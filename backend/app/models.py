# -*- coding: utf-8 -*-
"""Каноническая модель данных (раздел 6 CLAUDE.md)."""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class MineralForm(str, Enum):
    OPEN_PNT_CP = "Раскрытый Pnt/Cp"
    CLOSED_PNT_CP = "Закрытый Pnt/Cp"
    PYRRHOTITE_IMPURITY = "Примесь в пирротине"
    SILICATE = "Силикатная форма"
    PYRITE = "Пирит"
    MILLERITE = "Миллерит"


# достижимость по элементам: по неизвлекаемым формам гипотезы НЕ генерируются
RECOVERABLE: dict[str, set[MineralForm]] = {
    "Ni": {MineralForm.OPEN_PNT_CP, MineralForm.CLOSED_PNT_CP, MineralForm.MILLERITE},
    "Cu": {MineralForm.OPEN_PNT_CP, MineralForm.CLOSED_PNT_CP},
}

# канонический порядок классов крупности
SIZE_CLASSES = ["+125", "-125+71", "-71+45", "-45+20", "-20+10", "-10"]


class DataIssue(BaseModel):
    severity: Literal["info", "warning", "error"] = "warning"
    message: str
    cell: str | None = None      # адрес: "+125 / Закрытый Pnt/Cp / Ni" или "Итог!C10"
    rule: str | None = None      # R5a/R5b/R5c | parser | recover


class SizeClassRow(BaseModel):
    label: str                                   # каноническая метка из SIZE_CLASSES
    share_pct: float | None = None               # доля класса, %
    element_share_pct: dict[str, float | None] = Field(default_factory=dict)
    element_tonnes: dict[str, float | None] = Field(default_factory=dict)


Provenance = Literal["measured", "recovered_math", "recovered_llm", "manual"]


class LossCell(BaseModel):
    """Универсальная ячейка карты потерь."""
    axes: dict[str, str]                         # {"size_class": "+125", "mineral_form": "Закрытый Pnt/Cp"}
    element: Literal["Ni", "Cu"]
    tonnes: float | None = None
    share_pct: float | None = None               # доля формы в потерях класса, %
    recoverable: bool = False
    process_area: str | None = None
    provenance: Provenance = "measured"
    confidence: float | None = None              # для recovered_llm
    recovery_note: str | None = None             # формула яруса 1 или объяснение LLM

    @property
    def key(self) -> str:
        return f"{self.axes.get('size_class', '?')}/{self.axes.get('mineral_form', '?')}/{self.element}"


class TailingsReport(BaseModel):
    plant: str
    period: str | None = None
    tail_type: str = "отвальные"                 # ТОФ: "породные" | "пирротиновые"
    data_block: str = "Факт"                     # ТОФ: Факт | Расчёт
    feed_tonnes: float | None = None
    tails_tonnes: float | None = None
    grade: dict[str, float] = Field(default_factory=dict)          # {"Ni": 0.1004} в %
    losses_tonnes: dict[str, float] = Field(default_factory=dict)  # {"Ni": 4392.49}
    size_classes: list[SizeClassRow] = Field(default_factory=list)
    cells: list[LossCell] = Field(default_factory=list)
    recoverable_total: dict[str, float] = Field(default_factory=dict)   # т
    recoverable_pct: dict[str, float] = Field(default_factory=dict)     # %
    issues: list[DataIssue] = Field(default_factory=list)
    # контрольные строки «Итого (проверка)» / «Извлекаемый металл» из файла —
    # для валидации R5 (сверяются только measured-значения)
    control_totals: dict = Field(default_factory=dict)

    def cell(self, size_class: str, form: str, element: str) -> LossCell | None:
        for c in self.cells:
            if (c.axes.get("size_class") == size_class
                    and c.axes.get("mineral_form") == form and c.element == element):
                return c
        return None


class Diagnosis(BaseModel):
    rule_id: str                                 # R1..R5
    zone: str                                    # передел
    title: str
    text: str                                    # русское объяснение с числами
    element: Literal["Ni", "Cu"]
    inputs: dict = Field(default_factory=dict)   # входные числа правила (интерпретируемость)
    cell_keys: list[str] = Field(default_factory=list)
    tonnes_recoverable: float = 0.0
    uncertain: bool = False                      # опирается на recovered_llm
    node_refs: list[str] = Field(default_factory=list)  # узлы flowsheet фабрики
    regime_line: str | None = None               # «по регламенту: узел, t=…, %тв=…»


class Citation(BaseModel):
    quote: str                                   # <= 40 слов
    source: str = ""                             # заполняет verify по chunk_id
    page: int | None = None
    chunk_id: str | None = None
    verified: bool = False


class EquipmentRef(BaseModel):
    name: str
    positions: list[str] = Field(default_factory=list)
    present_on_plant: bool = True


class Equipment(BaseModel):
    """Единица оборудования, привязанная к конкретной линии (онтология раздела «Ограничения»)."""
    id: str
    line_id: str
    name: str
    position: str = ""
    category: str = ""
    status: Literal["в эксплуатации", "резерв", "выведено"] = "в эксплуатации"


class Line(BaseModel):
    """Фабрика/линия или лаборатория — мастер-данные, независимые от жизненного цикла проекта.

    kind — только для отображения/фильтра (у обеих категорий есть своё
    оборудование: промышленное или лабораторное). Показывать ли блок
    «Оборудование» решает НЕ kind, а то, привязан ли проект к конкретному
    объекту вообще (см. сентинел "без привязки к объекту" на фронте).
    """
    id: str
    name: str
    kind: Literal["производственная линия", "лаборатория"] = "производственная линия"
    ownership: Literal["в штате компании", "внешний подрядчик/партнёр"] = "в штате компании"


class Material(BaseModel):
    """Общий справочник материалов/сырья.

    Пока отдельный от графа знаний модуля генерации гипотез (там сущностей
    «материал» ещё нет) — в будущем стоит объединить с сущностями графа,
    чтобы «вкрапленная руда» была одной записью, а не двумя независимыми.
    """
    id: str
    name: str


class LineMaterial(BaseModel):
    """Остаток сырья на линии (см. пункт 3 ТЗ по мастер-данным).

    unit — свободная строка, не Literal: стандартный список предлагается на
    фронте (т/кг/г/мг/м³/л/мл/%/ppm/моль/ммоль/г/т), но «своя единица…»
    позволяет ввести произвольную.
    """
    id: str
    line_id: str
    material_id: str
    name: str
    quantity: float = 0.0
    unit: str = "т"


class Effect(BaseModel):
    tonnes_max: float = 0.0
    tonnes_expected: float = 0.0
    money_usd: float = 0.0
    assumptions: str = ""


class Step(BaseModel):
    n: int
    action: str
    resources: str = ""
    duration: str = ""
    success_criterion: str = ""
    fail_criterion: str = ""


class Hypothesis(BaseModel):
    id: str
    title: str
    process_area: str
    element: Literal["Ni", "Cu"] = "Ni"
    hypothesis_type: str = "other"               # ключ в domain_packs/flotation.yaml
    target_cells: list[dict] = Field(default_factory=list)   # {"key": ..., "tonnes": ...}
    mechanism: str = ""
    rationale: list[Citation] = Field(default_factory=list)
    equipment: list[EquipmentRef] = Field(default_factory=list)
    effect: Effect = Field(default_factory=Effect)
    risks: list[str] = Field(default_factory=list)
    feasibility: dict = Field(default_factory=dict)  # {capex: low/med/high, downtime_hours, complexity}
    novelty: dict = Field(default_factory=dict)      # {score, prior_matches: []}
    verification_plan: list[Step] = Field(default_factory=list)
    score: float = 0.0
    status: str = "proposed"   # proposed/accepted/rejected/testing/confirmed/refuted
    diagnosis_rule: str | None = None
    uncertain: bool = False                      # эффект посчитан на восстановленных данных


class RoadmapItem(BaseModel):
    id: str
    hypothesis_id: str
    hypothesis_title: str = ""
    stage: Literal["lab", "pilot", "rollout"]
    start: str                                   # ISO-дата
    end: str
    resource: str | None = None
    gate_criterion: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    shifted_reason: str | None = None            # "ждёт мельницу 5-3"


class ChatReference(BaseModel):
    type: Literal["rule", "cell", "hypothesis", "chunk"]
    id: str


class ChatAnswer(BaseModel):
    text: str
    references: list[ChatReference] = Field(default_factory=list)


class ProjectConstraints(BaseModel):
    """Раздел «Ограничения» формы создания проекта (аддитивно к строке constraints).

    equipment/materials — НЕ снимок: это всегда live-данные линии (см.
    Store.constraints_for_project), правки в них пишутся напрямую в мастер-данные
    линии (write-through), отдельного слепка на момент создания проекта нет.

    Нормативные требования (регуляторная чувствительность) сюда сознательно не
    включены — отложенная фича, к ней вернутся отдельно; недоделанный UI хуже,
    чем его отсутствие.
    """
    equipment: list[Equipment] = Field(default_factory=list)
    materials: list[LineMaterial] = Field(default_factory=list)


class Project(BaseModel):
    id: str
    name: str = ""       # «Название проекта»; если пусто — фронт подставляет "{линия} · QN YYYY"
    plant: str            # ссылка на Line.id (историческое имя поля — раньше было свободным текстом)
    goal: str = ""
    constraints: str = ""
    created_at: str = ""
    weights: dict = Field(default_factory=lambda: {"money": 0.4, "capex": 0.25, "risk": 0.2, "novelty": 0.15})
    stoplist: list[str] = Field(default_factory=list)
    factory: str | None = None   # НОФ|ТОФ|КГМК: оверрайд селектором или авто по xlsx
    project_constraints: ProjectConstraints = Field(default_factory=ProjectConstraints)
