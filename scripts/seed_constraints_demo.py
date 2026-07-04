# -*- coding: utf-8 -*-
"""Демо-данные для раздела «Ограничения» (feature/constraints): две гипотезы для
демо-проекта «НОФ · вкрапленные руды», которые наглядно показывают матчинг с
оборудованием линии — одна с оборудованием, которое есть (ГЦ-660), другая с тем,
которого на линии нет (отсадочная машина). Идемпотентно: пере-запуск не дублирует.

python scripts/seed_constraints_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.hypotheses.rank import rank_hypotheses  # noqa: E402
from backend.app.models import Citation, Effect, EquipmentRef, Hypothesis, Step  # noqa: E402
from backend.app.store import default_store  # noqa: E402

LINE_ID = "НОФ · вкрапленные руды"
MARKER_TITLE_1 = "Замена насадок гидроциклона ГЦ-660 для доизмельчения сростков"
MARKER_TITLE_2 = "Гравитационная доводка тяжёлой фракции на отсадочной машине"


def main() -> int:
    store = default_store()
    projects = [p for p in store.list_projects() if p.plant.startswith(LINE_ID) and
               store.get_reports(p.id) is not None]
    if not projects:
        print("нет проекта с загруженным отчётом для линии", LINE_ID, "— запустите demo_seed.py")
        return 1
    project = projects[0]

    existing_titles = {h.title for h in store.get_hypotheses(project.id)}
    if MARKER_TITLE_1 in existing_titles and MARKER_TITLE_2 in existing_titles:
        print("демо-гипотезы уже есть в проекте", project.id)
        return 0

    equipment_rows = store.list_equipment(LINE_ID)
    by_name: dict[str, list[str]] = {}
    for e in equipment_rows:
        by_name.setdefault(e.name, []).append(e.position)

    def eq_ref(name: str) -> EquipmentRef:
        positions = [p for p in by_name.get(name, []) if p]
        return EquipmentRef(name=name, positions=positions, present_on_plant=bool(positions))

    hyps = [
        Hypothesis(
            id="h-demo-constraints-01",
            title=MARKER_TITLE_1,
            process_area="классификация",
            element="Ni",
            hypothesis_type="classification",
            target_cells=[{"key": "+125/Закрытый Pnt/Cp/Ni", "tonnes": 845.7}],
            mechanism="Уменьшение диаметра песковой насадки гидроциклона ГЦ-660 повышает "
                      "циркулирующую нагрузку и снижает крупность слива, доразкрывая сростки "
                      "пентландита в классе +125, которые сейчас уходят в хвосты закрытыми.",
            rationale=[Citation(quote="песковые насадки гидроциклонов определяют гранулометрию слива",
                                source="geokniga-flotacionnye-metody-obogashcheniya_0.pdf",
                                page=42, verified=False)],
            equipment=[eq_ref("Гидроциклон ГЦ-660")],
            effect=Effect(tonnes_max=845.7, tonnes_expected=126.9, money_usd=2093850,
                          assumptions="capture_rate=0.15 по типу «classification» (domain_pack)"),
            risks=["рост тонкого шлама во флотации"],
            feasibility={"capex": "low", "complexity": "low"},
            verification_plan=[Step(n=1, action="Замена насадок на опытном ГЦ-660 (поз. 5-3)",
                                    resources="2 насадки, наладчик", duration="1 неделя",
                                    success_criterion="снижение d80 слива ≥ 10%",
                                    fail_criterion="рост циркулирующей нагрузки > 300%")],
            diagnosis_rule="R1",
        ),
        Hypothesis(
            id="h-demo-constraints-02",
            title=MARKER_TITLE_2,
            process_area="вспомогательные",
            element="Ni",
            hypothesis_type="gravity",
            target_cells=[{"key": "-125+71/Закрытый Pnt/Cp/Ni", "tonnes": 260.6}],
            mechanism="Отсадка тяжёлой фракции класса -125+71 перед контрольной флотацией "
                      "выделяет сростки с высокой плотностью, которые сейчас теряются из-за "
                      "недостаточного времени раскрытия.",
            rationale=[],
            equipment=[eq_ref("Отсадочная машина")],
            effect=Effect(tonnes_max=260.6, tonnes_expected=39.1, money_usd=644650,
                          assumptions="capture_rate=0.15 по типу «gravity» (domain_pack)"),
            risks=["требует нового узла и CAPEX", "нет опыта эксплуатации на линии"],
            feasibility={"capex": "high", "complexity": "high"},
            verification_plan=[Step(n=1, action="Лабораторная отсадка пробы класса -125+71",
                                    resources="лабораторная отсадочная машина", duration="2 недели",
                                    success_criterion="прирост извлечения Ni ≥ 0.5 п.п.",
                                    fail_criterion="прирост < 0.2 п.п.")],
            diagnosis_rule="R1",
        ),
    ]

    all_hyps = store.get_hypotheses(project.id) + hyps
    rank_hypotheses(all_hyps, weights=project.weights)
    store.save_hypotheses(project.id, hyps, replace=False)
    for h in all_hyps:
        if h.id in ("h-demo-constraints-01", "h-demo-constraints-02"):
            store.update_hypothesis(h)

    print(f"добавлено 2 демо-гипотезы в проект {project.id}:")
    print(" -", MARKER_TITLE_1, "-> оборудование ГЦ-660 есть на линии")
    print(" -", MARKER_TITLE_2, "-> оборудование «отсадочная машина» отсутствует (CAPEX)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
