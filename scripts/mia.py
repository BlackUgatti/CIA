#!/usr/bin/env python3
"""MIA bookkeeping: run ids, plan hints, lead registry, query statistics, Excel export.

Claude does the searching and the judgment. This script does the arithmetic and the
file housekeeping, so scores and statistics are computed the same way on every run.

Usage: python scripts/mia.py <command> [args]     (python scripts/mia.py --help)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RUNS = ROOT / "runs"
REPORTS = ROOT / "reports"
SETTINGS = ROOT / "config" / "settings.json"
LEADS = DATA / "leads.csv"
STATS = DATA / "query_stats.csv"
QLOG = DATA / "query_log.csv"
EXCLUSIONS = DATA / "exclusions.csv"
STATE = DATA / "state.json"
XLSX = REPORTS / "leads.xlsx"

LINES = {"RM", "AI", "DG", "IS", "DD"}
TRIGGERS = {f"T{i}" for i in range(1, 9)}
STATUSES = {"NEW", "UPDATE", "SEEN"}
QUERY_TYPES = {"mandatory", "explore", "rare", "uniform", "watchlist"}
LANGS = {"ru", "en", "kk", "az", "uz"}
CONFIDENCE = {"high", "medium", "low"}
VERIFIED = {"yes", "partial", "no", ""}
SCORE_RULES = {
    "fit": {0, 12, 25},
    "stage": {0, 6, 14, 20},
    "scale": {0, 4, 9, 15},
    "mandate": {0, 15},
    "urgency": {0, 10},
    "contact": {0, 5, 10},
    "window": {0, 5},
}
MODIFIERS = {"stale": -10, "no_date": -5, "tier3_only": -5, "off_profile": -15}
CAPS = {"", "background"}
SPECIAL_SECTORS = {"кросс", "watchlist"}

LEAD_FIELDS = [
    "lead_id", "first_run_id", "last_run_id", "first_seen", "last_seen", "seen_count",
    "status", "category", "score", "confidence", "verified",
    "country", "sector", "organization", "org_key", "trigger", "service_lines",
    "title", "url", "other_urls", "source_tier", "pub_date", "event_date", "stage",
    "amount_value", "amount_currency", "amount_type", "amount_usd_approx",
    "funding", "deadline", "contact", "it_landscape", "quote",
    "why_now", "solution", "risks", "next_step", "reasoning",
    "score_breakdown", "modifiers", "cap", "upsell", "query_id", "combo_key",
]
HUMAN_FIELDS = ["bd_owner", "bd_status", "verdict", "feedback_note", "feedback_date"]
ALL_LEAD_FIELDS = LEAD_FIELDS + HUMAN_FIELDS
QLOG_FIELDS = [
    "run_id", "scan_index", "date", "query_id", "country", "sector", "lang", "pattern",
    "keyword", "query", "type", "results_total", "tech_error", "leads_credited",
    "run_score", "hot", "combo_key",
]
STATS_FIELDS = [
    "combo_key", "country", "sector", "lang", "pattern", "keyword", "avg_score", "runs",
    "hot_runs", "confirmed", "irrelevant", "adj_score", "last_run_date", "last_scan_index",
]
EXCLUSION_FIELDS = ["organization", "type", "note"]

BD_STATUSES = ["новый", "в работе", "контакт", "встреча", "КП", "выигран", "проигран", "отложен"]
VERDICTS = ["релевантен", "нерелевантен", "уже клиент", "дубль", "устарел"]
CONFIRMED_STATUSES = {"в работе", "контакт", "встреча", "кп", "выигран", "проигран"}
IRRELEVANT_VERDICTS = {"нерелевантен", "устарел"}

HEADERS_RU = {
    "lead_id": "ID лида", "category": "Категория", "score": "Score", "confidence": "Уверенность",
    "verified": "Проверен", "status": "Статус", "country": "Страна", "sector": "Сектор",
    "organization": "Организация", "service_lines": "Линии услуг", "trigger": "Триггер",
    "title": "Заголовок", "url": "Ссылка", "pub_date": "Дата публикации", "stage": "Стадия",
    "amount_value": "Сумма", "amount_currency": "Валюта", "amount_type": "Тип суммы",
    "amount_usd_approx": "≈ USD", "funding": "Финансирование", "deadline": "Дедлайн",
    "contact": "Контакт", "it_landscape": "ИТ-ландшафт", "why_now": "Почему сейчас (гипотеза)",
    "solution": "Решение (гипотеза)", "risks": "Риски", "next_step": "Следующий шаг",
    "reasoning": "Кратко", "upsell": "Текущий клиент", "first_seen": "Впервые",
    "last_seen": "Последний раз", "bd_owner": "Ответственный (BD)", "bd_status": "Статус BD",
    "verdict": "Оценка команды", "feedback_note": "Комментарий", "feedback_date": "Дата отметки",
}
EXPORT_FIELDS = [
    "lead_id", "category", "score", "confidence", "verified", "status", "country", "sector",
    "organization", "service_lines", "trigger", "title", "url", "pub_date", "stage",
    "amount_value", "amount_currency", "amount_type", "amount_usd_approx", "funding", "deadline",
    "contact", "it_landscape", "why_now", "solution", "risks", "next_step", "reasoning", "upsell",
    "first_seen", "last_seen", *HUMAN_FIELDS,
]
LEGAL_FORMS = re.compile(
    r"\b(ао|ооо|тоо|пао|оао|зао|нао|ип|ук|нк|рго|ргп|гкп|гк|jsc|llp|llc|ltd|plc|ojsc|cjsc|"
    r"asc|qsc|mchj|aj|inc|corp|group|holding|холдинг|группа)\b"
)


# ---------- helpers ----------

def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def load_settings() -> dict:
    if not SETTINGS.exists():
        die(f"нет файла {SETTINGS.relative_to(ROOT)}")
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def read_csv(path: Path, fields: list[str]) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{k: (row.get(k) or "") for k in fields} for row in csv.DictReader(f)]


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def load_json(path: Path):
    if not path.exists():
        die(f"нет файла {path.relative_to(ROOT)}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"{path.relative_to(ROOT)}: невалидный JSON ({e})")


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"scan_count": 0, "runs": []}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_date(value: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def norm(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def org_key(name: str) -> str:
    s = norm(name).replace("ё", "е")
    s = re.sub(r"[«»\"'“”„()\[\],.:;!?&/\\\-]", " ", s)
    s = LEGAL_FORMS.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def combo_key(q: dict) -> str:
    return "|".join(norm(q.get(k)) for k in ("country", "sector", "lang", "pattern", "keyword"))


def to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def words(text: str) -> int:
    return len(str(text or "").split())


def md(value) -> str:
    """Make a value safe for a markdown table cell."""
    return str(value or "").replace("|", ", ").replace("\n", " ")


def load_exclusions() -> dict[str, str]:
    return {org_key(r["organization"]): norm(r["type"]) for r in read_csv(EXCLUSIONS, EXCLUSION_FIELDS)
            if r["organization"].strip()}


def category_for(score: int, params: dict) -> str:
    if score >= params["hot_threshold"]:
        return "HOT"
    if score >= params["warm_threshold"]:
        return "WARM"
    return "BACKGROUND"


def compute_score(lead: dict, params: dict) -> tuple[int, str, list[str]]:
    breakdown = lead["score_breakdown"]
    base = sum(int(breakdown[k]) for k in SCORE_RULES)
    mods = sum(MODIFIERS[m] for m in lead.get("modifiers", []))
    score = max(0, min(100, base + mods))
    caps = []
    hot_cap = params["hot_threshold"] - 1
    if not str(lead.get("solution", "")).strip() and score > hot_cap:
        score, caps = hot_cap, caps + ["нет гипотезы решения"]
    if int(lead.get("source_tier", 3)) == 3 and score > hot_cap:
        score, caps = hot_cap, caps + ["нет источника Tier 1/2"]
    if lead.get("cap") == "background" and score > params["warm_threshold"] - 1:
        score, caps = params["warm_threshold"] - 1, caps + ["cap: background"]
    return score, category_for(score, params), caps


# ---------- validation ----------

def validate_run(run_dir: Path, settings: dict, leads_db: list[dict]):
    params = settings["params"]
    errors: list[str] = []
    warnings: list[str] = []
    queries = load_json(run_dir / "queries.json")
    leads = load_json(run_dir / "leads.json")
    if not isinstance(queries, list) or not isinstance(leads, list):
        die("queries.json и leads.json должны быть массивами")

    countries = {c["code"] for c in settings["countries"]}
    sectors = set(settings["sectors"])
    qids: set[str] = set()
    for i, q in enumerate(queries):
        where = f"queries[{i}] ({q.get('query_id', '?')})"
        for field in ("query_id", "country", "sector", "lang", "query", "type"):
            if not str(q.get(field, "")).strip():
                errors.append(f"{where}: пустое поле {field}")
        if q.get("query_id") in qids:
            errors.append(f"{where}: повтор query_id")
        qids.add(q.get("query_id"))
        if q.get("country") not in countries:
            errors.append(f"{where}: страна {q.get('country')!r} не из settings.countries")
        if q.get("sector") not in sectors | SPECIAL_SECTORS:
            errors.append(f"{where}: сектор {q.get('sector')!r} не из settings.sectors / кросс / watchlist")
        if q.get("lang") not in LANGS:
            errors.append(f"{where}: lang должен быть одним из {sorted(LANGS)}")
        if q.get("type") not in QUERY_TYPES:
            errors.append(f"{where}: type должен быть одним из {sorted(QUERY_TYPES)}")
        if not isinstance(q.get("results_total"), int) or q["results_total"] < 0:
            errors.append(f"{where}: results_total должен быть целым ≥ 0")
        if not isinstance(q.get("tech_error"), bool):
            errors.append(f"{where}: tech_error должен быть true/false")

    existing = {r["lead_id"] for r in leads_db}
    freshness_cutoff = dt.date.today() - dt.timedelta(days=params["freshness_days"])
    new_urls: dict[str, int] = {}
    for i, lead in enumerate(leads):
        where = f"leads[{i}] ({str(lead.get('organization') or '')[:40] or lead.get('lead_id') or '?'})"
        status = lead.get("status")
        if status not in STATUSES:
            errors.append(f"{where}: status должен быть NEW/UPDATE/SEEN")
            continue
        if status in ("UPDATE", "SEEN") and lead.get("lead_id") not in existing:
            errors.append(f"{where}: lead_id {lead.get('lead_id')!r} не найден в data/leads.csv")
        if status == "NEW" and lead.get("lead_id"):
            warnings.append(f"{where}: у NEW lead_id игнорируется — ID присвоит скрипт")
        if status != "SEEN" and lead.get("query_id") not in qids:
            errors.append(f"{where}: query_id {lead.get('query_id')!r} нет в queries.json")
        if status == "SEEN":
            continue

        for field in ("country", "sector", "organization", "trigger", "title", "url"):
            if not str(lead.get(field, "")).strip():
                errors.append(f"{where}: пустое поле {field}")
        if lead.get("country") not in countries:
            errors.append(f"{where}: страна {lead.get('country')!r} не из settings.countries")
        if lead.get("sector") not in sectors:
            errors.append(f"{where}: сектор {lead.get('sector')!r} не из settings.sectors")
        if lead.get("trigger") not in TRIGGERS:
            errors.append(f"{where}: trigger должен быть T1–T8")
        lines = lead.get("service_lines")
        if not isinstance(lines, list) or not 1 <= len(lines) <= 3 or not set(lines) <= LINES:
            errors.append(f"{where}: service_lines — 1–3 значения из {sorted(LINES)}")
        if not str(lead.get("url", "")).startswith("http"):
            errors.append(f"{where}: url должен начинаться с http")
        if lead.get("source_tier") not in (1, 2, 3):
            errors.append(f"{where}: source_tier должен быть 1, 2 или 3")
        for field in ("pub_date", "event_date", "deadline"):
            value = str(lead.get(field, "") or "")
            if value and not parse_date(value):
                errors.append(f"{where}: {field} {value!r} — нужен YYYY-MM-DD или пусто")
        breakdown = lead.get("score_breakdown")
        if not isinstance(breakdown, dict) or set(breakdown) != set(SCORE_RULES):
            errors.append(f"{where}: score_breakdown должен содержать ровно {sorted(SCORE_RULES)}")
        else:
            for key, allowed in SCORE_RULES.items():
                if breakdown[key] not in allowed:
                    errors.append(f"{where}: score_breakdown.{key}={breakdown[key]!r}, допустимо {sorted(allowed)}")
        mods = lead.get("modifiers", [])
        if not isinstance(mods, list) or not set(mods) <= set(MODIFIERS) or len(mods) != len(set(mods)):
            errors.append(f"{where}: modifiers — без повторов из {sorted(MODIFIERS)}")
        if lead.get("cap", "") not in CAPS:
            errors.append(f"{where}: cap должен быть '' или 'background'")
        if lead.get("confidence") not in CONFIDENCE:
            errors.append(f"{where}: confidence должен быть high/medium/low")
        if str(lead.get("verified", "")) not in VERIFIED:
            errors.append(f"{where}: verified должен быть yes/partial/no или пусто")
        if lead.get("amount") is not None and not isinstance(lead.get("amount"), dict):
            errors.append(f"{where}: amount должен быть объектом")

        if words(lead.get("quote")) > 25:
            warnings.append(f"{where}: цитата длиннее 20 слов")
        if words(lead.get("reasoning")) > 15:
            warnings.append(f"{where}: reasoning длиннее 15 слов")
        pub = parse_date(lead.get("pub_date", ""))
        if not pub and "no_date" not in (mods or []):
            warnings.append(f"{where}: нет pub_date, но нет модификатора no_date")
        if pub and pub < freshness_cutoff and "stale" not in (mods or []) and lead.get("trigger") not in ("T1", "T5"):
            warnings.append(f"{where}: публикация старше {params['freshness_days']} дней — проверь модификатор stale")
        if lead.get("source_tier") == 3 and not lead.get("other_urls") and "tier3_only" not in (mods or []):
            warnings.append(f"{where}: единственный источник Tier 3 — проверь модификатор tier3_only")
        if status == "NEW":
            url = str(lead.get("url", "")).strip().rstrip("/")
            if url in new_urls:
                errors.append(f"{where}: тот же url, что у leads[{new_urls[url]}] — объедини дубли")
            new_urls[url] = i
    return queries, leads, errors, warnings


# ---------- statistics ----------

def recompute_feedback(stats: dict[str, dict], leads_db: list[dict]) -> None:
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in leads_db:
        key = row.get("combo_key")
        if not key:
            continue
        verdict, bd = norm(row.get("verdict")), norm(row.get("bd_status"))
        if verdict in IRRELEVANT_VERDICTS:
            counts[key][1] += 1
        elif verdict == "релевантен" or bd in CONFIRMED_STATUSES:
            counts[key][0] += 1
    for key, st in stats.items():
        confirmed, irrelevant = counts.get(key, (0, 0))
        st["confirmed"], st["irrelevant"] = confirmed, irrelevant
        f = (confirmed + 1) / (confirmed + irrelevant + 2)
        st["adj_score"] = round(min(100.0, to_float(st["avg_score"]) * (0.5 + f)), 1)


def accounts(leads_db: list[dict], window_days: int) -> list[dict]:
    cutoff = dt.date.today() - dt.timedelta(days=window_days)
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in leads_db:
        last = parse_date(row["last_seen"])
        if row["org_key"] and row["org_key"] != "не указано" and last and last >= cutoff:
            groups[row["org_key"]].append(row)
    result = []
    for key, rows in groups.items():
        scores = [to_int(r["score"]) for r in rows]
        result.append({
            "organization": max(rows, key=lambda r: to_int(r["score"]))["organization"],
            "org_key": key,
            "signals": len(rows),
            "max_score": max(scores),
            "hot": sum(r["category"] == "HOT" for r in rows),
            "countries": ", ".join(sorted({r["country"] for r in rows})),
            "sectors": ", ".join(sorted({r["sector"] for r in rows})),
            "lines": ", ".join(sorted({x for r in rows for x in r["service_lines"].split("|") if x})),
            "triggers": ", ".join(sorted({r["trigger"] for r in rows})),
            "lead_ids": ", ".join(r["lead_id"] for r in rows),
            "last_seen": max(r["last_seen"] for r in rows),
            "heating": len(rows) >= 2,
        })
    result.sort(key=lambda a: (a["signals"], a["max_score"]), reverse=True)
    return result


# ---------- commands ----------

def cmd_start(args) -> None:
    settings = load_settings()
    params = settings["params"]
    today = dt.date.today()
    iso = today.isocalendar()
    base = f"{iso[0]}-W{iso[1]:02d}"
    run_id, n = base, 1
    while (RUNS / run_id / ".ingested").exists():
        n += 1
        run_id = f"{base}-{n}"
    run_dir = RUNS / run_id
    resumed = run_dir.exists()
    run_dir.mkdir(parents=True, exist_ok=True)

    country_by_token = {}
    for c in settings["countries"]:
        country_by_token[norm(c["code"])] = c["code"]
        country_by_token[norm(c["name"])] = c["code"]
    scope_countries, scope_sectors, unmatched = [], [], []
    for token in args.scope or []:
        t = norm(token)
        if t in country_by_token:
            scope_countries.append(country_by_token[t])
            continue
        hits = [s for s in settings["sectors"] if t in norm(s)]
        if hits:
            scope_sectors.extend(hits)
        else:
            unmatched.append(token)
    countries = scope_countries or [c["code"] for c in settings["countries"]]

    state = load_state()
    scan_index = state["scan_count"] + 1
    stats = read_csv(STATS, STATS_FIELDS)
    qlog = read_csv(QLOG, QLOG_FIELDS)
    stale_cutoff = today - dt.timedelta(days=params["stale_days"])

    hints = {}
    for cc in countries:
        own = [s for s in stats if norm(s["country"]) == norm(cc)]
        def brief(s):
            return {k: s[k] for k in ("sector", "lang", "pattern", "keyword", "adj_score", "runs")}
        mandatory = sorted(
            (s for s in own if to_int(s["runs"]) >= params["mandatory_min_runs"]
             and to_float(s["adj_score"]) >= params["mandatory_min_avg"]),
            key=lambda s: to_float(s["adj_score"]), reverse=True)
        cap = math.floor(params["mandatory_max_share"] * params["min_queries_per_country"])
        low = [s for s in own if to_int(s["runs"]) >= params["rare_min_runs"]
               and to_float(s["adj_score"]) <= params["rare_max_avg"]]
        rare_eligible = [s for s in low
                         if scan_index - to_int(s["last_scan_index"]) >= params["rare_every_n_scans"]]
        rare_blocked = [s for s in low if s not in rare_eligible]
        stale = [s for s in own if to_int(s["runs"]) > 0
                 and (parse_date(s["last_run_date"]) or today) < stale_cutoff]
        last_by_sector = {}
        for row in qlog:
            if norm(row["country"]) == norm(cc) and row["sector"] not in SPECIAL_SECTORS:
                last_by_sector[row["sector"]] = max(last_by_sector.get(row["sector"], ""), row["date"])
        sector_pool = scope_sectors or settings["sectors"]
        order = sorted(sector_pool, key=lambda s: (s not in settings.get("priority_sectors", []),
                                                    last_by_sector.get(s, "")))
        hints[cc] = {
            "mandatory": [brief(s) for s in mandatory[:cap]],
            "mandatory_overflow": len(mandatory) - min(len(mandatory), cap),
            "rare_eligible": [brief(s) for s in rare_eligible],
            "rare_blocked_this_scan": [brief(s) for s in rare_blocked],
            "stale_for_exploration": [brief(s) for s in stale],
            "sector_order": [("★ " if s in settings.get("priority_sectors", []) else "")
                             + f"{s} — {last_by_sector.get(s, 'никогда')}" for s in order],
        }

    leads_db = read_csv(LEADS, ALL_LEAD_FIELDS)
    known_cutoff = (today - dt.timedelta(days=params["known_leads_days"])).isoformat()
    known_path = run_dir / "known_leads.tsv"
    with known_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        cols = ["lead_id", "last_seen", "country", "org_key", "organization", "trigger", "category", "score", "title", "url"]
        writer.writerow(cols)
        for row in leads_db:
            if row["last_seen"] >= known_cutoff:
                writer.writerow([row[c] for c in cols])

    watchlist = [w for w in settings.get("watchlist", [])
                 if not w.get("expires") or (parse_date(w["expires"]) or today) >= today]
    total_queries = params["min_queries_per_country"] * len(countries)
    context = {
        "run_id": run_id,
        "resumed_unfinished_run": resumed,
        "today": today.isoformat(),
        "iso_week": base,
        "scan_index": scan_index,
        "history": "есть" if stats else "нет — первый прогон, запросы распределяются равномерно",
        "freshness_cutoff": (today - dt.timedelta(days=params["freshness_days"])).isoformat(),
        "scope": {"countries": countries, "sectors": scope_sectors or "все", "unmatched_tokens": unmatched},
        "minimums": {
            "queries_per_country": params["min_queries_per_country"] if not scope_sectors else 4,
            "cross_queries_per_country": params["cross_queries_per_country"] if not scope_sectors else 0,
            "exploration_min_total": math.ceil(params["exploration_share"] * total_queries),
            "max_queries_per_country": params["max_queries_per_country"],
        },
        "plan_hints": hints,
        "watchlist_active": watchlist,
        "known_leads_file": str(known_path.relative_to(ROOT)).replace("\\", "/"),
        "known_leads_count": sum(1 for r in leads_db if r["last_seen"] >= known_cutoff),
        "run_dir": str(run_dir.relative_to(ROOT)).replace("\\", "/"),
    }
    (run_dir / "context.json").write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    emit(context)


def cmd_validate(args) -> None:
    settings = load_settings()
    run_dir = RUNS / args.run_id
    leads_db = read_csv(LEADS, ALL_LEAD_FIELDS)
    _, leads, errors, warnings = validate_run(run_dir, settings, leads_db)
    preview = []
    if not errors:
        for i, lead in enumerate(leads):
            if lead["status"] != "SEEN":
                score, category, caps = compute_score(lead, settings["params"])
                preview.append({"index": i, "organization": lead["organization"], "score": score,
                                "category": category, "caps": caps})
    emit({"errors": errors, "warnings": warnings, "preview": preview})
    if errors:
        sys.exit(1)


def lead_to_row(lead: dict, score: int, category: str, upsell: str, q_by_id: dict) -> dict:
    amount = lead.get("amount") or {}
    breakdown = lead["score_breakdown"]
    query = q_by_id.get(lead.get("query_id"), {})
    return {
        "status": lead["status"], "category": category, "score": str(score),
        "confidence": lead["confidence"], "verified": str(lead.get("verified", "")),
        "country": lead["country"], "sector": lead["sector"], "organization": lead["organization"],
        "org_key": org_key(lead["organization"]), "trigger": lead["trigger"],
        "service_lines": "|".join(lead["service_lines"]), "title": lead["title"], "url": lead["url"],
        "other_urls": " | ".join(lead.get("other_urls") or []), "source_tier": str(lead["source_tier"]),
        "pub_date": lead.get("pub_date", ""), "event_date": lead.get("event_date", ""),
        "stage": lead.get("stage", ""), "amount_value": amount.get("value", ""),
        "amount_currency": amount.get("currency", ""), "amount_type": amount.get("type", ""),
        "amount_usd_approx": amount.get("usd_approx", ""), "funding": lead.get("funding", ""),
        "deadline": lead.get("deadline", ""), "contact": lead.get("contact", ""),
        "it_landscape": lead.get("it_landscape", ""), "quote": lead.get("quote", ""),
        "why_now": lead.get("why_now", ""), "solution": lead.get("solution", ""),
        "risks": lead.get("risks", ""), "next_step": lead.get("next_step", ""),
        "reasoning": lead.get("reasoning", ""),
        "score_breakdown": ";".join(f"{k}={breakdown[k]}" for k in SCORE_RULES),
        "modifiers": ",".join(lead.get("modifiers") or []), "cap": lead.get("cap", ""),
        "upsell": upsell, "query_id": lead["query_id"], "combo_key": combo_key(query) if query else "",
    }


def cmd_ingest(args) -> None:
    settings = load_settings()
    params = settings["params"]
    run_id = args.run_id
    run_dir = RUNS / run_id
    if not run_dir.exists():
        die(f"нет папки runs/{run_id} — сначала python scripts/mia.py start")
    if (run_dir / ".ingested").exists():
        die(f"скан {run_id} уже загружен; повторная загрузка исказила бы статистику")
    leads_db = read_csv(LEADS, ALL_LEAD_FIELDS)
    queries, leads, errors, warnings = validate_run(run_dir, settings, leads_db)
    if errors:
        emit({"errors": errors, "warnings": warnings})
        print("Ничего не записано. Исправь JSON и повтори ingest.", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    scan_index = state["scan_count"] + 1
    run_date = dt.date.today().isoformat()
    by_id = {r["lead_id"]: r for r in leads_db}
    exclusions = load_exclusions()
    q_by_id = {q["query_id"]: q for q in queries}
    next_num: dict[str, int] = defaultdict(int)
    for lead_id in by_id:
        m = re.fullmatch(re.escape(run_id) + r"-([A-Z]+)-(\d+)", lead_id)
        if m:
            next_num[m.group(1)] = max(next_num[m.group(1)], int(m.group(2)))

    credited: dict[str, list[tuple[int, str]]] = defaultdict(list)
    assigned, skipped = [], []
    counts = defaultdict(int)
    for i, lead in enumerate(leads):
        status = lead["status"]
        counts[status] += 1
        if status == "SEEN":
            row = by_id[lead["lead_id"]]
            row.update(last_seen=run_date, last_run_id=run_id, status="SEEN",
                       seen_count=str(to_int(row["seen_count"], 1) + 1))
            continue
        kind = exclusions.get(org_key(lead["organization"]))
        if kind == "blacklist":
            skipped.append(f"leads[{i}] {lead['organization']}: в blacklist")
            continue
        score, category, caps = compute_score(lead, params)
        fields = lead_to_row(lead, score, category, "да" if kind == "client" else "", q_by_id)
        fields.update(last_seen=run_date, last_run_id=run_id)
        if status == "NEW":
            next_num[lead["country"]] += 1
            lead_id = f"{run_id}-{lead['country']}-{next_num[lead['country']]:02d}"
            row = {k: "" for k in ALL_LEAD_FIELDS}
            row.update(fields, lead_id=lead_id, first_run_id=run_id, first_seen=run_date, seen_count="1")
            leads_db.append(row)
            by_id[lead_id] = row
        else:
            row = by_id[lead["lead_id"]]
            keep = {k: row[k] for k in ("lead_id", "first_run_id", "first_seen", "query_id", "combo_key", *HUMAN_FIELDS)}
            row.update(fields)
            row.update(keep, seen_count=str(to_int(row["seen_count"], 1) + 1))
        credited[lead["query_id"]].append((score, category))
        counts[category] += 1
        assigned.append({"index": i, "lead_id": row["lead_id"], "status": status, "organization": lead["organization"],
                         "country": lead["country"], "sector": lead["sector"], "lines": lead["service_lines"],
                         "score": score, "category": category, "caps": caps, "upsell": kind == "client"})

    stats = {r["combo_key"]: r for r in read_csv(STATS, STATS_FIELDS)}
    qlog = read_csv(QLOG, QLOG_FIELDS)
    for q in queries:
        key = combo_key(q)
        creds = credited.get(q["query_id"], [])
        top = sorted((s for s, _ in creds), reverse=True)[:3]
        run_score = round(sum(top) / len(top), 1) if top else 0.0
        hot = any(c == "HOT" for _, c in creds)
        qlog.append({
            "run_id": run_id, "scan_index": scan_index, "date": run_date, "query_id": q["query_id"],
            "country": q["country"], "sector": q["sector"], "lang": q["lang"],
            "pattern": q.get("pattern", ""), "keyword": q.get("keyword", ""), "query": q["query"],
            "type": q["type"], "results_total": q["results_total"], "tech_error": int(q["tech_error"]),
            "leads_credited": len(creds), "run_score": run_score, "hot": int(hot), "combo_key": key,
        })
        if q["type"] == "watchlist" or q["tech_error"]:
            continue
        st = stats.get(key) or {
            "combo_key": key, "country": q["country"], "sector": q["sector"], "lang": q["lang"],
            "pattern": q.get("pattern", ""), "keyword": q.get("keyword", ""), "avg_score": 0, "runs": 0,
            "hot_runs": 0, "confirmed": 0, "irrelevant": 0, "adj_score": 0, "last_run_date": "",
            "last_scan_index": 0,
        }
        runs = to_int(st["runs"])
        st["avg_score"] = round((to_float(st["avg_score"]) * runs + run_score) / (runs + 1), 1)
        st["runs"] = runs + 1
        st["hot_runs"] = to_int(st["hot_runs"]) + int(hot)
        st["last_run_date"] = run_date
        st["last_scan_index"] = scan_index
        stats[key] = st
    recompute_feedback(stats, leads_db)

    write_csv(LEADS, ALL_LEAD_FIELDS, leads_db)
    write_csv(QLOG, QLOG_FIELDS, qlog)
    write_csv(STATS, STATS_FIELDS, sorted(stats.values(), key=lambda s: (s["country"], -to_float(s["adj_score"]))))
    state["scan_count"] = scan_index
    state["runs"].append({"run_id": run_id, "date": run_date, "scan_index": scan_index,
                          "queries": len(queries), "tech_errors": sum(q["tech_error"] for q in queries),
                          "new": counts["NEW"], "update": counts["UPDATE"], "seen": counts["SEEN"],
                          "hot": counts["HOT"], "warm": counts["WARM"], "background": counts["BACKGROUND"]})
    save_state(state)
    (run_dir / ".ingested").write_text(run_date, encoding="utf-8")

    matrix_cs: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    matrix_sl: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for a in assigned:
        matrix_cs[a["country"]][a["sector"]] += 1
        for line in a["lines"]:
            matrix_sl[a["sector"]][line] += 1
    xlsx_note = build_xlsx(settings)
    emit({
        "run_id": run_id, "scan_index": scan_index,
        "counts": {k: counts[k] for k in ("NEW", "UPDATE", "SEEN", "HOT", "WARM", "BACKGROUND")},
        "queries": len(queries), "tech_errors": sum(q["tech_error"] for q in queries),
        "leads": sorted(assigned, key=lambda a: -a["score"]),
        "country_x_sector": matrix_cs, "sector_x_line": matrix_sl,
        "heating_accounts": [a for a in accounts(leads_db, params["account_window_days"]) if a["heating"]][:10],
        "skipped": skipped, "warnings": warnings, "xlsx": xlsx_note,
    })


def cmd_feedback(args) -> None:
    settings = load_settings()
    path = Path(args.path)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        die(f"нет файла {args.path}")
    rows = read_feedback(path)
    leads_db = read_csv(LEADS, ALL_LEAD_FIELDS)
    by_id = {r["lead_id"]: r for r in leads_db}
    applied, unknown = 0, []
    today = dt.date.today().isoformat()
    for fb in rows:
        lead_id = fb.get("lead_id", "").strip()
        if not lead_id:
            continue
        row = by_id.get(lead_id)
        if row is None:
            unknown.append(lead_id)
            continue
        changed = False
        for field in ("bd_owner", "bd_status", "verdict", "feedback_note"):
            value = str(fb.get(field, "") or "").strip()
            if value and value != row[field]:
                row[field] = value
                changed = True
        if changed:
            row["feedback_date"] = str(fb.get("feedback_date") or today).strip()[:10]
            applied += 1
    stats = {r["combo_key"]: r for r in read_csv(STATS, STATS_FIELDS)}
    recompute_feedback(stats, leads_db)
    write_csv(LEADS, ALL_LEAD_FIELDS, leads_db)
    write_csv(STATS, STATS_FIELDS, sorted(stats.values(), key=lambda s: (s["country"], -to_float(s["adj_score"]))))
    xlsx_note = build_xlsx(settings)
    emit({"applied": applied, "unknown_lead_ids": unknown, "calibration": calibration(leads_db),
          "irrelevant": [{"lead_id": r["lead_id"], "organization": r["organization"], "category": r["category"],
                          "sector": r["sector"], "trigger": r["trigger"], "note": r["feedback_note"],
                          "combo_key": r["combo_key"]}
                         for r in leads_db if norm(r["verdict"]) in IRRELEVANT_VERDICTS][-30:],
          "xlsx": xlsx_note})


def read_feedback(path: Path) -> list[dict]:
    reverse = {norm(v): k for k, v in HEADERS_RU.items()}
    reverse.update({k: k for k in ALL_LEAD_FIELDS})

    def map_row(header: list, values: list) -> dict:
        out = {}
        for h, v in zip(header, values):
            field = reverse.get(norm(h))
            if field:
                out[field] = "" if v is None else str(v)
        return out

    if path.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            die("для xlsx нужен openpyxl: pip install openpyxl")
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb["Лиды"] if "Лиды" in wb.sheetnames else wb.active
        it = ws.iter_rows(values_only=True)
        header = list(next(it, []))
        return [map_row(header, list(r)) for r in it]
    text = path.read_text(encoding="utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(text.split("\n", 1)[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, [])
    return [map_row(header, r) for r in reader]


def calibration(leads_db: list[dict]) -> dict:
    result = {}
    for cat in ("HOT", "WARM", "BACKGROUND"):
        rated = [r for r in leads_db if r["category"] == cat and
                 (norm(r["verdict"]) in IRRELEVANT_VERDICTS | {"релевантен"} or norm(r["bd_status"]) in CONFIRMED_STATUSES)]
        good = [r for r in rated if norm(r["verdict"]) not in IRRELEVANT_VERDICTS]
        result[cat] = {"rated": len(rated), "relevant": len(good),
                       "precision": round(len(good) / len(rated), 2) if rated else None}
    return result


def cmd_stats(args) -> None:
    settings = load_settings()
    stats = read_csv(STATS, STATS_FIELDS)
    state = load_state()
    leads_db = read_csv(LEADS, ALL_LEAD_FIELDS)
    if args.summary:
        emit({"scans": state["scan_count"], "last_run": state["runs"][-1] if state["runs"] else None,
              "leads_total": len(leads_db), "combos": len(stats), "calibration": calibration(leads_db),
              "countries": [c["code"] for c in settings["countries"]], "sectors": len(settings["sectors"])})
        return
    rows = sorted(stats, key=lambda s: -to_float(s["adj_score"]))
    if args.top:
        rows = [s for s in rows if to_int(s["runs"]) >= 2][: args.top]
        title = f"Топ-{args.top} комбинаций (2+ прогона)"
    else:
        rows = sorted(stats, key=lambda s: (s["country"], -to_float(s["adj_score"])))
        title = "Статистика обучения"
    print(f"## {title}  (сканов: {state['scan_count']})\n")
    if not rows:
        print("Пока нет данных.")
        return
    print("| Страна | Сектор | Язык | Паттерн | Ключевое слово | avg | adj | Прогонов | Hot-прогонов | +/− | Последний |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in rows:
        print(f"| {s['country']} | {md(s['sector'])} | {s['lang']} | {md(s['pattern'])} | {md(s['keyword'])} | "
              f"{s['avg_score']} | {s['adj_score']} | {s['runs']} | {s['hot_runs']} | {s['confirmed']}/{s['irrelevant']} | "
              f"{s['last_run_date']} |")


def cmd_hot(args) -> None:
    state = load_state()
    if not state["runs"]:
        print("Нет данных последнего скана. Запустите /mia scan.")
        return
    run_id = args.run or state["runs"][-1]["run_id"]
    cats = {"HOT", "WARM"} if args.warm else {"HOT"}
    rows = [r for r in read_csv(LEADS, ALL_LEAD_FIELDS)
            if r["last_run_id"] == run_id and r["status"] in ("NEW", "UPDATE") and r["category"] in cats]
    rows.sort(key=lambda r: -to_int(r["score"]))
    print(f"## {' + '.join(sorted(cats))} — скан {run_id}\n")
    if not rows:
        print("Нет лидов этой категории.")
        return
    print("| ID | Организация | Страна | Сектор | Линии | Score | Уверенность | Кратко | Ссылка |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['lead_id']} | {md(r['organization'])} | {r['country']} | {md(r['sector'])} | {md(r['service_lines'])} | "
              f"{r['score']} | {r['confidence']} | {md(r['reasoning'])} | {r['url']} |")


def cmd_report(args) -> None:
    print(build_xlsx(load_settings()))


def cmd_reset_stats(args) -> None:
    if not args.confirm:
        die("нужен флаг --confirm")
    archive = DATA / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    if STATS.exists():
        shutil.copy2(STATS, archive / f"query_stats-{stamp}.csv")
    write_csv(STATS, STATS_FIELDS, [])
    print(f"Статистика сброшена, копия: data/archive/query_stats-{stamp}.csv. Журнал запросов и реестр лидов не тронуты.")


# ---------- Excel ----------

def build_xlsx(settings: dict) -> str:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
        from openpyxl.worksheet.datavalidation import DataValidation
    except ImportError:
        return "openpyxl не установлен — xlsx не собран (pip install openpyxl); CSV в data/ актуальны"

    params = settings["params"]
    leads_db = read_csv(LEADS, ALL_LEAD_FIELDS)
    state = load_state()
    last_run = state["runs"][-1]["run_id"] if state["runs"] else ""
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="1F3864")
    human_fill = PatternFill("solid", fgColor="FFF2CC")
    cat_fill = {"HOT": PatternFill("solid", fgColor="F8CBAD"), "WARM": PatternFill("solid", fgColor="FFE699"),
                "BACKGROUND": PatternFill("solid", fgColor="E7E6E6")}
    widths = {"lead_id": 18, "title": 45, "url": 30, "organization": 28, "why_now": 40, "solution": 45,
              "risks": 35, "next_step": 35, "reasoning": 30, "it_landscape": 30, "contact": 25,
              "feedback_note": 30, "sector": 22, "stage": 20, "funding": 22}

    def sheet(ws, fields: list[str], rows: list[dict], headers: dict, editable: set[str] = frozenset()):
        ws.append([headers.get(f, f) for f in fields])
        for cell in ws[1]:
            cell.font, cell.fill = head_font, head_fill
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        for row in rows:
            ws.append([row.get(f, "") for f in fields])
        for idx, f in enumerate(fields, start=1):
            letter = get_column_letter(idx)
            ws.column_dimensions[letter].width = widths.get(f, 14)
            for cell in ws[letter][1:]:
                cell.alignment = Alignment(wrap_text=f in widths, vertical="top")
                if f in editable:
                    cell.fill = human_fill
                if f == "category" and cell.value in cat_fill:
                    cell.fill = cat_fill[cell.value]
                if f == "url" and str(cell.value).startswith("http"):
                    cell.hyperlink = cell.value
                    cell.font = Font(color="0563C1", underline="single")
                if f == "score" and str(cell.value).isdigit():
                    cell.value = int(cell.value)
                if f == "service_lines" and cell.value:
                    cell.value = str(cell.value).replace("|", ", ")
        ws.freeze_panes = "B2"
        if rows:
            ws.auto_filter.ref = ws.dimensions

    wb = Workbook()
    ws = wb.active
    ws.title = "Лиды"
    rows = sorted(leads_db, key=lambda r: (r["last_seen"], to_int(r["score"])), reverse=True)
    sheet(ws, EXPORT_FIELDS, rows, HEADERS_RU, editable=set(HUMAN_FIELDS))
    max_row = max(len(rows) + 1, 2) + 500
    for field, options in (("bd_status", BD_STATUSES), ("verdict", VERDICTS)):
        col = get_column_letter(EXPORT_FIELDS.index(field) + 1)
        dv = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}{max_row}")

    week = [r for r in rows if r["last_run_id"] == last_run and r["status"] in ("NEW", "UPDATE")
            and r["category"] in ("HOT", "WARM")]
    week.sort(key=lambda r: -to_int(r["score"]))
    sheet(wb.create_sheet("Эта неделя"), EXPORT_FIELDS[:29], week, HEADERS_RU)

    acc = accounts(leads_db, params["account_window_days"])
    acc_fields = ["organization", "signals", "hot", "max_score", "countries", "sectors", "lines", "triggers",
                  "lead_ids", "last_seen"]
    acc_headers = {"organization": "Организация", "signals": "Сигналов", "hot": "HOT", "max_score": "Макс. score",
                   "countries": "Страны", "sectors": "Сектора", "lines": "Линии", "triggers": "Триггеры",
                   "lead_ids": "ID лидов", "last_seen": "Последний сигнал"}
    sheet(wb.create_sheet("Аккаунты"), acc_fields, acc, acc_headers)

    stats = sorted(read_csv(STATS, STATS_FIELDS), key=lambda s: -to_float(s["adj_score"]))
    st_headers = {"country": "Страна", "sector": "Сектор", "lang": "Язык", "pattern": "Паттерн",
                  "keyword": "Ключевое слово", "avg_score": "Средний score", "adj_score": "Score с учётом отметок",
                  "runs": "Прогонов", "hot_runs": "Hot-прогонов", "confirmed": "Подтверждено",
                  "irrelevant": "Нерелевантно", "last_run_date": "Последний прогон"}
    sheet(wb.create_sheet("Статистика запросов"), list(st_headers), stats, st_headers)

    help_ws = wb.create_sheet("Как заполнять")
    lines = [
        "Как работать с реестром MIA",
        "",
        "1. Лист «Эта неделя» — HOT и WARM последнего скана. Лист «Лиды» — весь реестр.",
        "2. Заполняйте только жёлтые колонки на листе «Лиды»: Ответственный (BD), Статус BD, Оценка команды, Комментарий.",
        "3. Статус BD: " + ", ".join(BD_STATUSES) + ".",
        "4. Оценка команды: " + ", ".join(VERDICTS) + ".",
        "   «нерелевантен» и «устарел» учат агента реже искать похожее; «релевантен» и рабочие статусы — чаще.",
        "   В комментарии коротко объясните почему: из этих комментариев агент предлагает новые правила.",
        "5. Сохраните файл и передайте владельцу агента — он загрузит отметки командой /mia feedback.",
        "6. Колонки «Почему сейчас» и «Решение» — гипотезы агента, а не факты. Факты — в колонках с суммой, датами и ссылкой.",
        "",
        f"Пороги: HOT ≥ {params['hot_threshold']}, WARM ≥ {params['warm_threshold']}. Обновлено: {dt.date.today().isoformat()}.",
    ]
    for line in lines:
        help_ws.append([line])
    help_ws["A1"].font = Font(bold=True, size=14)
    help_ws.column_dimensions["A"].width = 120

    REPORTS.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(XLSX)
    except PermissionError:
        return f"{XLSX.relative_to(ROOT)} открыт в Excel — закройте файл и выполните python scripts/mia.py report"
    return str(XLSX.relative_to(ROOT)).replace("\\", "/")


# ---------- CLI ----------

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="MIA: учёт сканов, лидов и статистики запросов")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("start", help="начать скан: run_id, даты, подсказки по плану, известные лиды")
    p.add_argument("--scope", nargs="*", help="страны и/или сектора для частичного скана")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("validate", help="проверить runs/<run_id>/*.json без записи")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("ingest", help="загрузить результаты скана в реестр и статистику")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("feedback", help="влить отметки команды из xlsx/csv")
    p.add_argument("path")
    p.set_defaults(func=cmd_feedback)

    p = sub.add_parser("stats", help="статистика обучения")
    p.add_argument("--top", type=int, default=0)
    p.add_argument("--summary", action="store_true")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("hot", help="HOT (и WARM с --warm) последнего скана")
    p.add_argument("--run")
    p.add_argument("--warm", action="store_true")
    p.set_defaults(func=cmd_hot)

    p = sub.add_parser("report", help="пересобрать reports/leads.xlsx")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("reset-stats", help="архивировать и обнулить статистику запросов")
    p.add_argument("--confirm", action="store_true")
    p.set_defaults(func=cmd_reset_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
