# -*- coding: utf-8 -*-
"""OCR скана через Yandex Vision (recognizeText, model=page).

Использование: python scripts/ocr_scan_book.py <путь к pdf>
Результат: data/kb/ocr/<stem>.pages.jsonl — по строке {"page": N, "text": "..."}.
Возобновляемый: уже распознанные страницы пропускаются.
Далее книга подхватывается kb/chunking.py (загрузчик *.pages.jsonl) и попадает
в индекс обычным scripts/index_kb_yandex.py --resume.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

import fitz
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "kb" / "ocr"
URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"
DPI = 200
PARALLEL = 2        # рендер идёт параллельно OCR-ожиданию
RETRIES = 8
TIMEOUT = 60.0

env = dotenv_values(ROOT / ".env", encoding="utf-8-sig")
KEY = env.get("LLM_API_KEY") or ""
FOLDER = (re.search(r"gpt://([^/]+)/", env.get("LLM_MODEL_STRONG") or "") or [None, ""])[1]

_rate_lock = Lock()
_next_slot = 0.0
MAX_RPS = 0.9  # дефолтная квота Vision OCR ~1 rps на каталог — держимся ниже


def _throttle():
    global _next_slot
    with _rate_lock:
        now = time.monotonic()
        wait = _next_slot - now
        _next_slot = max(now, _next_slot) + 1.0 / MAX_RPS
    if wait > 0:
        time.sleep(wait)


def ocr_png(png: bytes) -> str:
    body = {"mimeType": "image/png", "languageCodes": ["ru"], "model": "page",
            "content": base64.b64encode(png).decode()}
    last = None
    for attempt in range(RETRIES):
        _throttle()
        try:
            r = httpx.post(URL, json=body, timeout=TIMEOUT,
                           headers={"Authorization": f"Api-Key {KEY}", "x-folder-id": FOLDER})
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r.json()["result"]["textAnnotation"]["fullText"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            last = e
            time.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"Vision OCR не ответил после {RETRIES} попыток: {last}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    pdf = Path(sys.argv[1])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{pdf.stem}.pages.jsonl"

    done: set[int] = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["page"])

    doc = fitz.open(pdf)
    todo = [i for i in range(doc.page_count) if (i + 1) not in done]
    print(f"{pdf.name}: {doc.page_count} стр., уже распознано {len(done)}, осталось {len(todo)}")

    write_lock = Lock()
    t0 = time.time()
    counter = [0]

    def work(i: int):
        pix = doc[i].get_pixmap(dpi=DPI)
        text = ocr_png(pix.tobytes("png"))
        with write_lock:
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page": i + 1, "text": text}, ensure_ascii=False) + "\n")
            counter[0] += 1
            if counter[0] % 25 == 0:
                rate = counter[0] / (time.time() - t0)
                print(f"  {counter[0]}/{len(todo)} ({rate:.1f} стр/с, "
                      f"осталось ~{(len(todo) - counter[0]) / max(rate, 0.1):.0f}с)")

    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        list(pool.map(work, todo))

    total_chars = sum(len(json.loads(l)["text"])
                      for l in out.read_text(encoding="utf-8").splitlines() if l.strip())
    print(f"готово: {out} ({total_chars:,} символов за {time.time()-t0:.0f}с)".replace(",", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
