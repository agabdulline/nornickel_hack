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
    factory: str | None = None   # оверрайд селектором; иначе авто по xlsx


@router.post("/projects")
def create_project(body: ProjectIn, store: Store = Depends(get_store)) -> Project:
    return store.create_project(body.plant, body.goal, body.constraints,
                                body.weights, factory=body.factory)


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
    project = _project_or_404(pid, store)
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
    if not project.factory:  # авто-определение фабрики, если нет оверрайда
        from .flowsheet import detect_factory
        detected = detect_factory(name, res.plant)
        if detected:
            project.factory = detected
            store.update_project(project)
    return {"source": name, "plant": res.plant, "factory": project.factory,
            "reports": [r.model_dump() for r in res.reports],
            "recover_stats": stats, "meta": res.meta}


def _project_flowsheet(pid: str, store: Store) -> tuple[str | None, dict | None]:
    from .flowsheet import detect_factory, get_flowsheet
    project = store.get_project(pid)
    factory = project.factory if project else None
    if not factory:
        got = store.get_reports(pid)
        if got:
            _reports, meta = got
            factory = detect_factory(meta.get("source", ""), _reports[0].plant)
    return factory, get_flowsheet(factory)


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
    factory, flowsheet = _project_flowsheet(pid, store)
    diag = run_diagnostics(report, flowsheet=flowsheet)
    return {"tail_type": report.tail_type, "factory": factory, **diag.model_dump(),
            "report_issues": [i.model_dump() for i in report.issues]}


@router.get("/projects/{pid}/flowsheet")
def get_project_flowsheet(pid: str, store: Store = Depends(get_store)) -> dict:
    """Оцифрованная схема фабрики проекта — для графа переделов на экране диагностики."""
    from .flowsheet import RULE_NODE_TYPES, factories_available
    _project_or_404(pid, store)
    factory, flowsheet = _project_flowsheet(pid, store)
    if not flowsheet:
        return {"factory": factory, "available": factories_available(), "flowsheet": None}
    return {"factory": factory, "available": factories_available(),
            "flowsheet": flowsheet, "rule_node_types": RULE_NODE_TYPES}


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
    from .flowsheet import summarize_for_prompt, zero_reagent_hints
    factory, _fs = _project_flowsheet(pid, store)
    hyps = generate_hypotheses(
        report, diag, kb_index=kb, llm=llm_client,
        constraints=project.constraints, stoplist=project.stoplist,
        history_titles=history, excluded_areas=body.excluded_areas,
        flowsheet_summary=summarize_for_prompt(factory),
        reagent_hints=zero_reagent_hints(factory, kb_index=kb),
        n_samples=2)  # best-of-2: параллельные сэмплы + смысловой дедуп
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


from .parser.docx import expert_titles_for_plant  # noqa: E402 — используется в generate()


# ---------- чат-интерпретатор (8.1) ----------
class ChatIn(BaseModel):
    message: str
    history: list[dict] = Field(default_factory=list)
    tail_type: str | None = None


@router.post("/projects/{pid}/chat")
def project_chat(pid: str, body: ChatIn, store: Store = Depends(get_store),
                 kb: KBIndex = Depends(get_kb)) -> dict:
    from . import chat as chat_mod
    project = _project_or_404(pid, store)
    got = store.get_reports(pid)
    if not got:
        raise HTTPException(404, "сначала загрузите отчёт")
    reports, _meta = got
    report = _pick_report(reports, body.tail_type)
    diag = run_diagnostics(report)
    hyps = store.get_hypotheses(pid)
    ans = chat_mod.answer(body.message, body.history, report, diag, hyps,
                          project, kb_index=kb, llm=llm_client)
    return ans.model_dump()


# ---------- дорожная карта (8.2) ----------
@router.post("/projects/{pid}/roadmap/build")
def roadmap_build(pid: str, store: Store = Depends(get_store)) -> list[dict]:
    from .hypotheses.roadmap import build_roadmap
    _project_or_404(pid, store)
    accepted = store.get_hypotheses(pid, statuses=["accepted", "testing"])
    if not accepted:
        raise HTTPException(422, "нет принятых гипотез — примите хотя бы одну")
    items = build_roadmap(accepted)
    payload = [it.model_dump() for it in items]
    store.save_roadmap(pid, payload)
    return payload


@router.get("/projects/{pid}/roadmap")
def roadmap_get(pid: str, store: Store = Depends(get_store)) -> list[dict]:
    _project_or_404(pid, store)
    return store.get_roadmap(pid)


class RoadmapPatch(BaseModel):
    start: str  # ISO-дата


@router.patch("/roadmap/items/{item_id}")
def roadmap_patch(item_id: str, body: RoadmapPatch,
                  store: Store = Depends(get_store)) -> dict:
    from datetime import date as _date
    from .hypotheses.roadmap import move_item
    from .models import RoadmapItem
    pid = item_id.split(":")[0]
    got = store.get_hypothesis(pid)
    if not got:
        raise HTTPException(404, "стадия не найдена")
    _h, project_id = got
    items = [RoadmapItem(**x) for x in store.get_roadmap(project_id)]
    if not items:
        raise HTTPException(404, "дорожная карта не построена")
    try:
        new_start = _date.fromisoformat(body.start)
    except ValueError:
        raise HTTPException(422, "start: ожидается ISO-дата YYYY-MM-DD")
    ok, reason = move_item(items, item_id, new_start)
    if not ok:
        raise HTTPException(409, f"сдвиг невозможен: {reason}")
    store.save_roadmap(project_id, [it.model_dump() for it in items])
    return {"items": [it.model_dump() for it in items]}


# ---------- экспорт ----------
@router.get("/projects/{pid}/export/docx")
def export_docx(pid: str, tail_type: str | None = None,
                store: Store = Depends(get_store)):
    from fastapi.responses import Response
    from .export.report_docx import build_report_docx
    from .models import RoadmapItem
    project = _project_or_404(pid, store)
    got = store.get_reports(pid)
    if not got:
        raise HTTPException(404, "отчёт ещё не загружен")
    reports, _meta = got
    report = _pick_report(reports, tail_type)
    diag = run_diagnostics(report)
    hyps = store.get_hypotheses(pid)
    roadmap = [RoadmapItem(**x) for x in store.get_roadmap(pid)]
    data = build_report_docx(project, report, diag, hyps, roadmap)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="hypotheses_report.docx"'})


@router.get("/projects/{pid}/export/tasks.csv")
def export_tasks(pid: str, store: Store = Depends(get_store)):
    from fastapi.responses import Response
    from .export.tasks import to_tasks_csv
    from .models import RoadmapItem
    _project_or_404(pid, store)
    hyps = store.get_hypotheses(pid)
    roadmap = [RoadmapItem(**x) for x in store.get_roadmap(pid)]
    csv_text = to_tasks_csv(hyps, roadmap or None)
    return Response(content=csv_text.encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="tasks.csv"'})


@router.get("/projects/{pid}/export/json")
def export_json(pid: str, tail_type: str | None = None,
                store: Store = Depends(get_store)) -> dict:
    from .export.tasks import to_project_json
    from .models import RoadmapItem
    project = _project_or_404(pid, store)
    got = store.get_reports(pid)
    reports, _meta = got if got else ([], {})
    report = _pick_report(reports, tail_type) if reports else None
    diag = run_diagnostics(report) if report else None
    hyps = store.get_hypotheses(pid)
    roadmap = [RoadmapItem(**x) for x in store.get_roadmap(pid)]
    return to_project_json(project, report, diag, hyps, roadmap)


# ---------- база знаний ----------
@router.post("/kb/upload")
async def kb_upload(file: UploadFile, kb: KBIndex = Depends(get_kb)) -> dict:
    data = await file.read()
    name = unicodedata.normalize("NFC", file.filename or "doc.pdf")
    if not name.lower().endswith(".pdf"):
        raise HTTPException(422, "поддерживаются только PDF")
    result = ingest_pdf(data, filename=name, index=kb)
    if result["status"] == "scan_no_text":
        from .kb import ocr as kb_ocr
        if kb_ocr.available():
            _start_background_ocr(data, name, result["doc_id"], result["pages"], kb)
            kb.set_doc_meta(result["doc_id"], status="ocr_processing",
                            ocr_done=0, pages=result["pages"])
            return {**result, "status": "ocr_processing",
                    "message": "скан без текстового слоя — распознаём Vision OCR, "
                               "прогресс в списке документов"}
    return result


def _start_background_ocr(data: bytes, name: str, doc_id: str, total: int, kb: KBIndex):
    """Фоновый поток: Vision OCR постранично -> индексация. Прогресс — в meta документа."""
    import threading
    from .kb import ocr as kb_ocr
    from .kb.ingest import ingest_ocr_pages

    def work():
        try:
            def progress(done: int, n: int):
                if done % 5 == 0 or done == n:
                    kb.set_doc_meta(doc_id, status="ocr_processing", ocr_done=done, pages=n)
            pages = kb_ocr.ocr_pdf(data, progress=progress)
            ingest_ocr_pages(doc_id, name, pages, index=kb)
            log.info("OCR завершён: %s", name)
        except Exception as e:  # noqa: BLE001 — статус ошибки должен дойти до UI
            log.warning("OCR %s упал: %s", name, e)
            kb.set_doc_meta(doc_id, status="ocr_failed", error=str(e)[:200])

    threading.Thread(target=work, daemon=True, name=f"ocr-{doc_id}").start()


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
