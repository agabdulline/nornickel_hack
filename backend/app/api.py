# -*- coding: utf-8 -*-
"""HTTP API (раздел 9 CLAUDE.md). Чат и дорожная карта добавляются в P6."""
from __future__ import annotations

import logging
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .diagnostics import DiagnosticsResult, run_diagnostics
from .hypotheses.generate import generate_hypotheses
from .hypotheses.rank import rank_hypotheses
from .hypotheses.verify import verify_citations
from .kb import search as kb_search
from .kb.index import KBIndex, default_index
from .kb.ingest import ingest_pdf
from .llm import client as llm_client
from .models import Hypothesis, Project, TailingsReport
from .parser.docx import parse_expert_hypotheses
from .parser.recover import recover
from .parser.xlsx import parse_workbook
from .store import Store, default_store

log = logging.getLogger("api")
router = APIRouter(prefix="/api")


def get_store() -> Store:
    return default_store()


def get_kb() -> KBIndex:
    return default_index()


# ---------- проекты ----------
class ProjectIn(BaseModel):
    plant: str
    goal: str = ""
    constraints: str = ""
    weights: dict | None = None


@router.post("/projects")
def create_project(body: ProjectIn, store: Store = Depends(get_store)) -> Project:
    return store.create_project(body.plant, body.goal, body.constraints, body.weights)


@router.get("/projects")
def list_projects(store: Store = Depends(get_store)) -> list[Project]:
    return store.list_projects()


@router.get("/projects/{pid}")
def get_project(pid: str, store: Store = Depends(get_store)) -> dict:
    p = store.get_project(pid)
    if not p:
        raise HTTPException(404, "проект не найден")
    has_report = store.get_reports(pid) is not None
    n_hyps = len(store.get_hypotheses(pid))
    return {**p.model_dump(), "has_report": has_report, "hypotheses_count": n_hyps}


def _project_or_404(pid: str, store: Store) -> Project:
    p = store.get_project(pid)
    if not p:
        raise HTTPException(404, "проект не найден")
    return p


# ---------- отчёт ----------
@router.post("/projects/{pid}/report")
async def upload_report(pid: str, file: UploadFile,
                        store: Store = Depends(get_store)) -> dict:
    _project_or_404(pid, store)
    data = await file.read()
    name = unicodedata.normalize("NFC", file.filename or "report.xlsx")
    try:
        res = parse_workbook(data, source_name=name)
    except Exception as e:  # noqa: BLE001 — парсер не должен ронять API
        raise HTTPException(422, f"не удалось разобрать файл: {type(e).__name__}: {e}")
    if not res.reports:
        raise HTTPException(422, "в файле не найдено ни одной секции хвостов")
    stats = []
    for r in res.reports:
        stats.append({"tail_type": r.tail_type, **recover(r, llm=llm_client)})
    store.save_reports(pid, name, res.reports, {"issues": [i.model_dump() for i in res.issues],
                                                "parse_meta": res.meta})
    return {"source": name, "plant": res.plant,
            "reports": [r.model_dump() for r in res.reports],
            "recover_stats": stats, "meta": res.meta}


@router.get("/projects/{pid}/report")
def get_report(pid: str, store: Store = Depends(get_store)) -> dict:
    got = store.get_reports(pid)
    if not got:
        raise HTTPException(404, "отчёт ещё не загружен")
    reports, meta = got
    return {"reports": [r.model_dump() for r in reports], "meta": meta}


class CellEdit(BaseModel):
    key: str                      # "+125/Закрытый Pnt/Cp/Ni"
    tonnes: float | None = None
    share_pct: float | None = None


class CellsPatch(BaseModel):
    tail_type: str | None = None
    edits: list[CellEdit]


@router.patch("/projects/{pid}/report/cells")
def patch_cells(pid: str, body: CellsPatch, store: Store = Depends(get_store)) -> dict:
    got = store.get_reports(pid)
    if not got:
        raise HTTPException(404, "отчёт ещё не загружен")
    reports, meta = got
    report = _pick_report(reports, body.tail_type)
    by_key = {c.key: c for c in report.cells}
    applied = 0
    for e in body.edits:
        cell = by_key.get(e.key)
        if not cell:
            raise HTTPException(422, f"ячейка не найдена: {e.key}")
        if e.tonnes is not None:
            cell.tonnes = e.tonnes
        if e.share_pct is not None:
            cell.share_pct = e.share_pct
        cell.provenance = "manual"
        cell.recovery_note = None
        cell.confidence = None
        applied += 1
    store.save_reports(pid, meta.get("source", ""), reports,
                       {k: v for k, v in meta.items() if k != "source"})
    return {"applied": applied, "report": report.model_dump()}


def _pick_report(reports: list[TailingsReport], tail_type: str | None) -> TailingsReport:
    if tail_type:
        for r in reports:
            if r.tail_type == tail_type:
                return r
        raise HTTPException(404, f"нет секции хвостов «{tail_type}»")
    return reports[0]


# ---------- диагностика ----------
@router.get("/projects/{pid}/diagnostics")
def get_diagnostics(pid: str, tail_type: str | None = None,
                    store: Store = Depends(get_store)) -> dict:
    got = store.get_reports(pid)
    if not got:
        raise HTTPException(404, "отчёт ещё не загружен")
    reports, _meta = got
    report = _pick_report(reports, tail_type)
    diag = run_diagnostics(report)
    return {"tail_type": report.tail_type, **diag.model_dump(),
            "report_issues": [i.model_dump() for i in report.issues]}


# ---------- гипотезы ----------
class GenerateIn(BaseModel):
    weights: dict | None = None
    excluded_areas: list[str] = Field(default_factory=list)
    constraints: str | None = None
    tail_type: str | None = None


@router.post("/projects/{pid}/hypotheses/generate")
def generate(pid: str, body: GenerateIn, store: Store = Depends(get_store),
             kb: KBIndex = Depends(get_kb)) -> list[Hypothesis]:
    project = _project_or_404(pid, store)
    got = store.get_reports(pid)
    if not got:
        raise HTTPException(404, "сначала загрузите отчёт")
    reports, _meta = got
    report = _pick_report(reports, body.tail_type)
    diag = run_diagnostics(report)

    if body.weights:
        project.weights = {**project.weights, **body.weights}
    if body.constraints is not None:
        project.constraints = body.constraints
    store.update_project(project)

    history = [h.title for h in store.get_hypotheses(pid)]
    hyps = generate_hypotheses(
        report, diag, kb_index=kb, llm=llm_client,
        constraints=project.constraints, stoplist=project.stoplist,
        history_titles=history, excluded_areas=body.excluded_areas)
    verify_citations(hyps, kb)
    prior = expert_titles_for_plant(report.plant) + \
        [h.title for h in store.get_hypotheses(pid, statuses=["accepted"])]
    rank_hypotheses(hyps, weights=project.weights, prior_titles=prior)
    store.save_hypotheses(pid, hyps, replace=True)
    return hyps


@router.get("/projects/{pid}/hypotheses")
def list_hypotheses(pid: str, store: Store = Depends(get_store)) -> list[Hypothesis]:
    _project_or_404(pid, store)
    return store.get_hypotheses(pid)


class FeedbackIn(BaseModel):
    action: str                    # accept | reject
    reason: str = ""


@router.post("/hypotheses/{hid}/feedback")
def feedback(hid: str, body: FeedbackIn, store: Store = Depends(get_store)) -> dict:
    got = store.get_hypothesis(hid)
    if not got:
        raise HTTPException(404, "гипотеза не найдена")
    h, pid = got
    if body.action not in ("accept", "reject"):
        raise HTTPException(422, "action: accept | reject")
    h.status = "accepted" if body.action == "accept" else "rejected"
    store.update_hypothesis(h)
    store.add_feedback(hid, pid, body.action, body.reason)
    project = store.get_project(pid)
    if body.action == "reject" and body.reason.strip():
        # направление уходит в стоп-лист проекта — регенерация его исключит
        project.stoplist.append(body.reason.strip())
        store.update_project(project)
    return {"id": hid, "status": h.status, "stoplist": project.stoplist}


def expert_titles_for_plant(plant: str) -> list[str]:
    """Эталонные гипотезы экспертов для novelty/бейджа (если данные кейса рядом)."""
    from .config import DATA_CASE
    import os, re
    if not DATA_CASE.exists():
        return []
    low = plant.lower()
    pattern = ("кгмк" if "кгмк" in low else
               "ноф вкр" if "вкрапл" in low else
               "ноф мед" if "мед" in low else
               "тоф" if "тоф" in low else None)
    if not pattern:
        return []
    for root, _dirs, files in os.walk(DATA_CASE):
        for f in files:
            nf = unicodedata.normalize("NFC", f).lower()
            if nf.startswith("гипотезы") and nf.endswith(".docx"):
                if re.sub(r"\s+", " ", pattern) in nf.replace("_", " "):
                    try:
                        items = parse_expert_hypotheses(os.path.join(root, f))
                        return [x["title"] for x in items]
                    except Exception:  # noqa: BLE001
                        return []
    return []


# ---------- база знаний ----------
@router.post("/kb/upload")
async def kb_upload(file: UploadFile, kb: KBIndex = Depends(get_kb)) -> dict:
    data = await file.read()
    name = unicodedata.normalize("NFC", file.filename or "doc.pdf")
    if not name.lower().endswith(".pdf"):
        raise HTTPException(422, "поддерживаются только PDF")
    return ingest_pdf(data, filename=name, index=kb)


@router.get("/kb/documents")
def kb_documents(kb: KBIndex = Depends(get_kb)) -> list[dict]:
    return kb.documents()


@router.get("/kb/chunk/{chunk_id}")
def kb_chunk(chunk_id: str, kb: KBIndex = Depends(get_kb)) -> dict:
    c = kb.get_chunk(chunk_id)
    if not c:
        raise HTTPException(404, "чанк не найден")
    return c


class AskIn(BaseModel):
    question: str
    k: int = 5


@router.post("/kb/ask")
def kb_ask(body: AskIn, kb: KBIndex = Depends(get_kb)) -> dict:
    return kb_search.ask(body.question, k=body.k, index=kb, llm=llm_client)
