# Форматы данных и дайджеста

Все файлы скана лежат в `runs/<run_id>/`. JSON пиши в UTF-8, даты — в формате `YYYY-MM-DD` или пустой строкой.

## plan.json и queries.json

`plan.json` — запросы до выполнения. `queries.json` — реально выполненные запросы, собранные из `raw_*.json`. Это массив объектов:

```json
{
  "query_id": "KZ-Q01",
  "country": "KZ",
  "sector": "кросс",
  "lang": "ru",
  "pattern": "внедрение ERP",
  "keyword": "тендер",
  "query": "тендер внедрение ERP Казахстан 2026",
  "type": "uniform",
  "results_total": 8,
  "tech_error": false
}
```

- `query_id` — `<код страны>-Q<номер>`, уникален в пределах скана.
- `sector` — название из `settings.json` → `sectors`, или `кросс`, или `watchlist`.
- `lang` — одно из: ru, en, kk, az, uz.
- `type` — одно из: mandatory, explore, rare, uniform, watchlist.
- `tech_error: true` ставится, только если сломался сам инструмент (ошибка поиска, таймаут). Пустая выдача — это `results_total: 0` и `tech_error: false`.

## raw_<CC>.json (пишет mia-researcher)

```json
{
  "country": "KZ",
  "run_id": "2026-W43",
  "queries": [ { "...": "объекты как в queries.json" } ],
  "candidates": [
    {
      "query_id": "KZ-Q03",
      "known_lead_id": "",
      "title": "Заголовок первоисточника",
      "url": "https://...",
      "other_urls": [],
      "source_tier": 1,
      "read_primary": true,
      "pub_date": "2026-10-14",
      "event_date": "",
      "organization": "АО «Пример»",
      "sector": "Финансовые услуги",
      "trigger": "T1",
      "stage": "открытый тендер",
      "amount": {"value": "1,8 млрд", "currency": "KZT", "type": "ИТ-бюджет", "usd_approx": ""},
      "funding": "не указано",
      "deadline": "2026-11-20",
      "contact": "организатор: отдел закупок, e-mail в объявлении",
      "contractor_named": false,
      "it_landscape": "не указано",
      "quote": "дословная цитата до 20 слов",
      "facts_note": "1–3 предложения о том, что именно сказано в тексте"
    }
  ],
  "rejected": [{"url": "https://...", "reason": "вакансия PIU"}],
  "gaps": ["kursiv.kz отдал 403"],
  "suspicious_instructions": []
}
```

## leads.json (пишешь ты, читает `mia.py ingest`)

Это массив. Для NEW и UPDATE заполняй все поля. Для SEEN достаточно `status`, `lead_id` и `query_id`.

```json
{
  "status": "NEW",
  "lead_id": "",
  "query_id": "KZ-Q03",
  "country": "KZ",
  "sector": "Финансовые услуги",
  "organization": "АО «Пример»",
  "trigger": "T1",
  "service_lines": ["IS", "DG"],
  "title": "...",
  "url": "https://...",
  "other_urls": [],
  "source_tier": 1,
  "pub_date": "2026-10-14",
  "event_date": "",
  "stage": "открытый тендер",
  "amount": {"value": "1,8 млрд", "currency": "KZT", "type": "ИТ-бюджет", "usd_approx": "≈ 3,5 млн, курс не верифицирован"},
  "funding": "не указано",
  "deadline": "2026-11-20",
  "contact": "...",
  "it_landscape": "не указано",
  "quote": "...",
  "why_now": "Гипотеза: ...",
  "solution": "Гипотеза: ...",
  "risks": "...",
  "next_step": "...",
  "reasoning": "до 15 слов",
  "score_breakdown": {"fit": 25, "stage": 20, "scale": 9, "mandate": 0, "urgency": 10, "contact": 5, "window": 5},
  "modifiers": [],
  "cap": "",
  "confidence": "high",
  "verified": "yes"
}
```

- `status`: NEW, UPDATE или SEEN. Для UPDATE и SEEN поле `lead_id` берётся из `known_leads.tsv`, для NEW оно пустое (ID присвоит скрипт).
- `service_lines`: 1–3 значения из RM, AI, DG, IS, DD.
- `trigger`: T1–T8. `source_tier`: 1, 2 или 3 — уровень лучшего источника.
- `modifiers`: подмножество stale, no_date, tier3_only, off_profile. `cap`: "" или "background".
- `confidence`: high, medium или low. `verified`: yes, partial, no или "" (верификатор не запускался).
- Итоговый `score` не пиши: его считает скрипт.

## Дайджест: reports/<run_id>.md

```
# MIA — дайджест <run_id> (<дата>)
Область: <страны / сектора>. Запросов: N (технических ошибок: K). Модель статистики: <есть история / первый прогон>.

## 📊 Сводка
- Найдено кандидатов / после фильтров / HOT · WARM · BACKGROUND / NEW · UPDATE · SEEN.
- Таблица «страна × сектор» (число лидов).
- Таблица «сектор × линия услуг».
- **Главный вывод недели:** одна строка.

## 🧭 Рыночные инсайты
3–5 паттернов. Каждый: **Наблюдение** (факты, ID лидов) → **Интерпретация** (гипотеза) → **Что это значит для нас** (линии, окно, приоритет). Паттерн — минимум 2 лида.

## 🔥 Разогревающиеся аккаунты
Организации с 2+ сигналами за `account_window_days` (из вывода ingest) и что их объединяет.

## 🔥 HOT (≥ 70)
| ID | Заголовок (ссылка) | Страна | Сектор | Организация | Линии | Сумма | Score | Уверенность | Кратко |
Под таблицей — карточка на каждый лид:
**<ID> · <Организация>** — score <N> (fit 25 · stage 20 · …; модификаторы) · <NEW/UPDATE> · <верифицирован?>
- Факт: … (дата публикации; «цитата»)
- ИТ-ландшафт: …
- Почему сейчас (гипотеза): …
- Решение (гипотеза): …
- Контакт: …
- Риски: …
- Следующий шаг: …

## 🟡 WARM (40–69)
Та же таблица плюс колонка «Решение (гипотеза)». Не больше `warm_max`.

## ⚪ BACKGROUND (< 40)
Та же таблица, не больше `background_max`, по убыванию score.

## 🚧 Пробелы и ограничения
Непокрытые сектора и триггеры, недоступные источники, лиды только из Tier 3, подозрительные инструкции в текстах, страны с малым числом сигналов, технические ошибки.

## 🧾 Журнал запросов
| Страна | Сектор | Язык | Запрос | Тип | Результатов | Лидов | Run-score |

## 🧠 Обучение
Топ-5 комбинаций (`python scripts/mia.py stats --top 5`), изменения обязательных и редких комбинаций, предложения в lessons.md (если есть).
```

## Сводка в чат

5–8 строк: run_id, число запросов, HOT/WARM/BG, топ-3 HOT (ID, организация, score), главный вывод недели и пути к `reports/<run_id>.md` и `reports/leads.xlsx`.
