# -*- coding: utf-8 -*-
"""Ранжирование гипотез (раздел 8 CLAUDE.md).

score = w1·норм(effect.money) + w2·(1−capex_норм) + w3·(1−risk_норм) + w4·novelty
Веса — из запроса (слайдеры UI), дефолт 0.4/0.25/0.2/0.15.

Novelty: близость к эталонным/принятым ранее гипотезам. Основной путь —
эмбеддинги (cos>0.8 → prior_match, novelty=0.2); без модели — fuzzy-фоллбэк
(token_set_ratio>80). Гипотезы без единой verified-цитаты понижаются.
"""
from __future__ import annotations

import logging

from rapidfuzz import fuzz

from ..models import Hypothesis

log = logging.getLogger("hypotheses.rank")

DEFAULT_WEIGHTS = {"money": 0.4, "capex": 0.25, "risk": 0.2, "novelty": 0.15}
_CAPEX_NORM = {"low": 0.0, "med": 0.5, "medium": 0.5, "high": 1.0}
_COMPLEXITY_NORM = {"low": 0.0, "med": 0.5, "medium": 0.5, "high": 1.0}
UNVERIFIED_PENALTY = 0.75  # множитель score без единой verified-цитаты
SIM_THRESHOLD_EMB = 0.8
SIM_THRESHOLD_FUZZ = 80.0


def _risk_norm(h: Hypothesis) -> float:
    n_risks = min(len(h.risks) / 4.0, 1.0)
    compl = _COMPLEXITY_NORM.get(str(h.feasibility.get("complexity", "med")).lower(), 0.5)
    return 0.5 * n_risks + 0.5 * compl


def _capex_norm(h: Hypothesis) -> float:
    return _CAPEX_NORM.get(str(h.feasibility.get("capex", "med")).lower(), 0.5)


def _fuzzy_prior_matches(title: str, priors: list[str]) -> list[str]:
    return [p for p in priors
            if fuzz.token_set_ratio(title.lower(), p.lower()) > SIM_THRESHOLD_FUZZ]


def _embed_prior_matches(titles: list[str], priors: list[str]) -> list[list[str]] | None:
    """Матчи по эмбеддингам для всех заголовков сразу; None, если модель недоступна."""
    if not priors:
        return [[] for _ in titles]
    try:
        from ..kb.embed import encode, get_embedder
        model, name = get_embedder()
        if model is None:
            return None
        emb_t = encode(model, name, titles)
        emb_p = encode(model, name, priors)
        out = []
        for et in emb_t:
            matches = []
            for j, ep in enumerate(emb_p):
                cos = float((et * ep).sum())  # векторы нормированы
                if cos > SIM_THRESHOLD_EMB:
                    matches.append(priors[j])
            out.append(matches)
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("novelty по эмбеддингам недоступна (%s) — fuzzy", type(e).__name__)
        return None


def rank_hypotheses(hyps: list[Hypothesis], weights: dict | None = None,
                    prior_titles: list[str] | None = None,
                    use_embeddings: bool = True) -> list[Hypothesis]:
    """Мутирует score/novelty, возвращает отсортированный список."""
    if not hyps:
        return []
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    priors = prior_titles or []

    moneys = [h.effect.money_usd for h in hyps]
    lo, hi = min(moneys), max(moneys)

    emb_matches = _embed_prior_matches([h.title for h in hyps], priors) if use_embeddings else None

    for i, h in enumerate(hyps):
        money_n = (h.effect.money_usd - lo) / (hi - lo) if hi > lo else 0.5
        matches = emb_matches[i] if emb_matches is not None \
            else _fuzzy_prior_matches(h.title, priors)
        novelty = 0.2 if matches else 1.0
        h.novelty = {"score": novelty, "prior_matches": matches}

        score = (w["money"] * money_n
                 + w["capex"] * (1.0 - _capex_norm(h))
                 + w["risk"] * (1.0 - _risk_norm(h))
                 + w["novelty"] * novelty)
        if h.rationale and not any(c.verified for c in h.rationale):
            score *= UNVERIFIED_PENALTY  # цитаты есть, но ни одна не подтверждена
        h.score = round(score, 4)

    hyps.sort(key=lambda x: -x.score)
    return hyps
