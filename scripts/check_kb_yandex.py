# -*- coding: utf-8 -*-
"""Проверка качества выдачи kb_yandex_v2: 12 контрольных вопросов (6 тем × 2),
top-5 чистым dense-поиском (query-модель). Результат -> eval/yandex_embed_check.md
(оценки релевантности дописываются вручную после просмотра)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chromadb  # noqa: E402

from kb.embedder_base import get_embedder  # noqa: E402

QUESTIONS = [
    ("сростки/доизмельчение", "Как повысить раскрытие сростков пентландита при измельчении?"),
    ("сростки/доизмельчение", "Доизмельчение промпродукта для снижения потерь металла с хвостами"),
    ("шламы/тонкие классы", "Почему тонкие частицы −10 мкм плохо флотируются и теряются с хвостами?"),
    ("шламы/тонкие классы", "Как снизить вредное влияние шламов на флотацию?"),
    ("депрессия пирротина/реагенты", "Как подавить пирротин при флотации медно-никелевой руды?"),
    ("депрессия пирротина/реагенты", "Реагенты-депрессоры для отделения пентландита от пирротина"),
    ("гидроциклоны vs грохочение", "Чем тонкое грохочение лучше гидроциклонов в замкнутом цикле измельчения?"),
    ("гидроциклоны vs грохочение", "Недостатки гидроциклонов при классификации по граничному зерну"),
    ("футеровка", "Как профиль футеровки шаровой мельницы влияет на эффективность измельчения?"),
    ("футеровка", "Как увеличить срок службы футеровки шаровой мельницы?"),
    ("время/кинетика флотации", "Как время флотации влияет на извлечение металла?"),
    ("время/кинетика флотации", "Кинетика флотации крупных и мелких частиц: в чём разница?"),
]


def main():
    embedder = get_embedder("yandex")
    col = chromadb.PersistentClient(path=str(ROOT / "chroma")).get_collection("kb_yandex_v2")
    print(f"коллекция kb_yandex_v2: {col.count()} векторов")

    lines = [
        "# Проверка выдачи kb_yandex_v2 (Yandex text-search-doc/query, dim=256)",
        "",
        f"Корпус: {col.count()} чанков (5 учебников кейса + 13 внешних источников). "
        "Чистый dense-поиск (без BM25), top-5, метрика cosine.",
        "",
    ]
    for theme, q in QUESTIONS:
        emb = embedder.embed_query(q)
        got = col.query(query_embeddings=[emb], n_results=5,
                        include=["metadatas", "documents", "distances"])
        lines += [f"## [{theme}] {q}", ""]
        for meta, doc, dist in zip(got["metadatas"][0], got["documents"][0],
                                   got["distances"][0]):
            page = f", с. {meta['page']}" if meta.get("page", -1) not in (-1, None) else ""
            snippet = " ".join(doc.split())[:220]
            lines.append(f"- **{meta['source_file']}**{page} (dist {dist:.3f}): {snippet}…")
        lines += ["", "**Оценка:** _(заполняется при ревью)_", ""]
        print(f"[{theme}] {q}")
        for meta, dist in zip(got["metadatas"][0], got["distances"][0]):
            print(f"    {dist:.3f} {meta['source_file']}")

    out = ROOT / "eval" / "yandex_embed_check.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
