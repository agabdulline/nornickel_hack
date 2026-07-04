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
from .models import (Equipment, Hypothesis, Line, LineMaterial, Material, Project,
                     ProjectConstraints, TailingsReport)
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
    name: str = ""
    goal: str = ""
    constraints: str = ""
    weights: dict | None = None
    factory: str | None = None   # оверрайд селектором; иначе авто по xlsx
    project_constraints: ProjectConstraints | None = None


@router.post("/projects")
def create_project(body: ProjectIn, store: Store = Depends(get_store)) -> Project:
    return store.create_project(body.plant, body.goal, body.constraints, body.weights,
                                factory=body.factory,
                                project_constraints=body.project_constraints,
                                name=body.name)


# ---------- линии/лаборатории (мастер-данные, раздел «База знаний») ----------
class LineIn(BaseModel):
    name: str
    kind: str = "производственная линия"
    ownership: str = "в штате компании"


class LinePatch(BaseModel):
    name: str | None = None
    kind: str | None = None
    ownership: str | None = None


@router.get("/lines")
def list_lines(store: Store = Depends(get_store)) -> list[Line]:
    return store.list_lines()


@router.post("/lines")
def create_line(body: LineIn, store: Store = Depends(get_store)) -> Line:
    return store.create_line(body.name, body.kind, body.ownership)


@router.patch("/lines/{line_id}")
def update_line(line_id: str, body: LinePatch, store: Store = Depends(get_store)) -> Line:
    line = store.update_line(line_id, body.name, body.kind, body.ownership)
    if not line:
        raise HTTPException(404, "линия не найдена")
    return line


# ---------- справочник материалов (переиспользуется в ограничениях проекта) ----------
class MaterialIn(BaseModel):
    name: str


@router.get("/materials")
def list_materials(store: Store = Depends(get_store)) -> list[Material]:
    return store.list_materials()


@router.post("/materials")
def create_material(body: MaterialIn, store: Store = Depends(get_store)) -> Material:
    return store.find_or_create_material(body.name)


# ---------- сырьё линии ----------
class LineMaterialIn(BaseModel):
    line_id: str
    name: str
    quantity: float = 0.0
    unit: str = "т"
    material_id: str | None = None


class LineMaterialPatch(BaseModel):
    quantity: float | None = None
    unit: str | None = None
    name: str | None = None
    material_id: str | None = None


@router.get("/line-materials")
def list_line_materials(line_id: str, store: Store = Depends(get_store)) -> list[LineMaterial]:
    return store.list_line_materials(line_id)


@router.post("/line-materials")
def add_line_material(body: LineMaterialIn, store: Store = Depends(get_store)) -> LineMaterial:
    return store.add_line_material(body.line_id, body.name, body.quantity, body.unit, body.material_id)


@router.patch("/line-materials/{lm_id}")
def update_line_material(lm_id: str, body: LineMaterialPatch,
                         store: Store = Depends(get_store)) -> LineMaterial:
    lm = store.update_line_material(lm_id, body.quantity, body.unit, body.name, body.material_id)
    if not lm:
        raise HTTPException(404, "запись о сырье не найдена")
    return lm


@router.delete("/line-materials/{lm_id}")
def delete_line_material(lm_id: str, store: Store = Depends(get_store)) -> dict:
    ok = store.delete_line_material(lm_id)
    if not ok:
        raise HTTPException(404, "запись о сырье не найдена")
    return {"ok": True}


# ---------- оборудование линии (раздел «Ограничения») ----------
class EquipmentIn(BaseModel):
    line_id: str
    name: str
    position: str = ""
    category: str = ""
    status: str = "в эксплуатации"


class EquipmentPatch(BaseModel):
    name: str | None = None
    position: str | None = None
    category: str | None = None
    status: str | None = None


@router.get("/equipment")
def list_equipment(line_id: str, store: Store = Depends(get_store)) -> list[Equipment]:
    return store.list_equipment(line_id)


@router.post("/equipment")
def add_equipment(body: EquipmentIn, store: Store = Depends(get_store)) -> Equipment:
    return store.add_equipment(body.line_id, body.name, body.position,
                               body.category, body.status)


@router.patch("/equipment/{eq_id}")
def update_equipment(eq_id: str, body: EquipmentPatch, store: Store = Depends(get_store)) -> Equipment:
    eq = store.update_equipment(eq_id, body.name, body.position, body.category, body.status)
    if not eq:
        raise HTTPException(404, "оборудование не найдено")
    return eq


@router.delete("/equipment/{eq_id}")
def delete_equipment(eq_id: str, store: Store = Depends(get_store)) -> dict:
    ok = store.delete_equipment(eq_id)
    if not ok:
        raise HTTPException(404, "оборудование не найдено")
    return {"ok": True}


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
    accepted = len(store.get_hypotheses(pid, statuses=["accepted", "testing", "confirmed"]))
    roadmap_built = len(store.get_roadmap(pid)) > 0
    return {**p.model_dump(), "has_report": has_report, "hypotheses_count": n_hyps,
            "accepted_count": accepted, "roadmap_built": roadmap_built}


@router.delete("/projects/{pid}")
def delete_project(pid: str, store: Store = Depends(get_store)) -> dict:
    if not store.delete_project(pid):
        raise HTTPException(404, "проект не найден")
    return {"ok": True}


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
    reports, meta = got
    report = _pick_report(reports, tail_type)
    factory, flowsheet = _project_flowsheet(pid, store)
    diag = run_diagnostics(report, flowsheet=flowsheet, meta=meta.get("parse_meta"))
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


@router.get("/flowsheet-image/{factory}/{idx}")
def flowsheet_image(factory: str, idx: int):
    """Исходное изображение оцифрованной схемы (data/case) по индексу
    в source_files флоушита фабрики."""
    import os as _os
    from pathlib import Path
    from fastapi.responses import FileResponse
    from .config import DATA_CASE
    from .flowsheet import get_flowsheet
    fs = get_flowsheet(factory)
    files = (fs or {}).get("source_files") or []
    if not 0 <= idx < len(files):
        raise HTTPException(404, "схема не найдена")
    want = unicodedata.normalize("NFC", files[idx])
    for dirpath, _dirs, fnames in _os.walk(DATA_CASE):
        for f in fnames:
            if unicodedata.normalize("NFC", f) == want:
                return FileResponse(Path(dirpath) / f, media_type="image/png")
    raise HTTPException(404, f"файл схемы «{files[idx]}» не найден в data/case")


# ---------- курс валют ----------
@router.get("/fx")
def fx_rate() -> dict:
    """Курс отображения эффекта в ₽: ЦБ РФ с кэшем, офлайн — дефолт пакета."""
    from .fx import get_fx
    return get_fx()


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
    project_equipment = project.project_constraints.equipment
    hyps = generate_hypotheses(
        report, diag, kb_index=kb, llm=llm_client,
        constraints=project.constraints, stoplist=project.stoplist,
        history_titles=history, excluded_areas=body.excluded_areas,
        flowsheet_summary=summarize_for_prompt(factory),
        reagent_hints=zero_reagent_hints(factory, kb_index=kb),
        project_equipment=[e.model_dump() for e in project_equipment],
        n_samples=2)  # best-of-2: параллельные сэмплы + смысловой дедуп
    verify_citations(hyps, kb)
    prior = expert_titles_for_plant(report.plant) + \
        [h.title for h in store.get_hypotheses(pid, statuses=["accepted"])]
    rank_hypotheses(hyps, weights=project.weights, prior_titles=prior)
    store.save_hypotheses(pid, hyps, replace=True)
    return hyps


class RerankIn(BaseModel):
    weights: dict | None = None


@router.post("/projects/{pid}/hypotheses/rerank")
def rerank(pid: str, body: RerankIn, store: Store = Depends(get_store)) -> list[Hypothesis]:
    """Пере-ранжирование сохранённых гипотез новыми весами — без LLM.
    Слайдеры весов действуют сразу, регенерация не нужна."""
    project = _project_or_404(pid, store)
    hyps = store.get_hypotheses(pid)
    if not hyps:
        return []
    if body.weights:
        project.weights = {**project.weights, **body.weights}
        store.update_project(project)
    got = store.get_reports(pid)
    plant = got[0][0].plant if got and got[0] else project.plant
    # prior — только наработки экспертов: принятые здесь не добавляем, иначе
    # принятая гипотеза сматчится сама с собой и её novelty обнулится
    prior = expert_titles_for_plant(plant)
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
    history: list[dict] = Field(default_factory=list)   # опционально: оверрайд истории
    tail_type: str | None = None
    chat_id: str | None = None    # без него — последний диалог проекта (или новый)
    page: str | None = None       # экран, с которого спрашивают: report|map|hypotheses|export


class ChatCreateIn(BaseModel):
    title: str = "Новый диалог"


_DEFAULT_CHAT_TITLES = ("Новый диалог", "Диалог", "")


def _chat_or_404(pid: str, chat_id: str, store: Store) -> dict:
    chat = store.get_chat(chat_id)
    if not chat or chat["project_id"] != pid:
        raise HTTPException(404, "диалог не найден")
    return chat


@router.get("/projects/{pid}/chats")
def list_chats(pid: str, store: Store = Depends(get_store)) -> list[dict]:
    _project_or_404(pid, store)
    return store.list_chats(pid)


@router.post("/projects/{pid}/chats")
def create_chat(pid: str, body: ChatCreateIn | None = None,
                store: Store = Depends(get_store)) -> dict:
    _project_or_404(pid, store)
    return store.create_chat(pid, (body.title if body else "Новый диалог") or "Новый диалог")


@router.delete("/projects/{pid}/chats/{chat_id}")
def delete_chat(pid: str, chat_id: str, store: Store = Depends(get_store)) -> dict:
    _project_or_404(pid, store)
    _chat_or_404(pid, chat_id, store)
    store.delete_chat(chat_id)
    return {"ok": True}


@router.post("/projects/{pid}/chat")
def project_chat(pid: str, body: ChatIn, store: Store = Depends(get_store),
                 kb: KBIndex = Depends(get_kb)) -> dict:
    from . import chat as chat_mod
    project = _project_or_404(pid, store)
    got = store.get_reports(pid)
    if not got:
        raise HTTPException(404, "сначала загрузите отчёт")
    reports, meta = got
    report = _pick_report(reports, body.tail_type)
    chat = (_chat_or_404(pid, body.chat_id, store) if body.chat_id
            else store.latest_chat(pid) or store.create_chat(pid))
    # диагнозы с привязкой к схеме фабрики — как на экране диагностики
    _factory, flowsheet = _project_flowsheet(pid, store)
    diag = run_diagnostics(report, flowsheet=flowsheet, meta=meta.get("parse_meta"))
    hyps = store.get_hypotheses(pid)
    # история диалога хранится на сервере; клиентская (если прислали) важнее
    history = body.history or [{"role": m["role"], "content": m["content"]}
                               for m in store.get_chat_messages(pid, limit=12,
                                                                chat_id=chat["id"])]
    ans = chat_mod.answer(body.message, history, report, diag, hyps,
                          project, kb_index=kb, llm=llm_client,
                          roadmap=store.get_roadmap(pid), page=body.page)
    store.add_chat_message(pid, "user", body.message, chat_id=chat["id"])
    store.add_chat_message(pid, "assistant", ans.text,
                           refs=[r.model_dump() for r in ans.references],
                           charts=[c.model_dump() for c in ans.charts],
                           chat_id=chat["id"])
    if chat["title"] in _DEFAULT_CHAT_TITLES:   # заголовок из первого вопроса
        store.rename_chat(chat["id"], body.message.strip()[:48] or "Диалог")
    return {**ans.model_dump(), "chat_id": chat["id"]}


@router.get("/projects/{pid}/chat/history")
def chat_history(pid: str, chat_id: str | None = None,
                 store: Store = Depends(get_store)) -> dict:
    """История диалога (по chat_id; без него — последнего диалога проекта)."""
    _project_or_404(pid, store)
    chat = (_chat_or_404(pid, chat_id, store) if chat_id
            else store.latest_chat(pid))
    if not chat:
        return {"chat_id": None, "messages": []}
    return {"chat_id": chat["id"],
            "messages": store.get_chat_messages(pid, chat_id=chat["id"])}


@router.delete("/projects/{pid}/chat/history")
def chat_clear(pid: str, store: Store = Depends(get_store)) -> dict:
    """Полная очистка: все диалоги проекта."""
    _project_or_404(pid, store)
    return {"cleared": store.clear_chat(pid)}


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
    start: str          # ISO-дата
    force: bool = False  # принять ресурсный конфликт и всё равно сдвинуть


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
    ok, kind, reason = move_item(items, item_id, new_start, force=body.force)
    if not ok:
        # detail — объект: фронт по kind решает, предлагать ли «принять конфликт»
        raise HTTPException(409, detail={"kind": kind, "message": reason})
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
    from fastapi.concurrency import run_in_threadpool
    data = await file.read()
    name = unicodedata.normalize("NFC", file.filename or "doc.pdf")
    low = name.lower()
    if low.endswith(".txt"):
        from .kb.ingest import ingest_text
        result = await run_in_threadpool(ingest_text, data, name, kb)
        _save_kb_original(data, name, result["doc_id"])
        return result
    if not low.endswith(".pdf"):
        raise HTTPException(422, "поддерживаются PDF и TXT")
    # чанкование + dense-эмбеддинг — минуты для больших книг: не блокируем event loop
    result = await run_in_threadpool(ingest_pdf, data, name, kb)
    _save_kb_original(data, name, result["doc_id"])
    if result["status"] == "scan_no_text":
        from .kb import ocr as kb_ocr
        if kb_ocr.available():
            # статус ставим ДО старта потока: быстрый OCR не должен быть
            # перезатёрт запоздавшим ocr_processing из этого потока
            kb.set_doc_meta(result["doc_id"], status="ocr_processing",
                            ocr_done=0, pages=result["pages"])
            _start_background_ocr(data, name, result["doc_id"], result["pages"], kb)
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
            if doc_id not in kb.docs:  # документ удалили, пока шёл OCR
                log.info("OCR %s: документ удалён во время распознавания — результат отброшен", name)
                return
            ingest_ocr_pages(doc_id, name, pages, index=kb)
            log.info("OCR завершён: %s", name)
        except Exception as e:  # noqa: BLE001 — статус ошибки должен дойти до UI
            log.warning("OCR %s упал: %s", name, e)
            kb.set_doc_meta(doc_id, status="ocr_failed", error=str(e)[:200])

    threading.Thread(target=work, daemon=True, name=f"ocr-{doc_id}").start()


@router.get("/kb/documents")
def kb_documents(kb: KBIndex = Depends(get_kb)) -> list[dict]:
    return kb.documents()


def _kb_source_file(source: str, doc_id: str):
    """Исходный файл источника: сохранённая загрузка (storage/kb/files) или
    файлы репозитория (data/kb/books|extra) / кейса (data/case) по имени."""
    import os as _os
    from pathlib import Path
    from .config import DATA_CASE, ROOT, STORAGE
    src = unicodedata.normalize("NFC", source)
    ext = Path(src).suffix.lower()
    for p in (STORAGE / "kb" / "files" / f"{doc_id}{ext}",
              ROOT / "data" / "kb" / "books" / src,
              ROOT / "data" / "kb" / "extra" / src):
        if p.exists():
            return p
    for dirpath, _dirs, files in _os.walk(DATA_CASE):
        for f in files:
            if unicodedata.normalize("NFC", f) == src:
                return Path(dirpath) / f
    return None


def _save_kb_original(data: bytes, name: str, doc_id: str):
    """Оригинал загруженного файла — чтобы читалка могла показать исходник."""
    from pathlib import Path
    from .config import STORAGE
    files_dir = STORAGE / "kb" / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    (files_dir / f"{doc_id}{Path(name).suffix.lower()}").write_bytes(data)


@router.get("/kb/documents/{doc_id}/file")
def kb_document_file(doc_id: str, kb: KBIndex = Depends(get_kb)):
    """Исходник источника (PDF/TXT) — для вкладки «Исходник» в читалке."""
    from fastapi.responses import FileResponse
    if doc_id not in kb.docs:
        raise HTTPException(404, "документ не найден")
    p = _kb_source_file(kb.docs[doc_id]["source"], doc_id)
    if not p:
        raise HTTPException(404, "исходный файл недоступен на сервере")
    media = "application/pdf" if p.suffix.lower() == ".pdf" else "text/plain; charset=utf-8"
    return FileResponse(p, media_type=media, filename=p.name,
                        content_disposition_type="inline")


@router.get("/kb/documents/{doc_id}/preview")
def kb_document_preview(doc_id: str, offset: int = 0, limit: int = 6,
                        kb: KBIndex = Depends(get_kb)) -> dict:
    """Постраничное чтение источника: срез чанков документа для превью в UI."""
    if doc_id not in kb.docs:
        raise HTTPException(404, "документ не найден")
    part = [c for c in kb.chunks if c["doc_id"] == doc_id]
    offset = max(0, offset)
    sel = part[offset: offset + max(1, min(limit, 20))]
    meta = kb.docs[doc_id]
    return {"doc_id": doc_id, "source": meta["source"], "pages": meta.get("pages"),
            "status": meta.get("status"), "total_chunks": len(part), "offset": offset,
            "has_file": _kb_source_file(meta["source"], doc_id) is not None,
            "chunks": [{"chunk_id": c["chunk_id"], "page_start": c["page_start"],
                        "page_end": c["page_end"], "text": c["text"]} for c in sel]}


class KbDocPatch(BaseModel):
    enabled: bool | None = None
    topic: str | None = None


@router.patch("/kb/documents/{doc_id}")
def kb_document_patch(doc_id: str, body: KbDocPatch,
                      kb: KBIndex = Depends(get_kb)) -> dict:
    """Вкл/выкл источника (выключенный не участвует в поиске и в НОВЫХ
    цитатах; сохранённые цитаты гипотез остаются доступными) и/или смена темы."""
    fields = {k: v for k, v in (("enabled", body.enabled), ("topic", body.topic))
              if v is not None}
    if not fields:
        raise HTTPException(422, "нечего менять: передайте enabled и/или topic")
    if not kb.set_doc_meta(doc_id, **fields):
        raise HTTPException(404, "документ не найден")
    return {"doc_id": doc_id, **kb.docs[doc_id]}


@router.delete("/kb/documents/{doc_id}")
def kb_document_delete(doc_id: str, kb: KBIndex = Depends(get_kb)) -> dict:
    if not kb.delete_document(doc_id):
        raise HTTPException(404, "документ не найден")
    return {"deleted": doc_id}


@router.get("/kb/chunk/{chunk_id}")
def kb_chunk(chunk_id: str, kb: KBIndex = Depends(get_kb)) -> dict:
    c = kb.get_chunk(chunk_id)
    if not c:
        raise HTTPException(404, "чанк не найден")
    # has_file — вкладка «Исходник»; lang — кнопка «Перевести на русский»
    return {**c, "has_file": _kb_source_file(c["source"], c["doc_id"]) is not None,
            "lang": kb.docs.get(c["doc_id"], {}).get("lang", "ru")}


class KbTranslateIn(BaseModel):
    chunk_ids: list[str] = Field(max_length=12)


@router.post("/kb/translate")
def kb_translate(body: KbTranslateIn, kb: KBIndex = Depends(get_kb)) -> dict:
    """Перевод фрагментов en/zh источника на русский (кэшируется)."""
    from .kb.translate import translate_chunks
    from .llm import LLMUnavailable
    try:
        return {"translations": translate_chunks(body.chunk_ids, kb, llm_client)}
    except LLMUnavailable as e:
        raise HTTPException(503, f"перевод недоступен: {e}")
    except ValueError as e:
        raise HTTPException(502, f"перевод не разобран: {e}")


class AskIn(BaseModel):
    question: str
    k: int = 5


@router.post("/kb/ask")
def kb_ask(body: AskIn, kb: KBIndex = Depends(get_kb)) -> dict:
    return kb_search.ask(body.question, k=body.k, index=kb, llm=llm_client)
