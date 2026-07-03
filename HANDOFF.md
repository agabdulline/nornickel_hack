# HANDOFF — как поднять проект на другом ПК и что где лежит

Шпаргалка для продолжения работы (агентом или человеком) на новой машине.
Подробное ТЗ — `CLAUDE.md`; журнал сделанного — `TODO.md`; продуктовое описание — `README.md`.

## Что это

«Фабрика гипотез» — MVP для хакатона Норникеля: xlsx-отчёт по хвостам флотации →
детерминированная диагностика потерь (R1–R5) → LLM-генерация проверяемых гипотез
с цитатами из литературы → ранжирование → дорожная карта испытаний → экспорт
DOCX/CSV/JSON. Backend FastAPI + SQLite + chromadb, frontend React/Vite/Tailwind
(6 экранов + чат-панель). Все фазы P0–P9 из CLAUDE.md выполнены, 68 pytest зелёные.

## Быстрый старт на новой машине

```bash
git clone https://github.com/GeorgeItsMe/hack_nornikil.git && cd hack_nornikil
pip install -r requirements.txt              # ядро (тесты/бэкенд работают)
pip install -r requirements-ml.txt           # опционально: dense-поиск bge-m3 (тянет torch)
cd frontend && npm install && cd ..
cp .env.example .env                         # вписать ключи (см. ниже)
pytest -q                                    # 68 passed (без data/case часть скипается)
python -m uvicorn backend.app.main:app --port 8000
cd frontend && npm run dev                   # http://127.0.0.1:5173
```

## Что НЕ в git (принести руками)

| Что | Куда положить | Откуда |
|---|---|---|
| Данные кейса (31 файл) | `data/case/` (структура: Пример 1..4, Дополнительные материалы, Схемы флотации, Регламенты) | архив «Задача 1. Фабрика гипотез.zip»; при распаковке снять префикс `Задача 1. Фабрика гипотез/Задача 1/`, имена нормализовать в NFC |
| Ключи | `.env` в корне | см. контракт ниже |
| Учебники для KB-корпуса | `data/kb/books/` (5 PDF) | копия из `data/case/Дополнительные материалы/` |
| Внешние источники KB | `data/kb/extra/` + `data/kb/sources.csv` | пересобрать: `python scripts/fetch_kb_sources.py` (по `kb_extra_sources.xlsx` из репо) |
| Индексы | `storage/` (KB приложения), `chroma/` (kb_yandex_v2) | пересобрать, см. ниже |
| Кэш эмбеддинг-модели | `models_cache/` | скачается сам при первом использовании bge-m3 (~2.3 ГБ) |

## Контракт .env (единственный источник LLM-конфига)

```
LLM_BASE_URL=https://ai.api.cloud.yandex.net/v1
LLM_API_KEY=<api-ключ Yandex Cloud>
LLM_MODEL_STRONG=gpt://<folder_id>/deepseek-v4-flash/latest
LLM_MODEL_FAST=gpt://<folder_id>/deepseek-v4-flash/latest
LLM_AUTH_STYLE=bearer          # bearer | raw (raw — для GPTunnel)
LLM_EXTRA_BODY=                # JSON, мёржится в тело запроса (GPTunnel: {"useWalletBalance": true})
EMBED_MODEL=BAAI/bge-m3        # локальные эмбеддинги приложения; fallback intfloat/multilingual-e5-small
```

Без ключа ВСЁ работает на моках (генерация — из `backend/tests/fixtures/generate_mock.json`
с заземлением цитат на локальный индекс). Ключ нигде не логируется (маска `AQVN3...ZsLP`).

## Карта репозитория

```
backend/app/            FastAPI-приложение
  parser/xlsx.py        парсер отчёта (нормализация «гуляющих» меток)
  parser/recover.py     восстановление битых ячеек: инварианты I1-I6 + LLM (7.1)
  diagnostics.py        правила R1-R5 (детерминированные, интерпретируемые)
  kb/                   KB приложения: BM25Plus + bge-m3 + RRF, авто-реиндекс (storage/kb)
  hypotheses/           generate (STRONG JSON) / verify (rapidfuzz>75) / rank / roadmap (Гант)
  chat.py               чат-интерпретатор со ссылками [R1]/[ячейка]/[chunk]
  export/               DOCX / tasks.csv / JSON
  api.py, store.py      роуты и SQLite (storage/app.db)
backend/tests/          68 тестов; LLM только моками; data-тесты скипаются без data/case
frontend/src/           6 экранов + чат-панель (Vite-прокси /api -> :8000)
domain_packs/flotation.yaml   ВСЯ доменка: синонимы меток, capture_rates, онтология
                        оборудования, профили проверки, типовые распределения,
                        intervention_menu (меню направлений для генерации)
kb/                     ОТДЕЛЬНЫЙ конвейер большого корпуса (см. ниже)
scripts/                demo_seed, fetch_kb_sources, smoke/index/check для kb_yandex_v2
eval/run_eval.py        бенчмарк против эталонных docx; отчёты в eval/report.md
```

## Конвейер KB-корпуса (kb/ + chroma/kb_yandex_v2)

Эмбеддинги Yandex AI Studio: OpenAI-совместимый `POST {LLM_BASE_URL}/embeddings`,
модели `emb://<folder>/text-embeddings-v2-doc/latest` (чанки) и
`.../text-embeddings-v2-query/latest` (запросы) — строго асимметрично, dim=256,
батча НЕТ (по одному тексту, до 8 параллельных, троттлинг 9 RPS).
Внимание: старые URI `text-search-doc/query` тоже отвечают, но это ДРУГАЯ модель
(cos между поколениями ~0.04) — не смешивать в одной коллекции. Порядок пересборки на новой машине:

```bash
python scripts/fetch_kb_sources.py     # 13 внешних источников -> data/kb/extra
python kb/chunking.py                  # 1146 чанков -> data/kb/chunks.jsonl (~500 ток., fix_mojibake для ГИАБ-PDF)
python scripts/smoke_yandex_embed.py   # разведка API (пишет data/kb/embed_api.json)
python scripts/index_kb_yandex.py      # индекс kb_yandex_v2 (--resume для дозаливки), ~10 мин
python scripts/check_kb_yandex.py      # 12 контрольных вопросов -> eval/yandex_embed_check.md
```

`kb/embedder_base.py` — интерфейс `Embedder` (embed_documents/embed_query) с фабрикой
`get_embedder(provider)` по env `EMBED_PROVIDER`. Реализован `yandex`;
**`local` — заглушка NotImplementedError, реализация планируется на другом ПК,
интерфейс не менять.**

Поиск по корпусу — `kb/search_hybrid.py`: BM25Plus + dense (взвешенный RRF,
dense_weight=2.0, калиброван по eval/kb_manual_check.md). Ручной запрос:
`python scripts/kb_query.py "запрос" [N] [--dense] [--with-gold]`. Чанкер
отфильтровывает служебные чанки (таблицы/оглавления/библиографию) — см.
is_service_chunk.

Сканы без текстового слоя: `python scripts/ocr_scan_book.py <pdf>` — Yandex Vision
OCR (квота ~1 rps, возобновляемый) → data/kb/ocr/<stem>.pages.jsonl → чанкер
подхватывает автоматически. Книга Лодейщикова (золото) уже распознана и помечена
type=book_gold — в Cu-Ni поиске исключается фильтром exclude_types={"book_gold"}.

OCR встроен и в ОСНОВНОЕ приложение: POST /api/kb/upload со сканом запускает
фоновый Vision OCR (backend/app/kb/ocr.py), прогресс в GET /api/kb/documents
(status=ocr_processing, ocr_done/pages), экран «База знаний» показывает
анимированный прогресс и бейдж «распознан (OCR)». Лодейщиков уже залит в
storage/kb (620 чанков bge-m3), /kb/ask отвечает по нему с точными страницами.

## Текущее состояние и цифры (2026-07-03)

- Живой демо-проект в storage/app.db: «НОФ · вкрапленные руды · Q2 2026», 13 гипотез
  (3 accepted / 1 testing), дорожная карта с конфликт-сдвигом.
- Eval (eval/report.md): 3 живых прогона; лучший (deepseek-v4-flash): parse_ok 4/4,
  coverage 59% (цель 60), citation_validity 95% (цель 90), novel 32.
- kb_yandex_v2: 1146 векторов, проверка выдачи — eval/yandex_embed_check.md
  (10/12 тем релевантны; слабые: кинетика флотации, доизмельчение промпродукта).
- Известные грабли: (1) PDF ГИАБ — битая кодировка текстового слоя, чинится
  fix_mojibake в kb/chunking.py автоматически; (2) vite на Windows слушает ::1 —
  в vite.config.ts прибит host 127.0.0.1; (3) НЕ переименовывать data/case, имена
  с кириллицей/NFC; (4) деньги: оборванные по таймауту LLM-вызовы не тарифицируются.
