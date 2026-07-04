# Эмбеддинг корпуса на GPU (RTX 5060 Ti)

Текстовый проход «Научного клубка» уже сделан: 1517 документов,
~184 тыс. чанков лежат в `storage/kb/chunks.jsonl`. Осталось докатить
dense-вектора — на CPU это ~4 суток, на 5060 Ti — **~10–30 минут**.

## Шаги на машине с GPU

1. Взять код и данные:
   ```
   git clone https://github.com/GeorgeItsMe/hack_nornikil.git
   cd hack_nornikil
   ```
   Скопировать с ноутбука папку `storage\kb` ЦЕЛИКОМ (chunks.jsonl,
   meta.json, chroma\, files\, translations.json) в то же место клона.
   Перед копированием на ноуте остановить бэкенд и процессы инжеста.

2. Зависимости + CUDA-сборка torch (5060 Ti = Blackwell/sm_120,
   нужен torch >= 2.7 с cu128 — обычный CPU-torch из requirements заменить):
   ```
   pip install -r requirements.txt -r requirements-ml.txt
   pip install --upgrade torch --index-url https://download.pytorch.org/whl/cu128
   python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
   ```
   Должно напечатать `True NVIDIA GeForce RTX 5060 Ti`.

3. `.env` с ключами не нужен; достаточно `EMBED_MODEL`:
   ```
   echo EMBED_MODEL=BAAI/bge-m3 > .env
   ```
   (bge-m3 ~2.3 ГБ скачается при первом запуске.)

4. Докатить вектора (resumable — можно прерывать и перезапускать,
   уже закодированные документы пропускаются; порядок — сначала
   включённые темы):
   ```
   python scripts/ingest_folder.py --dense-only
   ```

5. Вернуть на ноут/сервер обновлённые `storage\kb\chroma` и
   `storage\kb\meta.json` (вектора совместимы — модель та же).
   На сервер: см. deploy/README.md, том nornickel_storage.

## Ожидаемая скорость

| Железо | Скорость | 184К чанков |
|---|---|---|
| CPU ноутбука/сервера | ~0.5 чанк/с | ~4 суток |
| RTX 5060 Ti (fp16, батч 64) | ~100–300 чанк/с | ~10–30 мин |

Ускорение ~200–400×. Узкое место после GPU — запись в chroma (минуты).
