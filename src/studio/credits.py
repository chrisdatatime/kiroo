"""Livro-razão de créditos por workspace (Fase C).

Unidade: centésimo de crédito (inteiro), para não acumular arredondamento por chamada.
Ciclo de cada chamada paga:
  reserva (−estimado) antes de chamar → ao terminar, liberação (+reservado) e débito (−custo).
  Recusa sem custo = só a liberação (estorno). Reserva órfã (processo caiu antes de criar a tentativa) é liberada
  depois de ORPHAN_MINUTES.
O custo debitado segue a mesma regra do orçamento da produção: custo confirmado quando o provedor informa, senão o
estimado. Workspaces isentos (dono da plataforma) registram tudo, mas não precisam de saldo.
Entradas não são apagadas nem editadas; correções viram lançamentos de ajuste. `ext_ref` único torna cada lançamento
idempotente (base para os webhooks do Mercado Pago na Fase D).
"""

from __future__ import annotations

import math
import threading
from datetime import datetime, timedelta, timezone

from .db import Database, new_id, now

ORPHAN_MINUTES = 15
_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS credit_entries (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount_cc INTEGER NOT NULL,
    usd REAL,
    hold_id TEXT,
    production_id TEXT,
    attempt_id TEXT,
    stage TEXT,
    note TEXT,
    ext_ref TEXT UNIQUE,
    created_by TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_credit_ws ON credit_entries(workspace_id, created_at);
CREATE INDEX IF NOT EXISTS ix_credit_hold ON credit_entries(hold_id);
CREATE INDEX IF NOT EXISTS ix_credit_prod ON credit_entries(production_id);
"""

KINDS_IN = {"grant", "purchase", "adjust"}  # entradas manuais/compras
LABELS = {"grant": "Créditos liberados", "purchase": "Compra", "adjust": "Ajuste", "reserve": "Reserva",
          "release": "Reserva devolvida", "debit": "Uso"}
STAGES = {"image": "Imagens", "video": "Vídeos", "review_image": "Conferência das imagens",
          "review_video": "Conferência dos takes", "plan": "Direção (roteiro)"}


class InsufficientCredits(Exception):
    def __init__(self, balance_cc: int, needed_cc: int):
        super().__init__(f"saldo {balance_cc / 100:.2f} créditos, necessário {needed_cc / 100:.2f}")
        self.balance_cc = balance_cc
        self.needed_cc = needed_cc


def to_cc(usd: float) -> int:
    """US$ → centésimos de crédito pela política vigente (arredonda para cima)."""
    if not usd or usd <= 0:
        return 0
    from .billing import policy  # import tardio: billing importa o orquestrador
    p = policy()
    return math.ceil(usd * p.fx_brl_per_usd * p.margin / p.credit_price_brl * 100 - 1e-9)


def fmt(cc: int) -> str:
    """Centésimos → texto em créditos (pt-BR)."""
    s = f"{abs(cc) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if s.endswith(",00"):
        s = s[:-3]
    return ("−" if cc < 0 else "") + s


class Ledger:
    def __init__(self, db: Database):
        self.db = db
        db.conn.executescript(SCHEMA)

    # ------------------------------------------------------------- leitura
    def balance(self, wid: str) -> int:
        return self.db.conn.execute("SELECT COALESCE(SUM(amount_cc),0) FROM credit_entries WHERE workspace_id=?",
                                    (wid,)).fetchone()[0]

    def held(self, wid: str) -> int:
        """Reservas ainda abertas (positivo)."""
        return self.db.conn.execute(
            "SELECT COALESCE(-SUM(r.amount_cc),0) FROM credit_entries r WHERE r.workspace_id=? AND r.kind='reserve'"
            " AND NOT EXISTS (SELECT 1 FROM credit_entries x WHERE x.hold_id=r.hold_id AND x.kind='release')",
            (wid,)).fetchone()[0]

    def exempt(self, wid: str) -> bool:
        row = self.db.conn.execute("SELECT credits_exempt FROM workspaces WHERE id=?", (wid,)).fetchone()
        return bool(row and row[0])

    def summary(self, wid: str) -> dict:
        bal, held = self.balance(wid), self.held(wid)
        return {"balance_cc": bal, "held_cc": held, "available_cc": bal, "exempt": self.exempt(wid),
                "balance": fmt(bal), "held": fmt(held)}

    def statement(self, wid: str, limit: int = 60) -> list[dict]:
        """Extrato: créditos que entraram e uso por tentativa (reserva+liberação+débito viram uma linha)."""
        rows = self.db.conn.execute(
            "SELECT e.*, p.product_json FROM credit_entries e LEFT JOIN productions p ON p.id=e.production_id"
            " WHERE e.workspace_id=? AND e.kind IN ('grant','purchase','adjust','debit','release')"
            " ORDER BY e.created_at DESC, e.rowid DESC LIMIT ?", (wid, limit * 3)).fetchall()
        debited = {r["hold_id"] for r in rows if r["kind"] == "debit"}
        out = []
        for r in rows:
            if r["kind"] == "release" and r["hold_id"] in debited:
                continue  # a liberação de uma reserva que virou débito não interessa no extrato
            kind = "refund" if r["kind"] == "release" else r["kind"]
            amount = 0 if kind == "refund" else r["amount_cc"]
            out.append({"id": r["id"], "kind": kind, "at": r["created_at"], "amount_cc": amount, "amount": fmt(amount),
                        "label": "Estorno (sem custo)" if kind == "refund" else LABELS.get(kind, kind),
                        "stage": STAGES.get(r["stage"] or "", r["stage"] or ""), "production_id": r["production_id"],
                        "product": _title(r["product_json"]), "note": r["note"] or ""})
            if len(out) >= limit:
                break
        return out

    def usage(self, wid: str) -> list[dict]:
        """Consumo por produção e por etapa (débitos)."""
        rows = self.db.conn.execute(
            "SELECT e.production_id, e.stage, SUM(-e.amount_cc) cc, COUNT(*) n, p.product_json"
            " FROM credit_entries e LEFT JOIN productions p ON p.id=e.production_id"
            " WHERE e.workspace_id=? AND e.kind='debit' GROUP BY e.production_id, e.stage", (wid,)).fetchall()
        by: dict[str, dict] = {}
        for r in rows:
            d = by.setdefault(r["production_id"], {"production_id": r["production_id"], "product": _title(r["product_json"]),
                                                   "total_cc": 0, "stages": []})
            d["total_cc"] += r["cc"]
            d["stages"].append({"stage": STAGES.get(r["stage"] or "", r["stage"] or "outros"), "cc": r["cc"],
                                "credits": fmt(r["cc"]), "calls": r["n"]})
        out = sorted(by.values(), key=lambda d: -d["total_cc"])
        for d in out:
            d["total"] = fmt(d["total_cc"])
            d["stages"].sort(key=lambda s: -s["cc"])
        return out

    # ------------------------------------------------------------- escrita
    def _insert(self, **f) -> str:
        eid = new_id("cre")
        f.setdefault("created_at", now())
        cols = ", ".join(["id", *f])
        self.db.conn.execute(f"INSERT INTO credit_entries({cols}) VALUES ({', '.join('?' * (len(f) + 1))})",
                             (eid, *f.values()))
        return eid

    def add(self, wid: str, credits_cc: int, *, kind: str = "grant", note: str = "", ext_ref: str | None = None,
            by: str | None = None) -> str:
        """Entrada manual (liberação, compra, ajuste). Mesmo ext_ref = mesmo lançamento (idempotente)."""
        if kind not in KINDS_IN:
            raise ValueError("tipo de lançamento inválido")
        if kind != "adjust" and credits_cc <= 0:
            raise ValueError("a quantidade precisa ser positiva")
        with _LOCK:
            if ext_ref:
                row = self.db.conn.execute("SELECT id FROM credit_entries WHERE ext_ref=?", (ext_ref,)).fetchone()
                if row:
                    return row[0]
            return self._insert(workspace_id=wid, kind=kind, amount_cc=int(credits_cc), note=note[:300],
                                ext_ref=ext_ref, created_by=by)

    def hold(self, wid: str, pid: str, usd: float, stage: str) -> str | None:
        """Reserva antes de uma chamada paga. Sem saldo → InsufficientCredits (nada é reservado)."""
        cc = to_cc(usd)
        if cc <= 0:
            return None
        hid = new_id("hold")
        with _LOCK:
            self.db.conn.execute("BEGIN IMMEDIATE")
            try:
                bal = self.balance(wid)
                if not self.exempt(wid) and bal < cc:
                    raise InsufficientCredits(bal, cc)
                self._insert(workspace_id=wid, kind="reserve", amount_cc=-cc, usd=usd, hold_id=hid, production_id=pid,
                             stage=stage, ext_ref=f"reserve:{hid}")
                self.db.conn.execute("COMMIT")
            except BaseException:
                self.db.conn.execute("ROLLBACK")
                raise
        return hid

    def attach(self, hid: str | None, attempt_id: str) -> None:
        if hid:
            self.db.conn.execute("UPDATE credit_entries SET attempt_id=? WHERE hold_id=? AND kind='reserve'", (attempt_id, hid))

    def release(self, hid: str | None, note: str = "") -> None:
        """Devolve a reserva sem cobrar (chamada não aconteceu ou foi recusada sem custo)."""
        if not hid:
            return
        with _LOCK:
            r = self.db.conn.execute("SELECT * FROM credit_entries WHERE hold_id=? AND kind='reserve'", (hid,)).fetchone()
            if r is None or self.db.conn.execute("SELECT 1 FROM credit_entries WHERE ext_ref=?", (f"release:{hid}",)).fetchone():
                return
            self._insert(workspace_id=r["workspace_id"], kind="release", amount_cc=-r["amount_cc"], hold_id=hid,
                         production_id=r["production_id"], attempt_id=r["attempt_id"], stage=r["stage"], note=note[:300],
                         ext_ref=f"release:{hid}")

    def close_direct(self, hid: str | None, usd: float, note: str = "") -> None:
        """Fecha uma reserva sem produção (teste de treinamento): devolve a reserva e cobra o custo real."""
        if not hid:
            return
        r = self.db.conn.execute("SELECT * FROM credit_entries WHERE hold_id=? AND kind='reserve'", (hid,)).fetchone()
        self.release(hid, note)
        charge = to_cc(usd)
        if r is not None and charge:
            with _LOCK:
                self._insert(workspace_id=r["workspace_id"], kind="debit", amount_cc=-charge, usd=usd, hold_id=hid, production_id=None,
                             stage=r["stage"], ext_ref=f"debit:{hid}", note=note[:300])

    def settle(self, pid: str) -> int:
        """Fecha as reservas cujas tentativas terminaram. Idempotente; devolve quantas fechou."""
        open_holds = self.db.conn.execute(
            "SELECT r.* FROM credit_entries r WHERE r.production_id=? AND r.kind='reserve'"
            " AND NOT EXISTS (SELECT 1 FROM credit_entries x WHERE x.hold_id=r.hold_id AND x.kind='release')",
            (pid,)).fetchall()
        closed = 0
        stale = (datetime.now(timezone.utc) - timedelta(minutes=ORPHAN_MINUTES)).isoformat(timespec="seconds")
        for r in open_holds:
            hid = r["hold_id"]
            if not r["attempt_id"]:
                if r["created_at"] < stale:
                    self.release(hid, "reserva sem chamada (processo interrompido)")
                    closed += 1
                continue
            att = self.db.attempt(r["attempt_id"])
            if att is None or att["status"] not in ("succeeded", "failed"):
                continue
            usd = att["confirmed_cost_usd"] if (not att["simulated"] and att["confirmed_cost_usd"] is not None) \
                else (att["estimated_cost_usd"] or 0.0)
            charge = to_cc(usd)
            with _LOCK:
                if self.db.conn.execute("SELECT 1 FROM credit_entries WHERE ext_ref=?", (f"release:{hid}",)).fetchone():
                    continue
                self.db.conn.execute("BEGIN IMMEDIATE")
                try:
                    self._insert(workspace_id=r["workspace_id"], kind="release", amount_cc=-r["amount_cc"], hold_id=hid,
                                 production_id=pid, attempt_id=att["id"], stage=r["stage"], ext_ref=f"release:{hid}",
                                 note="" if charge else "recusado sem custo")
                    if charge:
                        self._insert(workspace_id=r["workspace_id"], kind="debit", amount_cc=-charge, usd=usd, hold_id=hid,
                                     production_id=pid, attempt_id=att["id"], stage=r["stage"], ext_ref=f"debit:{hid}",
                                     note=f"{att['kind']} #{att['attempt_no']}")
                    self.db.conn.execute("COMMIT")
                except BaseException:
                    self.db.conn.execute("ROLLBACK")
                    raise
            closed += 1
        return closed


def _title(product_json: str | None) -> str:
    if not product_json:
        return ""
    import json
    try:
        return (json.loads(product_json).get("name") or "")[:80]
    except ValueError:
        return ""
