"""Persistência em SQLite: produções, cenas, tentativas, revisões e eventos.

Cada transição importante gera um evento. Tentativas nunca são apagadas: resultados
substituídos ficam marcados como `superseded` para auditoria.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import migrations
from .states import (
    ProductionStatus,
    SceneStatus,
    check_production_transition,
    check_scene_transition,
)

# O schema vive em migrations.py (PRAGMA user_version).


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


BUSY_TIMEOUT_MS = 30_000
WAL_ATTEMPTS = 50          # tentativas de trocar para WAL num banco novo
WAL_RETRY_SLEEP_S = 0.1


def _enable_wal(conn: sqlite3.Connection) -> None:
    """Troca o journal_mode para WAL tolerando disputa. A troca num arquivo novo exige lock exclusivo e, quando
    outra conexão está fazendo o mesmo, o SQLite devolve SQLITE_BUSY na hora (sem passar pelo busy_timeout, para
    evitar deadlock). Aqui isso é transitório: tenta de novo por até ~5 s. Só erros de "locked/busy" são repetidos."""
    for attempt in range(WAL_ATTEMPTS):
        try:
            mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(mode).lower() == "wal":
                return
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "locked" not in msg and "busy" not in msg:
                raise
            if attempt == WAL_ATTEMPTS - 1:
                raise
        time.sleep(WAL_RETRY_SLEEP_S)
    raise sqlite3.OperationalError("não foi possível ativar o modo WAL (journal_mode != wal)")


def connect(path: Path) -> sqlite3.Connection:
    """Abre uma conexão SQLite configurada (uma por requisição; não compartilhe entre requisições).

    WAL + synchronous=NORMAL (durável contra queda do processo; num corte de energia pode perder as últimas
    transações, nunca corromper), busy_timeout para esperar o lock de escrita em vez de falhar na hora,
    chaves estrangeiras ligadas. O checkpoint automático do WAL fica no padrão do SQLite (1000 páginas) e o app
    ainda roda checkpoints PASSIVE periódicos (`checkpoint`): PASSIVE nunca bloqueia leitores/escritores nem
    atrapalha o Litestream."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    _enable_wal(conn)
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def checkpoint(path: Path) -> tuple[int, int, int]:
    """Checkpoint PASSIVE do WAL (busy, páginas no WAL, páginas copiadas). Seguro com o Litestream rodando."""
    conn = connect(path)
    try:
        r = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        return int(r[0]), int(r[1]), int(r[2])
    finally:
        conn.close()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.conn = connect(path)
        try:
            migrations.migrate(self.conn)   # banco em dia: só um PRAGMA user_version
        except BaseException:
            self.conn.close()
            raise

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- eventos
    def add_event(self, production_id: str, type_: str, message: str = "", *, scene_idx: int | None = None,
                  from_state: str | None = None, to_state: str | None = None, data: dict | None = None) -> None:
        self.conn.execute(
            "INSERT INTO events(production_id, scene_idx, ts, type, from_state, to_state, message, data_json)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (production_id, scene_idx, now(), type_, from_state, to_state, message,
             json.dumps(data, ensure_ascii=False) if data else None),
        )

    # ------------------------------------------------- execução (retomada após reinício)
    def set_run_state(self, pid: str, state: str, *, resume_attempts: int | None = None, reset_attempts: bool = False) -> None:
        self.conn.execute(
            "INSERT INTO run_state(production_id, state, resume_attempts, updated_at) VALUES (?,?,?,?)"
            " ON CONFLICT(production_id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at,"
            " resume_attempts=CASE WHEN ? THEN 0 WHEN ? IS NOT NULL THEN ? ELSE resume_attempts END",
            (pid, state, resume_attempts or 0, now(), int(reset_attempts), resume_attempts, resume_attempts))

    def run_states(self, *states: str) -> list[sqlite3.Row]:
        marks = ",".join("?" * len(states))
        return self.conn.execute(f"SELECT * FROM run_state WHERE state IN ({marks}) ORDER BY updated_at", states).fetchall()

    def events(self, production_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events WHERE production_id=? ORDER BY id", (production_id,)
        ).fetchall()

    # -------------------------------------------------------------- produções
    def create_production(self, *, mode: str, format_id: str, product: dict, profiles: dict, budget_usd: float,
                          go_ahead: str = "all", autonomy: str = "classico") -> str:
        pid = new_id("prod")
        ts = now()
        self.conn.execute(
            "INSERT INTO productions(id, status, mode, format_id, product_json, profiles_json, budget_usd, go_ahead,"
            " autonomy, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, ProductionStatus.RECEIVED, mode, format_id, json.dumps(product, ensure_ascii=False),
             json.dumps(profiles, ensure_ascii=False), budget_usd, go_ahead, autonomy, ts, ts),
        )
        self.add_event(pid, "production_created", f"modo={mode} formato={format_id} orçamento=US${budget_usd:.2f}",
                       to_state=ProductionStatus.RECEIVED)
        return pid

    def production(self, pid: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM productions WHERE id=?", (pid,)).fetchone()
        if row is None:
            raise KeyError(f"produção {pid} não encontrada")
        return row

    def productions(self, workspace_id: str | None = None) -> list[sqlite3.Row]:
        if workspace_id is None:
            return self.conn.execute("SELECT * FROM productions ORDER BY created_at DESC").fetchall()
        return self.conn.execute("SELECT * FROM productions WHERE workspace_id=? ORDER BY created_at DESC",
                                 (workspace_id,)).fetchall()

    def update_production(self, pid: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = now()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE productions SET {cols} WHERE id=?", (*fields.values(), pid))

    def set_production_status(self, pid: str, new: ProductionStatus, reason: str = "") -> None:
        row = self.production(pid)
        current = ProductionStatus(row["status"])
        if current == new:
            return
        check_production_transition(current, new)
        extra: dict[str, Any] = {"status": new, "status_reason": reason or None}
        if new == ProductionStatus.PAUSED:
            extra["resume_status"] = current
        self.update_production(pid, **extra)
        self.add_event(pid, "production_status", reason, from_state=current, to_state=new)

    def resume_production(self, pid: str, reason: str = "retomada manual") -> ProductionStatus:
        row = self.production(pid)
        if row["status"] != ProductionStatus.PAUSED:
            raise ValueError("produção não está pausada")
        target = ProductionStatus(row["resume_status"])
        extra = {"pause_code": None} if "pause_code" in row.keys() else {}
        self.update_production(pid, status=target, resume_status=None, status_reason=None, **extra)
        self.add_event(pid, "production_status", reason, from_state=ProductionStatus.PAUSED, to_state=target)
        return target

    # ------------------------------------------------------------------ cenas
    def upsert_scene(self, pid: str, idx: int, spec_json: str, spec_hash: str) -> None:
        existing = self.conn.execute("SELECT 1 FROM scenes WHERE production_id=? AND idx=?", (pid, idx)).fetchone()
        if existing:
            self.conn.execute(
                "UPDATE scenes SET spec_json=?, spec_hash=?, updated_at=? WHERE production_id=? AND idx=?",
                (spec_json, spec_hash, now(), pid, idx),
            )
        else:
            self.conn.execute(
                "INSERT INTO scenes(production_id, idx, status, spec_json, spec_hash, updated_at) VALUES (?,?,?,?,?,?)",
                (pid, idx, SceneStatus.PENDING, spec_json, spec_hash, now()),
            )

    def scene(self, pid: str, idx: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM scenes WHERE production_id=? AND idx=?", (pid, idx)).fetchone()
        if row is None:
            raise KeyError(f"cena {idx} não encontrada em {pid}")
        return row

    def scenes(self, pid: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM scenes WHERE production_id=? ORDER BY idx", (pid,)).fetchall()

    def update_scene(self, pid: str, idx: int, **fields: Any) -> None:
        fields["updated_at"] = now()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE scenes SET {cols} WHERE production_id=? AND idx=?", (*fields.values(), pid, idx))

    def set_scene_status(self, pid: str, idx: int, new: SceneStatus, reason: str = "", **fields: Any) -> None:
        current = SceneStatus(self.scene(pid, idx)["status"])
        if current != new:
            check_scene_transition(current, new)
        self.update_scene(pid, idx, status=new, **fields)
        if current != new:
            self.add_event(pid, "scene_status", reason, scene_idx=idx, from_state=current, to_state=new)

    # ------------------------------------------------------------- tentativas
    def create_attempt(self, *, production_id: str, scene_idx: int | None, kind: str, provider: str, model: str,
                       simulated: bool, input_hash: str, prompt: str | None, params: dict, references: list,
                       estimated_cost_usd: float, pricing_source: str) -> str:
        attempt_no = self.conn.execute(
            "SELECT COUNT(*) FROM attempts WHERE production_id=? AND scene_idx IS ? AND kind=?",
            (production_id, scene_idx, kind),
        ).fetchone()[0] + 1
        aid = new_id("att")
        self.conn.execute(
            "INSERT INTO attempts(id, production_id, scene_idx, kind, attempt_no, status, provider, model, simulated,"
            " input_hash, prompt, params_json, references_json, estimated_cost_usd, pricing_source, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, production_id, scene_idx, kind, attempt_no, "created", provider, model, int(simulated), input_hash,
             prompt, json.dumps(params, ensure_ascii=False), json.dumps(references, ensure_ascii=False),
             estimated_cost_usd, pricing_source, now()),
        )
        self.add_event(production_id, "attempt_created", f"{kind} #{attempt_no} ({provider}/{model})",
                       scene_idx=scene_idx, data={"attempt_id": aid, "estimated_cost_usd": estimated_cost_usd})
        return aid

    def attempt(self, aid: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM attempts WHERE id=?", (aid,)).fetchone()
        if row is None:
            raise KeyError(aid)
        return row

    def update_attempt(self, aid: str, **fields: Any) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE attempts SET {cols} WHERE id=?", (*fields.values(), aid))

    def attempts(self, pid: str, scene_idx: int | None = None, kind: str | None = None) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM attempts WHERE production_id=?", [pid]
        if scene_idx is not None:
            sql += " AND scene_idx=?"
            args.append(scene_idx)
        if kind is not None:
            sql += " AND kind=?"
            args.append(kind)
        return self.conn.execute(sql + " ORDER BY created_at, attempt_no", args).fetchall()

    def count_generation_attempts(self, pid: str, scene_idx: int, kind: str) -> int:
        """Tentativas resolvidas (enviadas, concluídas ou com falha). Exclui as substituídas por invalidação."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM attempts WHERE production_id=? AND scene_idx=? AND kind=? AND superseded=0"
            " AND status != 'created'",
            (pid, scene_idx, kind),
        ).fetchone()[0]

    def reusable_attempt(self, pid: str, kind: str, input_hash: str) -> sqlite3.Row | None:
        """Resultado pago já concluído com a mesma entrada e sem reprovação: reaproveitar em vez de gerar de novo."""
        return self.conn.execute(
            "SELECT * FROM attempts a WHERE production_id=? AND kind=? AND input_hash=? AND status='succeeded'"
            " AND superseded=0 AND NOT EXISTS (SELECT 1 FROM reviews r WHERE r.attempt_id=a.id"
            " AND r.decision='rejected') ORDER BY finished_at DESC LIMIT 1",
            (pid, kind, input_hash),
        ).fetchone()

    def inflight_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM attempts WHERE status='submitted'").fetchone()[0]

    def supersede_attempts(self, pid: str, scene_idx: int, kind: str, reason: str) -> None:
        cur = self.conn.execute(
            "UPDATE attempts SET superseded=1 WHERE production_id=? AND scene_idx=? AND kind=? AND superseded=0",
            (pid, scene_idx, kind),
        )
        if cur.rowcount:
            self.add_event(pid, "attempts_superseded", f"{kind}: {reason}", scene_idx=scene_idx,
                           data={"count": cur.rowcount})

    # ------------------------------------------------------------- revisões
    def add_review(self, *, production_id: str, scene_idx: int | None, attempt_id: str | None, stage: str,
                   reviewer: str, decision: str, result: dict) -> str:
        rid = new_id("rev")
        self.conn.execute(
            "INSERT INTO reviews(id, production_id, scene_idx, attempt_id, stage, reviewer, decision, result_json, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (rid, production_id, scene_idx, attempt_id, stage, reviewer, decision,
             json.dumps(result, ensure_ascii=False), now()),
        )
        self.add_event(production_id, "review", f"{stage} {reviewer}: {decision}", scene_idx=scene_idx,
                       data={"review_id": rid, "attempt_id": attempt_id})
        return rid

    def reviews(self, pid: str, scene_idx: int | None = None) -> list[sqlite3.Row]:
        if scene_idx is None:
            return self.conn.execute("SELECT * FROM reviews WHERE production_id=? ORDER BY created_at", (pid,)).fetchall()
        return self.conn.execute(
            "SELECT * FROM reviews WHERE production_id=? AND scene_idx=? ORDER BY created_at", (pid, scene_idx)
        ).fetchall()

    def reviews_for_attempt(self, attempt_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM reviews WHERE attempt_id=? ORDER BY created_at", (attempt_id,)).fetchall()
