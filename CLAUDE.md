# MIA — Market Intelligence Agent

Репозиторий агента рыночной разведки команды Data & Analytics. Агент ищет лиды на ИТ- и data-консалтинг в KZ, AZ и UZ.

- Вход: команда `/mia` (скилл `.claude/skills/mia/`). Еженедельный запуск — облачная рутина с промптом из `routine/prompt.md`.
- Субагенты: `mia-researcher` (поиск по стране) и `mia-verifier` (проверка фактов) в `.claude/agents/`.
- Всю арифметику (score, статистику, ID, Excel) делает `scripts/mia.py`. Числа в `data/*.csv` вручную не правь: запусти соответствующую команду скрипта.
- Источники истины: `data/leads.csv` (реестр), `data/query_stats.csv` (обучение), `data/lessons.md` (правила), `config/settings.json` (параметры). `reports/leads.xlsx` собирается из них заново при каждом запуске.
- Отметки команды приходят файлами в `inbox/` и загружаются командой `python scripts/mia.py feedback <файл>`.
