# Развёртывание «Фабрики гипотез»

Прод-стек в Docker: **бэкенд** (FastAPI + KB на sentence-transformers/chromadb) и
**фронтенд** (Vite-сборка, раздаётся nginx-ом контейнера, он же проксирует `/api`
на бэкенд). Наружу торчит только один порт на `127.0.0.1`; публичный домен и TLS
даёт **системный nginx** хоста.

```
Интернет ──HTTPS──► системный nginx (host, :443)
                      └─ server_name nornickel.indata.group
                         proxy_pass → 127.0.0.1:8012
                                        │
                        ┌───────────────┴───────────────┐  docker-compose (project: nornickel)
                        │  web (nginx:alpine)            │
                        │   • отдаёт SPA (dist)          │
                        │   • /api/ → http://backend:8000│
                        │  публикует 127.0.0.1:8012:80   │
                        │                                │
                        │  backend (uvicorn, :8000)      │
                        │   тома: storage/ models_cache/ │
                        │   монтирует data/ (ro)         │
                        └────────────────────────────────┘
```

## Быстрый старт на чистом сервере (по порту, без домена)

Нужен только **Docker**. Данные кейса (`data/`) и `.env` не в git — заливаем всё дерево одним rsync-ом.

**На своей машине** (доставить код + данные + ключи):
```bash
rsync -az --exclude=node_modules --exclude=.venv --exclude=dist \
  --exclude=storage --exclude=models_cache --exclude=__pycache__ --exclude=.git \
  ./ USER@SERVER:/opt/nornickel/
```

**На сервере** (`cd /opt/nornickel`):
```bash
curl -fsSL https://get.docker.com | sh                            # 1. Docker (если ещё нет)
cp -n .env.example .env    # 2. конфиг (если .env не приехал); впишите LLM_API_KEY — без него моки
DC="docker compose -f deploy/docker-compose.yml"
$DC build                                                         # 3. сборка образов
$DC run --rm backend python -u scripts/demo_seed.py               # 4. демо-данные (опц.; на CPU ~минуты)
WEB_BIND=0.0.0.0:8080 $DC up -d                                   # 5. запуск на :8080
```

Открыть **`http://SERVER:8080`** (файрвол: `sudo ufw allow 8080`). Здоровье: `curl http://localhost:8080/api/health`.

- Порт меняется в `WEB_BIND` (напр. `0.0.0.0:80`).
- Шаг 4 (сид) — **отдельный one-off контейнер до `up`**, чтобы не конфликтовать за индекс БЗ с работающим бэкендом. Можно пропустить — отчёты и PDF грузятся через UI; тогда шаги 3+5 сворачиваются в `WEB_BIND=0.0.0.0:8080 $DC up -d --build`.

---

## Что где на этом сервере (`feedly`, 81.26.178.170)

| | |
|---|---|
| Каталог приложения | `/home/mac/nornickel` |
| Compose-проект | `nornickel` (`deploy/docker-compose.yml`) |
| Порт на хосте | `127.0.0.1:8012` (только web-контейнер) |
| Домен | `https://nornickel.indata.group` |
| nginx-сайт | `/etc/nginx/sites-available/nornickel` → `sites-enabled/nornickel` |
| TLS | Let's Encrypt `/etc/letsencrypt/live/nornickel.indata.group/` (авто-renew) |
| Тома данных | `nornickel_storage` (sqlite + индекс KB), `nornickel_models` (кэш bge-m3) |
| Эмбеддер | `BAAI/bge-m3` (`EMBED_MODEL` в `.env`) |

Стек **изолирован**: собственный compose-проект, собственные тома и сеть, порт
только на localhost, отдельный nginx-server-block и отдельный TLS-сертификат.
Ничего из уже работающего на сервере (feedly, indata, empire-poker, postgres/redis/…)
не затрагивается.

## Требования на хосте

- Docker + Docker Compose plugin (`docker compose`), пользователь в группе `docker`.
- Системный nginx + certbot (для домена и TLS).
- ~4 ГБ свободной RAM и ~5 ГБ диска (образы + bge-m3 2.3 ГБ + индекс).

## Развёртывание с нуля

### 1. Доставить код на сервер

Rsync рабочего дерева (тянет и `data/case`, и `.env` с ключами; тяжёлое/сборочное
исключаем):

```bash
rsync -az \
  --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='node_modules' --exclude='dist' \
  --exclude='.venv' --exclude='storage' --exclude='models_cache' --exclude='chroma' \
  backend frontend domain_packs scripts deploy data \
  requirements.txt requirements-ml.txt .env .dockerignore README.md \
  mac@81.26.178.170:/home/mac/nornickel/
```

### 2. Конфиг

`.env` в корне `/home/mac/nornickel` (см. `.env.example`). Прод-эмбеддер:

```bash
sed -i 's|^EMBED_MODEL=.*|EMBED_MODEL=BAAI/bge-m3|' /home/mac/nornickel/.env
```

`LLM_*` — ключи из локального `.env` (любой OpenAI-совместимый эндпоинт).
Без валидного ключа генерация/чат/синтез ответа в БЗ уходят в фолбэк
(мок-гипотезы с реальными цитатами; в БЗ — только фрагменты).

### 3. Сборка и запуск

```bash
cd /home/mac/nornickel
docker compose -f deploy/docker-compose.yml build      # torch-CPU + ML-deps + vite
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml ps
curl -s http://127.0.0.1:8012/api/health                # {"status":"ok",...}
```

### 4. Домен и TLS (системный nginx)

```bash
# server-block: proxy_pass → 127.0.0.1:8012
sudo cp deploy/nginx-site.conf /etc/nginx/sites-available/nornickel
sudo ln -sfn /etc/nginx/sites-available/nornickel /etc/nginx/sites-enabled/nornickel
sudo nginx -t && sudo systemctl reload nginx            # ТЕСТ → мягкий reload

# TLS (отдельный сертификат только для поддомена, чужие блоки не трогает)
sudo certbot --nginx -d nornickel.indata.group -n --agree-tos --redirect
```

> ⚠️ Всегда `sudo nginx -t` **до** reload. Если тест падает — убрать симлинк и не
> перезагружать nginx, чтобы не уронить остальные сайты.

### 5. Сид данных

Индексирует книги в БЗ (bge-m3 качается при первом запуске ~2.3 ГБ, затем
кодирование ~700 чанков на CPU — небыстро), создаёт демо-проект «НОФ ·
вкрапленные руды · Q2 2026» с диагнозами, гипотезами и дорожной картой:

```bash
docker compose -f deploy/docker-compose.yml exec -T backend \
  sh -c 'python -u scripts/demo_seed.py 2>&1 | tee /app/storage/seed.log'
```

Скан Лодейщикова помечается `scan_no_text` (не OCR-ится). Каждый прогон создаёт
новый проект — лишние дубли можно удалить кнопкой в UI (страница «Проекты»).

### 6. Проверка

```bash
curl -s https://nornickel.indata.group/api/health
curl -s https://nornickel.indata.group/api/kb/documents | jq length     # проиндексированные книги
curl -s https://nornickel.indata.group/api/projects | jq '.[].name'
```

## Эксплуатация

```bash
cd /home/mac/nornickel
docker compose -f deploy/docker-compose.yml logs -f backend      # логи
docker compose -f deploy/docker-compose.yml restart backend      # рестарт
docker compose -f deploy/docker-compose.yml down                 # остановить (тома сохраняются)
```

**Обновление кода** (после rsync новой версии):

```bash
docker compose -f deploy/docker-compose.yml up -d --build         # пересобрать изменившееся
```
Тома `nornickel_storage`/`nornickel_models` переживают пересборку — индекс KB,
проекты и скачанная bge-m3 не теряются.

**Бэкап данных** (sqlite + индекс KB):

```bash
docker run --rm -v nornickel_storage:/s -v "$PWD":/b alpine \
  tar czf /b/nornickel_storage_$(date +%F).tgz -C /s .
```

## Заметки

- **CPU-only**: сервер без GPU, torch ставится CPU-колесом; bge-m3 работает, но
  индексация и запросы к БЗ медленнее, чем на GPU.
- **Смена эмбеддера**: при изменении `EMBED_MODEL` индекс автоматически
  переиндексируется под новую модель (правило 8а) — первый запрос к БЗ будет долгим.
- **Порт 8012** выбран как свободный (8000 на сервере уже занят другим сервисом);
  публикуется только на `127.0.0.1`, наружу — исключительно через системный nginx.
