# -*- coding: utf-8 -*-
"""SQLite-хранилище: проекты, отчёты, гипотезы, фидбэк, дорожные карты.

Схема простая (JSON-блобы для вложенных структур) — важна скорость итераций,
а не нормализация. Все операции синхронные, БД локальная.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import STORAGE
from .models import (Equipment, Hypothesis, Line, LineMaterial, Material, Project,
                     ProjectConstraints, StopEntry, TailingsReport)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, plant TEXT, goal TEXT, constraints TEXT,
  created_at TEXT, weights_json TEXT, stoplist_json TEXT
);
CREATE TABLE IF NOT EXISTS reports (
  project_id TEXT PRIMARY KEY, source TEXT, payload_json TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS hypotheses (
  id TEXT PRIMARY KEY, project_id TEXT, payload_json TEXT,
  score REAL, status TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, hypothesis_id TEXT, project_id TEXT,
  action TEXT, reason TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS roadmaps (
  project_id TEXT PRIMARY KEY, payload_json TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS equipment (
  id TEXT PRIMARY KEY, line_id TEXT, name TEXT, position TEXT,
  category TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS lines (
  id TEXT PRIMARY KEY, name TEXT, type TEXT, kind TEXT, ownership TEXT
);
CREATE TABLE IF NOT EXISTS materials (
  id TEXT PRIMARY KEY, name TEXT
);
CREATE TABLE IF NOT EXISTS line_materials (
  id TEXT PRIMARY KEY, line_id TEXT, material_id TEXT, name TEXT,
  quantity REAL, unit TEXT
);
CREATE TABLE IF NOT EXISTS line_stoplist (
  id TEXT PRIMARY KEY, line_id TEXT, direction TEXT, reason TEXT,
  project_id TEXT, hypothesis_id TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS chats (
  id TEXT PRIMARY KEY, project_id TEXT, title TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, chat_id TEXT, role TEXT,
  content TEXT, refs_json TEXT, charts_json TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_chat_project ON chat_messages(project_id);
CREATE TABLE IF NOT EXISTS factory_images (
  id TEXT PRIMARY KEY, factory TEXT, filename TEXT, caption TEXT,
  path TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS line_flowsheets (
  key TEXT PRIMARY KEY, payload_json TEXT, source_image TEXT,
  status TEXT, error TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS project_files (
  id TEXT PRIMARY KEY, project_id TEXT, filename TEXT, kind TEXT,
  text TEXT, status TEXT, path TEXT, created_at TEXT
);
"""

# сид онтологии оборудования (раздел «Ограничения») для демо-линии кейса;
# намеренно без отсадочных машин — сценарий «оборудования нет» демонстрирует
# отдельная линия-партнёр без единиц оборудования (см. _SEED_LINES)
_INSTITUTE = "Институт «Норильскпроект» (филиал Гипроникеля, Норильск)"
_PARTNER = "Институт-партнёр (внешний)"

_SEED_EQUIPMENT: dict[str, list[dict]] = {
    "НОФ · вкрапленные руды": [
        {"name": "Гидроциклон ГЦ-660", "position": "5-3", "category": "гидроциклон"},
        {"name": "Гидроциклон ГЦ-660", "position": "5-5", "category": "гидроциклон"},
        {"name": "Мельница МШЦ 4,5×6,0", "position": "5-3", "category": "мельница"},
        {"name": "Мельница МШРГУ 4,5×6,0", "position": "5-1", "category": "мельница"},
        {"name": "Флотомашина ФПМ-16-4К", "position": "3-2", "category": "флотомашина"},
        {"name": "Сгуститель П-30", "position": "7-1", "category": "сгуститель"},
    ],
    # правдоподобный, но иллюстративный набор лабораторного оборудования по
    # категориям из ТЗ — НЕ подтверждённый факт о реальном парке приборов института
    _INSTITUTE: [
        {"name": "Роторный делитель проб", "position": "", "category": "пробоподготовка"},
        {"name": "Вибрационный ситовой анализатор", "position": "", "category": "пробоподготовка"},
        {"name": "Тестер индекса Бонда (измельчаемость)", "position": "", "category": "дробление/измельчение"},
        {"name": "Лабораторная флотомашина МФЛ-012М", "position": "", "category": "флотация"},
        {"name": "Рентгенофлуоресцентный анализатор (РФА)", "position": "", "category": "элементный анализ"},
    ],
    # у партнёра намеренно нет оборудования — демонстрирует состояние
    # «объект есть, но оборудование ещё не заведено»
}

# сид линий/лабораторий: id совпадает с прежним свободным именем линии —
# так первая итерация (equipment.line_id == "НОФ · вкрапленные руды") не ломается
_SEED_LINES: list[dict] = [
    {"id": "НОФ · вкрапленные руды", "name": "НОФ · вкрапленные руды",
     "kind": "производственная линия", "ownership": "в штате компании"},
    {"id": _INSTITUTE, "name": _INSTITUTE,
     "kind": "лаборатория", "ownership": "в штате компании"},
    {"id": _PARTNER, "name": _PARTNER,
     "kind": "лаборатория", "ownership": "внешний подрядчик/партнёр"},
]

_SEED_MATERIALS: dict[str, list[dict]] = {
    "НОФ · вкрапленные руды": [
        {"name": "Вкрапленная руда", "quantity": 1200.0, "unit": "т"},
    ],
}

# справочник материалов — не привязан к конкретной линии/лаборатории, доступен
# как вариант для любого объекта; реальные типы руд компании помимо вкрапленной
_SEED_MATERIALS_CATALOG = ["Вкрапленная руда", "Медистая руда", "Богатая руда"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path) if path else str(STORAGE / "app.db")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # один Connection на несколько потоков FastAPI-threadpool небезопасен
        # без внешней блокировки (check_same_thread=False снимает только assert,
        # не гонки) — отсюда рандомные "битые" строки под конкурентными запросами
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        try:  # миграция: колонка factory появилась после первых БД
            self._conn.execute("ALTER TABLE projects ADD COLUMN factory TEXT")
        except sqlite3.OperationalError:
            pass
        try:  # миграция: исследуемый материал (не только отвальные хвосты)
            self._conn.execute("ALTER TABLE projects ADD COLUMN material TEXT")
        except sqlite3.OperationalError:
            pass
        self._migrate_project_constraints()
        self._migrate_project_name()
        self._migrate_lines_kind_ownership()
        self._migrate_chats()
        self._seed_equipment()
        self._seed_lines()
        self._migrate_project_lines()
        self._seed_materials()
        self._seed_materials_catalog()
        self._seed_factory_images()
        self._conn.commit()

    def _migrate_chats(self):
        """Аддитивная миграция: сообщения до появления диалогов (chat_id/charts_json)
        собираются в один диалог «Диалог» на проект."""
        for col in ("chat_id TEXT", "charts_json TEXT"):
            try:
                self._conn.execute(f"ALTER TABLE chat_messages ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        rows = self._conn.execute(
            "SELECT DISTINCT project_id FROM chat_messages WHERE chat_id IS NULL").fetchall()
        for r in rows:
            cid = uuid.uuid4().hex[:10]
            self._conn.execute("INSERT INTO chats VALUES (?,?,?,?,?)",
                               (cid, r["project_id"], "Диалог", _now(), _now()))
            self._conn.execute(
                "UPDATE chat_messages SET chat_id=? WHERE project_id=? AND chat_id IS NULL",
                (cid, r["project_id"]))

    def _migrate_project_constraints(self):
        """Аддитивная миграция: старые БД созданы до появления раздела «Ограничения»."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(projects)")}
        if "project_constraints_json" not in cols:
            self._conn.execute("ALTER TABLE projects ADD COLUMN project_constraints_json TEXT")

    def _migrate_project_name(self):
        """Аддитивная миграция: старые БД созданы до появления поля «Название проекта»."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(projects)")}
        if "name" not in cols:
            self._conn.execute("ALTER TABLE projects ADD COLUMN name TEXT")

    def _seed_equipment(self):
        for line_id, items in _SEED_EQUIPMENT.items():
            existing = self._conn.execute(
                "SELECT COUNT(*) c FROM equipment WHERE line_id=?", (line_id,)).fetchone()["c"]
            if existing:
                continue
            for item in items:
                self._conn.execute(
                    "INSERT INTO equipment VALUES (?,?,?,?,?,?)",
                    (uuid.uuid4().hex[:10], line_id, item["name"], item["position"],
                     item["category"], "в эксплуатации"))

    def _migrate_lines_kind_ownership(self):
        """Аддитивная миграция: линии первой итерации хранили только type=factory|lab."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(lines)")}
        if "kind" not in cols:
            self._conn.execute("ALTER TABLE lines ADD COLUMN kind TEXT")
        if "ownership" not in cols:
            self._conn.execute("ALTER TABLE lines ADD COLUMN ownership TEXT")
        self._conn.execute(
            "UPDATE lines SET kind = CASE type WHEN 'factory' THEN 'производственная линия' "
            "WHEN 'lab' THEN 'лаборатория' ELSE 'производственная линия' END WHERE kind IS NULL")
        self._conn.execute("UPDATE lines SET ownership = 'в штате компании' WHERE ownership IS NULL")

    def _migrate_project_lines(self):
        """Реконсиляция привязки проект→линия (line-scoped данные).

        У части старых/сид-проектов plant был свободным текстом, не совпадающим
        с id линии (напр. «НОФ · вкрапленные руды · Q2 2026» вместо линии
        «НОФ · вкрапленные руды»), из-за чего оборудование и стоп-лист линии не
        показывались в «Базе знаний». Здесь привязываем к реальной линии: если
        plant без хвоста-квартала ' · QN YYYY' совпадает с существующей линией —
        репойнтим туда, а хвост уводим в name; иначе заводим линию с этим plant.
        Переносим и записи стоп-листа. Идемпотентно (после фикса — no-op).
        Требует уже засиженных линий, поэтому вызывается ПОСЛЕ _seed_lines."""
        import re
        quarter = re.compile(r"\s*·\s*Q[1-4]\s+\d{4}\s*$")
        line_ids = {r["id"] for r in self._conn.execute("SELECT id FROM lines")}
        for row in self._conn.execute("SELECT id, plant, name FROM projects").fetchall():
            pid, plant = row["id"], row["plant"]
            name = row["name"] if "name" in row.keys() else None
            if not plant or plant in line_ids:
                continue                       # уже привязан к реальной линии
            base = quarter.sub("", plant).strip()
            if base and base != plant and base in line_ids:
                # репойнт на существующую линию, квартал сохраняем в названии
                self._conn.execute("UPDATE projects SET plant=?, name=? WHERE id=?",
                                   (base, name or plant, pid))
                self._conn.execute("UPDATE line_stoplist SET line_id=? WHERE line_id=?",
                                   (base, plant))
            else:
                # объект не заведён как линия — регистрируем его (id = plant)
                self._conn.execute(
                    "INSERT INTO lines (id, name, type, kind, ownership) VALUES (?,?,?,?,?)",
                    (plant, plant, "производственная линия",
                     "производственная линия", "в штате компании"))
                line_ids.add(plant)

    def _seed_lines(self):
        # посрочная проверка по id (как в _seed_equipment) — иначе на уже
        # существующей БД первой итерации новые сид-линии (институт, партнёр)
        # никогда бы не появились, раз таблица lines уже не пуста
        for line in _SEED_LINES:
            existing = self._conn.execute(
                "SELECT COUNT(*) c FROM lines WHERE id=?", (line["id"],)).fetchone()["c"]
            if existing:
                continue
            self._conn.execute("INSERT INTO lines (id, name, type, kind, ownership) VALUES (?,?,?,?,?)",
                               (line["id"], line["name"], line["kind"], line["kind"], line["ownership"]))

    def _seed_materials(self):
        existing = self._conn.execute("SELECT COUNT(*) c FROM line_materials").fetchone()["c"]
        if existing:
            return
        for line_id, items in _SEED_MATERIALS.items():
            for item in items:
                mat = self._find_or_create_material(item["name"])
                self._conn.execute(
                    "INSERT INTO line_materials VALUES (?,?,?,?,?,?)",
                    (uuid.uuid4().hex[:10], line_id, mat.id, mat.name,
                     item["quantity"], item["unit"]))

    def _seed_materials_catalog(self):
        """Справочник материалов, доступный для ЛЮБОГО объекта — не привязан к
        конкретной линии/лаборатории, поэтому идёт отдельно от _seed_materials
        (которая сидирует остатки СЫРЬЯ на конкретной линии и всё-или-ничего
        по line_materials). find_or_create_material идемпотентен по имени —
        безопасно вызывать при каждом старте."""
        for name in _SEED_MATERIALS_CATALOG:
            self._find_or_create_material(name)

    # ---------- проекты ----------
    def create_project(self, plant: str, goal: str = "", constraints: str = "",
                       weights: dict | None = None, factory: str | None = None,
                       project_constraints: ProjectConstraints | None = None,
                       name: str = "", material: str = "отвальные хвосты") -> Project:
        p = Project(id=uuid.uuid4().hex[:10], plant=plant, goal=goal, name=name,
                    constraints=constraints, created_at=_now(), factory=factory,
                    material=material or "отвальные хвосты")
        if weights:
            p.weights = weights
        if project_constraints:
            p.project_constraints = project_constraints
        with self._lock:
            self._conn.execute(
                "INSERT INTO projects (id, plant, goal, constraints, created_at, "
                "weights_json, stoplist_json, project_constraints_json, name, factory, "
                "material) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (p.id, p.plant, p.goal, p.constraints, p.created_at,
                 json.dumps(p.weights), json.dumps(p.stoplist, ensure_ascii=False),
                 p.project_constraints.model_dump_json(), p.name, p.factory, p.material))
            self._conn.commit()
        return self.get_project(p.id)

    def get_project(self, pid: str) -> Project | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
            if not row:
                return None
            raw_pc = row["project_constraints_json"] if "project_constraints_json" in row.keys() else None
            pc = ProjectConstraints(**json.loads(raw_pc)) if raw_pc else ProjectConstraints()
            p = Project(id=row["id"], plant=row["plant"], goal=row["goal"],
                       name=(row["name"] if "name" in row.keys() else None) or "",
                       constraints=row["constraints"], created_at=row["created_at"],
                       weights=json.loads(row["weights_json"] or "{}"),
                       stoplist=json.loads(row["stoplist_json"] or "[]"),
                       factory=row["factory"] if "factory" in row.keys() else None,
                       material=(row["material"] if "material" in row.keys() else None)
                       or "отвальные хвосты",
                       project_constraints=pc)
        return self.constraints_for_project(p)

    def constraints_for_project(self, p: Project) -> Project:
        """Оверлей live-данных линии (оборудование/сырьё) поверх project_constraints.

        Это и есть write-through из п.7 ТЗ: equipment/materials никогда не
        читаются как снимок из project_constraints_json — только из мастер-данных
        линии по p.plant (=line_id), так что правки в «Базе знаний» сразу видны
        в проекте и наоборот. И линия, и лаборатория могут иметь оборудование
        (просто разных категорий) — kind тут ни на что не влияет. Пусто
        получится ровно тогда, когда p.plant не ссылается на реальную линию
        (сентинел «без привязки к объекту» с фронта) — list_equipment/
        list_line_materials на несуществующий line_id просто вернут [].
        """
        p.project_constraints.equipment = self.list_equipment(p.plant)
        p.project_constraints.materials = self.list_line_materials(p.plant)
        return p

    def list_projects(self) -> list[Project]:
        with self._lock:
            rows = self._conn.execute("SELECT id FROM projects ORDER BY created_at DESC").fetchall()
            return [self.get_project(r["id"]) for r in rows]

    def update_project(self, p: Project):
        with self._lock:
            self._conn.execute(
                "UPDATE projects SET weights_json=?, stoplist_json=?, goal=?, constraints=?, "
                "project_constraints_json=?, name=?, factory=? WHERE id=?",
                (json.dumps(p.weights), json.dumps(p.stoplist, ensure_ascii=False),
                 p.goal, p.constraints, p.project_constraints.model_dump_json(),
                 p.name, p.factory, p.id))
            self._conn.commit()

    def delete_project(self, pid: str) -> bool:
        """Удаляет проект и все его данные (отчёт, гипотезы, фидбэк, дорожную
        карту). Мастер-данные линии (оборудование/сырьё) — общие, их НЕ трогаем.
        Возвращает False, если проекта не было."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM projects WHERE id=?", (pid,))
            for f in self.list_project_files(pid):
                if f.get("path"):
                    try:
                        Path(f["path"]).unlink(missing_ok=True)
                    except OSError:
                        pass
            for table in ("reports", "hypotheses", "feedback", "roadmaps",
                          "chat_messages", "chats", "project_files"):
                self._conn.execute(f"DELETE FROM {table} WHERE project_id=?", (pid,))
            self._conn.commit()
            return cur.rowcount > 0

    # ---------- линии/лаборатории (мастер-данные) ----------
    def list_lines(self) -> list[Line]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM lines ORDER BY name").fetchall()
            return [Line(id=r["id"], name=r["name"], kind=r["kind"] or "производственная линия",
                        ownership=r["ownership"] or "в штате компании") for r in rows]

    def get_line(self, line_id: str) -> Line | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone()
            return (Line(id=row["id"], name=row["name"], kind=row["kind"] or "производственная линия",
                        ownership=row["ownership"] or "в штате компании")
                    if row else None)

    def create_line(self, name: str, kind: str = "производственная линия",
                    ownership: str = "в штате компании") -> Line:
        line = Line(id=uuid.uuid4().hex[:10], name=name, kind=kind, ownership=ownership)
        with self._lock:
            self._conn.execute(
                "INSERT INTO lines (id, name, type, kind, ownership) VALUES (?,?,?,?,?)",
                (line.id, line.name, line.kind, line.kind, line.ownership))
            self._conn.commit()
        return line

    def update_line(self, line_id: str, name: str | None = None, kind: str | None = None,
                    ownership: str | None = None) -> Line | None:
        with self._lock:
            line = self.get_line(line_id)
            if not line:
                return None
            if name is not None:
                line.name = name
            if kind is not None:
                line.kind = kind
            if ownership is not None:
                line.ownership = ownership
            self._conn.execute("UPDATE lines SET name=?, type=?, kind=?, ownership=? WHERE id=?",
                               (line.name, line.kind, line.kind, line.ownership, line.id))
            self._conn.commit()
        return line

    # ---------- справочник материалов (переиспользуется в ограничениях проекта) ----------
    def list_materials(self) -> list[Material]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM materials ORDER BY name").fetchall()
            return [Material(id=r["id"], name=r["name"]) for r in rows]

    def _find_or_create_material(self, name: str) -> Material:
        name = name.strip()
        row = self._conn.execute(
            "SELECT * FROM materials WHERE lower(name)=lower(?)", (name,)).fetchone()
        if row:
            return Material(id=row["id"], name=row["name"])
        mat = Material(id=uuid.uuid4().hex[:10], name=name)
        self._conn.execute("INSERT INTO materials VALUES (?,?)", (mat.id, mat.name))
        return mat

    def find_or_create_material(self, name: str) -> Material:
        with self._lock:
            mat = self._find_or_create_material(name)
            self._conn.commit()
        return mat

    # ---------- сырьё линии ----------
    def list_line_materials(self, line_id: str) -> list[LineMaterial]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM line_materials WHERE line_id=? ORDER BY name", (line_id,)).fetchall()
            return [LineMaterial(id=r["id"], line_id=r["line_id"], material_id=r["material_id"],
                                 name=r["name"], quantity=r["quantity"] or 0.0,
                                 unit=r["unit"] or "т") for r in rows]

    def add_line_material(self, line_id: str, name: str, quantity: float = 0.0,
                          unit: str = "т", material_id: str | None = None) -> LineMaterial:
        with self._lock:
            mat = None
            if material_id:
                row = self._conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
                mat = Material(id=row["id"], name=row["name"]) if row else None
            if mat is None:
                mat = self._find_or_create_material(name)
            lm = LineMaterial(id=uuid.uuid4().hex[:10], line_id=line_id, material_id=mat.id,
                              name=mat.name, quantity=quantity, unit=unit)
            self._conn.execute("INSERT INTO line_materials VALUES (?,?,?,?,?,?)",
                               (lm.id, lm.line_id, lm.material_id, lm.name, lm.quantity, lm.unit))
            self._conn.commit()
        return lm

    def update_line_material(self, lm_id: str, quantity: float | None = None,
                             unit: str | None = None, name: str | None = None,
                             material_id: str | None = None) -> LineMaterial | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM line_materials WHERE id=?", (lm_id,)).fetchone()
            if not row:
                return None
            lm = LineMaterial(id=row["id"], line_id=row["line_id"], material_id=row["material_id"],
                              name=row["name"], quantity=row["quantity"] or 0.0, unit=row["unit"] or "т")
            if quantity is not None:
                lm.quantity = quantity
            if unit is not None:
                lm.unit = unit
            if material_id is not None:
                mrow = self._conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
                if mrow:
                    lm.material_id, lm.name = mrow["id"], mrow["name"]
            elif name is not None and name.strip() and name.strip() != lm.name:
                mat = self._find_or_create_material(name)
                lm.material_id, lm.name = mat.id, mat.name
            self._conn.execute("UPDATE line_materials SET material_id=?, name=?, quantity=?, unit=? WHERE id=?",
                               (lm.material_id, lm.name, lm.quantity, lm.unit, lm.id))
            self._conn.commit()
        return lm

    def delete_line_material(self, lm_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM line_materials WHERE id=?", (lm_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ---------- оборудование (онтология линии) ----------
    def list_equipment(self, line_id: str) -> list[Equipment]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM equipment WHERE line_id=? ORDER BY category, name, position",
                (line_id,)).fetchall()
            return [Equipment(id=r["id"], line_id=r["line_id"], name=r["name"],
                              position=r["position"] or "", category=r["category"] or "",
                              status=r["status"] or "в эксплуатации") for r in rows]

    def add_equipment(self, line_id: str, name: str, position: str = "",
                      category: str = "", status: str = "в эксплуатации") -> Equipment:
        eq = Equipment(id=uuid.uuid4().hex[:10], line_id=line_id, name=name,
                       position=position, category=category, status=status)
        with self._lock:
            self._conn.execute(
                "INSERT INTO equipment VALUES (?,?,?,?,?,?)",
                (eq.id, eq.line_id, eq.name, eq.position, eq.category, eq.status))
            self._conn.commit()
        return eq

    def update_equipment(self, eq_id: str, name: str | None = None, position: str | None = None,
                         category: str | None = None, status: str | None = None) -> Equipment | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM equipment WHERE id=?", (eq_id,)).fetchone()
            if not row:
                return None
            eq = Equipment(id=row["id"], line_id=row["line_id"], name=row["name"],
                          position=row["position"] or "", category=row["category"] or "",
                          status=row["status"] or "в эксплуатации")
            if name is not None:
                eq.name = name
            if position is not None:
                eq.position = position
            if category is not None:
                eq.category = category
            if status is not None:
                eq.status = status
            self._conn.execute(
                "UPDATE equipment SET name=?, position=?, category=?, status=? WHERE id=?",
                (eq.name, eq.position, eq.category, eq.status, eq.id))
            self._conn.commit()
        return eq

    def delete_equipment(self, eq_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM equipment WHERE id=?", (eq_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ---------- стоп-лист линии (память фидбэка, line-scoped) ----------
    def _row_to_stop(self, r) -> StopEntry:
        return StopEntry(id=r["id"], line_id=r["line_id"], direction=r["direction"] or "",
                         reason=r["reason"] or "", project_id=r["project_id"],
                         hypothesis_id=r["hypothesis_id"], created_at=r["created_at"] or "")

    def list_line_stoplist(self, line_id: str) -> list[StopEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM line_stoplist WHERE line_id=? ORDER BY created_at DESC, rowid DESC",
                (line_id,)).fetchall()
            return [self._row_to_stop(r) for r in rows]

    def add_line_stop(self, line_id: str, direction: str = "", reason: str = "",
                      project_id: str | None = None,
                      hypothesis_id: str | None = None) -> StopEntry:
        """Записывает отклонённое направление в стоп-лист линии.

        Идемпотентно по (line_id, hypothesis_id): повторное отклонение той же
        гипотезы обновляет причину, а не плодит дубли. Для ручных записей без
        гипотезы дедуп по направлению (без учёта регистра)."""
        with self._lock:
            existing = None
            if hypothesis_id:
                existing = self._conn.execute(
                    "SELECT id FROM line_stoplist WHERE line_id=? AND hypothesis_id=?",
                    (line_id, hypothesis_id)).fetchone()
            elif direction.strip():
                existing = self._conn.execute(
                    "SELECT id FROM line_stoplist WHERE line_id=? AND lower(direction)=lower(?)",
                    (line_id, direction.strip())).fetchone()
            if existing:
                self._conn.execute(
                    "UPDATE line_stoplist SET direction=?, reason=?, project_id=?, created_at=? WHERE id=?",
                    (direction.strip(), reason.strip(), project_id, _now(), existing["id"]))
                self._conn.commit()
                row = self._conn.execute("SELECT * FROM line_stoplist WHERE id=?",
                                         (existing["id"],)).fetchone()
                return self._row_to_stop(row)
            entry = StopEntry(id=uuid.uuid4().hex[:10], line_id=line_id,
                              direction=direction.strip(), reason=reason.strip(),
                              project_id=project_id, hypothesis_id=hypothesis_id, created_at=_now())
            self._conn.execute(
                "INSERT INTO line_stoplist VALUES (?,?,?,?,?,?,?)",
                (entry.id, entry.line_id, entry.direction, entry.reason,
                 entry.project_id, entry.hypothesis_id, entry.created_at))
            self._conn.commit()
        return entry

    def remove_line_stop_for_hypothesis(self, hypothesis_id: str) -> int:
        """Снимает гипотезу со стоп-листа (по всем линиям) — вызывается при
        «всё-таки принять», чтобы принятое направление снова могло предлагаться."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM line_stoplist WHERE hypothesis_id=?", (hypothesis_id,))
            self._conn.commit()
            return cur.rowcount

    def delete_line_stop(self, stop_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM line_stoplist WHERE id=?", (stop_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ---------- отчёты ----------
    def save_reports(self, project_id: str, source: str, reports: list[TailingsReport],
                     meta: dict | None = None):
        payload = {"source": source, "meta": meta or {},
                   "reports": [r.model_dump() for r in reports]}
        with self._lock:
            self._conn.execute(
                "INSERT INTO reports VALUES (?,?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET source=?, payload_json=?, updated_at=?",
                (project_id, source, json.dumps(payload, ensure_ascii=False), _now(),
                 source, json.dumps(payload, ensure_ascii=False), _now()))
            self._conn.commit()

    def get_reports(self, project_id: str) -> tuple[list[TailingsReport], dict] | None:
        with self._lock:
            row = self._conn.execute("SELECT payload_json FROM reports WHERE project_id=?",
                                     (project_id,)).fetchone()
            if not row:
                return None
            payload = json.loads(row["payload_json"])
        reports = [TailingsReport(**r) for r in payload["reports"]]
        return reports, {"source": payload.get("source"), **payload.get("meta", {})}

    # ---------- гипотезы ----------
    def save_hypotheses(self, project_id: str, hyps: list[Hypothesis], replace: bool = False):
        with self._lock:
            if replace:
                self._conn.execute(
                    "DELETE FROM hypotheses WHERE project_id=? AND status='proposed'", (project_id,))
            for h in hyps:
                self._conn.execute(
                    "INSERT INTO hypotheses VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET payload_json=?, score=?, status=?",
                    (h.id, project_id, h.model_dump_json(), h.score, h.status, _now(),
                     h.model_dump_json(), h.score, h.status))
            self._conn.commit()

    def get_hypotheses(self, project_id: str, statuses: list[str] | None = None) -> list[Hypothesis]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM hypotheses WHERE project_id=? ORDER BY score DESC",
                (project_id,)).fetchall()
        out = [Hypothesis(**json.loads(r["payload_json"])) for r in rows]
        if statuses:
            out = [h for h in out if h.status in statuses]
        return out

    def get_hypothesis(self, hid: str) -> tuple[Hypothesis, str] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json, project_id FROM hypotheses WHERE id=?", (hid,)).fetchone()
            if not row:
                return None
            return Hypothesis(**json.loads(row["payload_json"])), row["project_id"]

    def update_hypothesis(self, h: Hypothesis):
        with self._lock:
            self._conn.execute(
                "UPDATE hypotheses SET payload_json=?, score=?, status=? WHERE id=?",
                (h.model_dump_json(), h.score, h.status, h.id))
            self._conn.commit()

    # ---------- фидбэк ----------
    def add_feedback(self, hypothesis_id: str, project_id: str, action: str, reason: str = ""):
        with self._lock:
            self._conn.execute(
                "INSERT INTO feedback (hypothesis_id, project_id, action, reason, created_at) "
                "VALUES (?,?,?,?,?)", (hypothesis_id, project_id, action, reason, _now()))
            self._conn.commit()

    def get_feedback(self, project_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM feedback WHERE project_id=? ORDER BY id", (project_id,)).fetchall()
            return [dict(r) for r in rows]

    # ---------- чат-ассистент (диалоги) ----------
    def create_chat(self, project_id: str, title: str = "Новый диалог") -> dict:
        chat = {"id": uuid.uuid4().hex[:10], "project_id": project_id,
                "title": title, "created_at": _now(), "updated_at": _now()}
        with self._lock:
            self._conn.execute("INSERT INTO chats VALUES (?,?,?,?,?)",
                               (chat["id"], project_id, title,
                                chat["created_at"], chat["updated_at"]))
            self._conn.commit()
        return {**chat, "messages": 0}

    def get_chat(self, chat_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
            return dict(row) if row else None

    def list_chats(self, project_id: str) -> list[dict]:
        """Диалоги проекта, свежие сверху, с числом сообщений."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM chat_messages m WHERE m.chat_id=c.id) "
                "AS messages FROM chats c WHERE c.project_id=? "
                "ORDER BY c.updated_at DESC, c.rowid DESC", (project_id,)).fetchall()
            return [dict(r) for r in rows]

    def latest_chat(self, project_id: str) -> dict | None:
        chats = self.list_chats(project_id)
        return chats[0] if chats else None

    def rename_chat(self, chat_id: str, title: str):
        with self._lock:
            self._conn.execute("UPDATE chats SET title=?, updated_at=? WHERE id=?",
                               (title, _now(), chat_id))
            self._conn.commit()

    def delete_chat(self, chat_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
            self._conn.execute("DELETE FROM chat_messages WHERE chat_id=?", (chat_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def add_chat_message(self, project_id: str, role: str, content: str,
                         refs: list[dict] | None = None,
                         charts: list[dict] | None = None,
                         chat_id: str | None = None):
        with self._lock:
            self._conn.execute(
                "INSERT INTO chat_messages (project_id, chat_id, role, content, "
                "refs_json, charts_json, created_at) VALUES (?,?,?,?,?,?,?)",
                (project_id, chat_id, role, content,
                 json.dumps(refs or [], ensure_ascii=False),
                 json.dumps(charts or [], ensure_ascii=False), _now()))
            if chat_id:
                self._conn.execute("UPDATE chats SET updated_at=? WHERE id=?",
                                   (_now(), chat_id))
            self._conn.commit()

    def get_chat_messages(self, project_id: str, limit: int = 100,
                          chat_id: str | None = None) -> list[dict]:
        """Последние `limit` сообщений в хронологическом порядке
        (всего проекта или одного диалога)."""
        where, params = "project_id=?", [project_id]
        if chat_id:
            where += " AND chat_id=?"
            params.append(chat_id)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT role, content, refs_json, charts_json, created_at "
                f"FROM chat_messages WHERE {where} ORDER BY id DESC LIMIT ?",
                (*params, limit)).fetchall()
        return [{"role": r["role"], "content": r["content"],
                 "references": json.loads(r["refs_json"] or "[]"),
                 "charts": json.loads(r["charts_json"] or "[]"),
                 "created_at": r["created_at"]} for r in reversed(rows)]

    def clear_chat(self, project_id: str) -> int:
        """Удаляет все диалоги проекта; возвращает число удалённых сообщений."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM chat_messages WHERE project_id=?",
                                     (project_id,))
            self._conn.execute("DELETE FROM chats WHERE project_id=?", (project_id,))
            self._conn.commit()
            return cur.rowcount


    # ---------- изображения схем фабрик ----------
    def _seed_factory_images(self):
        """Идемпотентный сид: исходные схемы из domain_pack привязываются к
        фабрикам в БД (файлы остаются в data/case, path пустой)."""
        try:
            from .domain import pack
            flowsheets = pack().get("flowsheets") or {}
        except Exception:
            return
        for factory, sheet in flowsheets.items():
            for fn in sheet.get("source_files") or []:
                row = self._conn.execute(
                    "SELECT 1 FROM factory_images WHERE factory=? AND filename=?",
                    (factory, fn)).fetchone()
                if not row:
                    self._conn.execute(
                        "INSERT INTO factory_images VALUES (?,?,?,?,?,?)",
                        (uuid.uuid4().hex[:10], factory, fn,
                         "Схема из материалов кейса", "", _now()))

    # ---------- оцифрованные схемы линий (загрузка пользователя) ----------
    def save_line_flowsheet(self, key: str, payload: dict | None,
                            source_image: str = "", status: str = "processing",
                            error: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO line_flowsheets (key, payload_json, source_image, "
                "status, error, updated_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET payload_json=excluded.payload_json, "
                "source_image=excluded.source_image, status=excluded.status, "
                "error=excluded.error, updated_at=excluded.updated_at",
                (key, json.dumps(payload, ensure_ascii=False) if payload else None,
                 source_image, status, error, _now()))
            self._conn.commit()

    def get_line_flowsheet(self, key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM line_flowsheets WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["payload"] = json.loads(d.pop("payload_json")) if d.get("payload_json") else None
        return d

    def list_factory_images(self, factory: str | None = None) -> list[dict]:
        with self._lock:
            if factory:
                rows = self._conn.execute(
                    "SELECT * FROM factory_images WHERE factory=? ORDER BY created_at, rowid",
                    (factory,)).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM factory_images ORDER BY factory, created_at, rowid").fetchall()
            return [dict(r) for r in rows]

    def get_factory_image(self, img_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM factory_images WHERE id=?",
                                     (img_id,)).fetchone()
            return dict(row) if row else None

    def add_factory_image(self, factory: str, filename: str, caption: str = "",
                          path: str = "") -> dict:
        img = {"id": uuid.uuid4().hex[:10], "factory": factory, "filename": filename,
               "caption": caption, "path": path, "created_at": _now()}
        with self._lock:
            self._conn.execute("INSERT INTO factory_images VALUES (?,?,?,?,?,?)",
                               (img["id"], factory, filename, caption, path, img["created_at"]))
            self._conn.commit()
        return img

    def update_factory_image(self, img_id: str, caption: str) -> dict | None:
        with self._lock:
            self._conn.execute("UPDATE factory_images SET caption=? WHERE id=?",
                               (caption, img_id))
            self._conn.commit()
        return self.get_factory_image(img_id)

    def delete_factory_image(self, img_id: str) -> bool:
        img = self.get_factory_image(img_id)
        if not img:
            return False
        if img.get("path"):   # загруженный файл удаляем, файлы кейса не трогаем
            try:
                Path(img["path"]).unlink(missing_ok=True)
            except OSError:
                pass
        with self._lock:
            self._conn.execute("DELETE FROM factory_images WHERE id=?", (img_id,))
            self._conn.commit()
        return True

    # ---------- материалы проекта (файлы с извлечённым текстом) ----------
    def add_project_file(self, project_id: str, filename: str, kind: str,
                         text: str, status: str, path: str) -> dict:
        f = {"id": uuid.uuid4().hex[:10], "project_id": project_id,
             "filename": filename, "kind": kind, "text": text,
             "status": status, "path": path, "created_at": _now()}
        with self._lock:
            self._conn.execute("INSERT INTO project_files VALUES (?,?,?,?,?,?,?,?)",
                               (f["id"], project_id, filename, kind, text,
                                status, path, f["created_at"]))
            self._conn.commit()
        return f

    def list_project_files(self, project_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM project_files WHERE project_id=? ORDER BY created_at, rowid",
                (project_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_project_file(self, fid: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM project_files WHERE id=?",
                                     (fid,)).fetchone()
            return dict(row) if row else None

    def delete_project_file(self, fid: str) -> bool:
        f = self.get_project_file(fid)
        if not f:
            return False
        if f.get("path"):
            try:
                Path(f["path"]).unlink(missing_ok=True)
            except OSError:
                pass
        with self._lock:
            self._conn.execute("DELETE FROM project_files WHERE id=?", (fid,))
            self._conn.commit()
        return True

    # ---------- дорожная карта ----------
    def save_roadmap(self, project_id: str, items: list[dict]):
        payload = json.dumps(items, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT INTO roadmaps VALUES (?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET payload_json=?, updated_at=?",
                (project_id, payload, _now(), payload, _now()))
            self._conn.commit()

    def get_roadmap(self, project_id: str) -> list[dict]:
        with self._lock:
            row = self._conn.execute("SELECT payload_json FROM roadmaps WHERE project_id=?",
                                     (project_id,)).fetchone()
            return json.loads(row["payload_json"]) if row else []


_default_store: Store | None = None


def default_store() -> Store:
    global _default_store
    if _default_store is None:
        _default_store = Store()
    return _default_store
