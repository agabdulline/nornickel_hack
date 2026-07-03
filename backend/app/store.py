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
from .models import Equipment, Hypothesis, Project, ProjectConstraints, TailingsReport

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
"""

# сид онтологии оборудования (раздел «Ограничения») для демо-линии кейса;
# намеренно без отсадочных машин — сценарий «оборудования нет» в п.4 задачи
_SEED_EQUIPMENT: dict[str, list[dict]] = {
    "НОФ · вкрапленные руды": [
        {"name": "Гидроциклон ГЦ-660", "position": "5-3", "category": "гидроциклон"},
        {"name": "Гидроциклон ГЦ-660", "position": "5-5", "category": "гидроциклон"},
        {"name": "Мельница МШЦ 4,5×6,0", "position": "5-3", "category": "мельница"},
        {"name": "Мельница МШРГУ 4,5×6,0", "position": "5-1", "category": "мельница"},
        {"name": "Флотомашина ФПМ-16-4К", "position": "3-2", "category": "флотомашина"},
        {"name": "Сгуститель П-30", "position": "7-1", "category": "сгуститель"},
    ],
}


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
        self._migrate_project_constraints()
        self._seed_equipment()
        self._conn.commit()

    def _migrate_project_constraints(self):
        """Аддитивная миграция: старые БД созданы до появления раздела «Ограничения»."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(projects)")}
        if "project_constraints_json" not in cols:
            self._conn.execute("ALTER TABLE projects ADD COLUMN project_constraints_json TEXT")

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

    # ---------- проекты ----------
    def create_project(self, plant: str, goal: str = "", constraints: str = "",
                       weights: dict | None = None,
                       project_constraints: ProjectConstraints | None = None) -> Project:
        p = Project(id=uuid.uuid4().hex[:10], plant=plant, goal=goal,
                    constraints=constraints, created_at=_now())
        if weights:
            p.weights = weights
        if project_constraints:
            p.project_constraints = project_constraints
        with self._lock:
            self._conn.execute(
                "INSERT INTO projects (id, plant, goal, constraints, created_at, "
                "weights_json, stoplist_json, project_constraints_json) VALUES (?,?,?,?,?,?,?,?)",
                (p.id, p.plant, p.goal, p.constraints, p.created_at,
                 json.dumps(p.weights), json.dumps(p.stoplist, ensure_ascii=False),
                 p.project_constraints.model_dump_json()))
            self._conn.commit()
        return p

    def get_project(self, pid: str) -> Project | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
            if not row:
                return None
            raw_pc = row["project_constraints_json"] if "project_constraints_json" in row.keys() else None
            pc = ProjectConstraints(**json.loads(raw_pc)) if raw_pc else ProjectConstraints()
            return Project(id=row["id"], plant=row["plant"], goal=row["goal"],
                           constraints=row["constraints"], created_at=row["created_at"],
                           weights=json.loads(row["weights_json"] or "{}"),
                           stoplist=json.loads(row["stoplist_json"] or "[]"),
                           project_constraints=pc)

    def list_projects(self) -> list[Project]:
        with self._lock:
            rows = self._conn.execute("SELECT id FROM projects ORDER BY created_at DESC").fetchall()
            return [self.get_project(r["id"]) for r in rows]

    def update_project(self, p: Project):
        with self._lock:
            self._conn.execute(
                "UPDATE projects SET weights_json=?, stoplist_json=?, goal=?, constraints=?, "
                "project_constraints_json=? WHERE id=?",
                (json.dumps(p.weights), json.dumps(p.stoplist, ensure_ascii=False),
                 p.goal, p.constraints, p.project_constraints.model_dump_json(), p.id))
            self._conn.commit()

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
