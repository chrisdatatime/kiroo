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
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from .db import Database, new_id, now

ORPHAN_MINUTES = 15
# Serializa threads que compartilham UMA conexão (o orquestrador usa uma só); entre conexões/processos quem garante a
# exclusão é o BEGIN IMMEDIATE do SQLite (lock de escrita do arquivo), que é o que protege o saldo de verdade.
_LOCK = threading.RLock()

# O schema vive em migrations.py (PRAGMA user_version).

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

    @contextmanager
    def _txn(self):
        """Transação de escrita com lock do SQLite (BEGIN IMMEDIATE): leitura do saldo + lançamento viram atômicos,
        mesmo entre conexões e processos diferentes. Espera o lock até o busy_timeout da conexão. Se o chamador já
        abriu uma transação, participa dela."""
        with _LOCK:
            if self.db.conn.in_transaction:
                yield
                return
            self.db.conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.db.conn.execute("ROLLBACK")
                raise
            self.db.conn.execute("COMMIT")

    # ------------------------------------------------------------- leitura
    def balance(self, wid: str) -> int:
        return self.db.conn.execute("SELECT COALESCE(SUM(amount_cc),0) FROM credit_entries WHERE workspace_id=?",
                                    (wid,)).fetchone()[0]

    def held(self, wid: str) -> int:
        """Reservas ainda abertas (positivo). No pré-orçamento, o que já virou uso (drawdown) sai da reserva."""
        return self.db.conn.execute(
            "SELECT COALESCE(-SUM(r.amount_cc),0) FROM credit_entries r WHERE r.workspace_id=?"
            " AND r.kind IN ('reserve','drawdown')"
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
        with self._txn():
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
        with self._txn():   # saldo lido e reserva gravada sob o mesmo lock: o saldo nunca fica negativo
            bal = self.balance(wid)
            if not self.exempt(wid) and bal < cc:
                raise InsufficientCredits(bal, cc)
            self._insert(workspace_id=wid, kind="reserve", amount_cc=-cc, usd=usd, hold_id=hid, production_id=pid,
                         stage=stage, ext_ref=f"reserve:{hid}")
        return hid

    def attach(self, hid: str | None, attempt_id: str) -> None:
        if hid:
            self.db.conn.execute("UPDATE credit_entries SET attempt_id=? WHERE hold_id=? AND kind='reserve'", (attempt_id, hid))

    def release(self, hid: str | None, note: str = "") -> None:
        """Devolve a reserva sem cobrar (chamada não aconteceu ou foi recusada sem custo)."""
        if not hid:
            return
        with self._txn():
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
        with self._txn():   # liberação e débito juntos: nunca fica só um dos dois
            r = self.db.conn.execute("SELECT * FROM credit_entries WHERE hold_id=? AND kind='reserve'", (hid,)).fetchone()
            self.release(hid, note)
            charge = to_cc(usd)
            if r is not None and charge:
                self._insert(workspace_id=r["workspace_id"], kind="debit", amount_cc=-charge, usd=usd, hold_id=hid, production_id=None,
                             stage=r["stage"], ext_ref=f"debit:{hid}", note=note[:300])

    def settle(self, pid: str) -> int:
        """Fecha as reservas cujas tentativas terminaram. Idempotente; devolve quantas fechou."""
        open_holds = self.db.conn.execute(
            "SELECT r.* FROM credit_entries r WHERE r.production_id=? AND r.kind='reserve'"
            " AND COALESCE(r.stage,'')<>'prebudget'"   # o pré-orçamento tem acerto próprio (settle_pool/close_pool)
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
            usd = attempt_cost_usd(att)
            charge = 0 if att["status"] == "failed" else to_cc(usd)   # falha técnica: estorna, não cobra
            with self._txn():
                if self.db.conn.execute("SELECT 1 FROM credit_entries WHERE ext_ref=?", (f"release:{hid}",)).fetchone():
                    continue
                self._insert(workspace_id=r["workspace_id"], kind="release", amount_cc=-r["amount_cc"], hold_id=hid,
                             production_id=pid, attempt_id=att["id"], stage=r["stage"], ext_ref=f"release:{hid}",
                             note="" if charge else ("falha técnica: sem custo" if att["status"] == "failed"
                                                     else "recusado sem custo"))
                if charge:
                    self._insert(workspace_id=r["workspace_id"], kind="debit", amount_cc=-charge, usd=usd, hold_id=hid,
                                 production_id=pid, attempt_id=att["id"], stage=r["stage"], ext_ref=f"debit:{hid}",
                                 note=f"{att['kind']} #{att['attempt_no']}")
            closed += 1
        return closed

    # ------------------------------------------------- pré-orçamento da produção (saldo do cliente)
    @staticmethod
    def pool_id(pid: str) -> str:
        return f"pool_{pid}"

    def can_reserve(self, wid: str, cc: int) -> None:
        """Checagem antecipada (antes de receber fotos/criar a produção). Sem saldo → InsufficientCredits."""
        bal = self.balance(wid)
        if cc > 0 and not self.exempt(wid) and bal < cc:
            raise InsufficientCredits(bal, cc)

    def reserve_pool(self, wid: str, pid: str, cc: int, *, ref: str, usd: float | None = None, note: str = "") -> bool:
        """Reserva (parte do) pré-orçamento da produção. `ref` torna a reserva idempotente (base, extra:N...).
        Devolve False se a mesma reserva já existia. Sem saldo → InsufficientCredits (nada é reservado)."""
        if cc <= 0:
            return False
        hid = self.pool_id(pid)
        with self._txn():
            if self.db.conn.execute("SELECT 1 FROM credit_entries WHERE ext_ref=?", (f"pool:{pid}:{ref}",)).fetchone():
                return False
            if self.db.conn.execute("SELECT 1 FROM credit_entries WHERE ext_ref=?", (f"release:{hid}",)).fetchone():
                raise ValueError("o pré-orçamento desta produção já foi encerrado")
            bal = self.balance(wid)
            if not self.exempt(wid) and bal < cc:
                raise InsufficientCredits(bal, cc)
            self._insert(workspace_id=wid, kind="reserve", amount_cc=-int(cc), usd=usd, hold_id=hid, production_id=pid,
                         stage="prebudget", ext_ref=f"pool:{pid}:{ref}", note=note[:300])
        return True

    def pool_state(self, pid: str) -> dict:
        hid = self.pool_id(pid)
        rows = self.db.conn.execute("SELECT kind, amount_cc FROM credit_entries WHERE hold_id=?", (hid,)).fetchall()
        reserved = sum(-r["amount_cc"] for r in rows if r["kind"] == "reserve")
        drawn = sum(r["amount_cc"] for r in rows if r["kind"] == "drawdown")
        closed = any(r["kind"] == "release" for r in rows)
        return {"reserved_cc": reserved, "used_cc": drawn, "remaining_cc": max(reserved - drawn, 0), "closed": closed}

    def settle_pool(self, pid: str, wid: str) -> int:
        """Acerta com o cliente cada tentativa terminada da produção (uma decisão por tentativa, idempotente):
        sucesso → uso tirado do pré-orçamento (até o que foi reservado; acima disso o Kiroo absorve);
        falha técnica (erro do provedor, tempo esgotado) → nada sai do pré-orçamento."""
        rows = self.db.conn.execute(
            "SELECT * FROM attempts a WHERE a.production_id=? AND a.status IN ('succeeded','failed')"
            " AND NOT EXISTS (SELECT 1 FROM production_charges c WHERE c.attempt_id=a.id) ORDER BY a.created_at, a.rowid",
            (pid,)).fetchall()
        done = 0
        for att in rows:
            usd = attempt_cost_usd(att)
            with self._txn():
                if self.db.conn.execute("SELECT 1 FROM production_charges WHERE attempt_id=?", (att["id"],)).fetchone():
                    continue
                state = self.pool_state(pid)
                if att["status"] == "failed":
                    decision, charge = "technical_failure", 0
                else:
                    cost = to_cc(usd)
                    charge = 0 if state["closed"] else min(cost, state["remaining_cc"])
                    decision = "charged" if charge == cost else "absorbed"   # absorbed: o Kiroo paga a diferença
                if charge > 0:
                    hid = self.pool_id(pid)
                    self._insert(workspace_id=wid, kind="drawdown", amount_cc=charge, hold_id=hid, production_id=pid,
                                 attempt_id=att["id"], stage=att["kind"], ext_ref=f"draw:{att['id']}")
                    self._insert(workspace_id=wid, kind="debit", amount_cc=-charge, usd=usd, hold_id=hid,
                                 production_id=pid, attempt_id=att["id"], stage=att["kind"], ext_ref=f"debit:{att['id']}",
                                 note=f"{att['kind']} #{att['attempt_no']}")
                self.db.conn.execute(
                    "INSERT INTO production_charges(attempt_id, production_id, workspace_id, scene_idx, operation, provider,"
                    " model, cost_usd, charged_cc, decision, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (att["id"], pid, wid, att["scene_idx"], att["kind"], att["provider"], att["model"], usd, charge,
                     decision, now()))
            done += 1
        return done

    def close_pool(self, pid: str, note: str = "produção encerrada: devolve o que sobrou do pré-orçamento") -> int:
        """Devolve ao saldo o que não foi usado do pré-orçamento. Idempotente. Devolve os centésimos liberados."""
        hid = self.pool_id(pid)
        with self._txn():
            if self.db.conn.execute("SELECT 1 FROM credit_entries WHERE ext_ref=?", (f"release:{hid}",)).fetchone():
                return 0
            row = self.db.conn.execute("SELECT workspace_id FROM credit_entries WHERE hold_id=? AND kind='reserve'",
                                       (hid,)).fetchone()
            if row is None:
                return 0
            back = self.pool_state(pid)["remaining_cc"]
            self._insert(workspace_id=row["workspace_id"], kind="release", amount_cc=back, hold_id=hid, production_id=pid,
                         stage="prebudget", ext_ref=f"release:{hid}", note=note[:300])
        return back

    def charges(self, pid: str) -> list[dict]:
        """Registro por produção, cena, operação e provedor (o que custou ao Kiroo e o que saiu do cliente)."""
        return [dict(r) for r in self.db.conn.execute(
            "SELECT * FROM production_charges WHERE production_id=? ORDER BY created_at, rowid", (pid,))]


def attempt_cost_usd(att) -> float:
    """Mesma regra do orçamento: custo confirmado pelo provedor quando houver (e não simulado), senão o estimado."""
    if not att["simulated"] and att["confirmed_cost_usd"] is not None:
        return att["confirmed_cost_usd"]
    return att["estimated_cost_usd"] or 0.0


def _title(product_json: str | None) -> str:
    if not product_json:
        return ""
    import json
    try:
        return (json.loads(product_json).get("name") or "")[:80]
    except ValueError:
        return ""
