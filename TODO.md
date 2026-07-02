# TODO — Фабрика гипотез

Журнал автономной сессии. Обновляется после каждой фазы.

## done
- [x] Проверка окружения: Python 3.13.1, node 24, git, диск ОК; данные распакованы в data/case/ (31 файл, NFC); .env заполнен, живой смоук LLM: HTTP 200, auth_style=raw, «работает», $0.026/вызов.
- [x] P0: git init, скаффолд backend/app (config, models, llm-клиент с retry/масками, FastAPI+CORS), domain_packs/flotation.yaml (синонимы меток, capture_rates, профили 8.2, онтология оборудования), pytest (5 passed), CI workflow, .env.example, .gitignore (.env, data/, *.zip).

## blocked
- (пусто)

## deferred
- [ ] typical_distribution в flotation.yaml — грубые диапазоны; уточнить по фактическим данным в P1.

## заметки
- data/case и zip НЕ коммитятся (203 МБ, read-only исходники кейса).
- Тесты, зависящие от data/case, имеют skipif для CI.
