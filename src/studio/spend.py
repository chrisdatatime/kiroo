"""Monitoramento de gastos (todas as produções).

Gasto real = tentativas não simuladas: custo confirmado quando houver, senão a
estimativa pela tabela de preços (a Gemini API não devolve custo por chamada).
Simulações aparecem à parte, como "equivalente estimado", e nunca somam ao real.
Datas no fuso local da máquina.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from .db import Database

KIND_LABELS = {"image": "Imagens", "video": "Vídeos", "review_image": "Revisão de imagem",
               "review_video": "Revisão de vídeo", "plan": "Roteiro (IA)", "workflow": "Pacote de vídeo e fotos"}


def _local(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone()


def _value(row) -> float:
    return row["confirmed_cost_usd"] if row["confirmed_cost_usd"] is not None else (row["estimated_cost_usd"] or 0.0)


def _attempts(db: Database, workspace_id: str | None, where: str = ""):
    if workspace_id is None:
        return db.conn.execute(f"SELECT * FROM attempts {('WHERE ' + where) if where else ''} ORDER BY created_at").fetchall()
    cond = "a.production_id IN (SELECT id FROM productions WHERE workspace_id=?)" + (f" AND {where}" if where else "")
    return db.conn.execute(f"SELECT * FROM attempts a WHERE {cond} ORDER BY created_at", (workspace_id,)).fetchall()


def month_real_spend(db: Database, month: str | None = None, workspace_id: str | None = None) -> float:
    month = month or datetime.now().astimezone().strftime("%Y-%m")
    total = 0.0
    for r in _attempts(db, workspace_id, "simulated=0"):
        if _local(r["created_at"]).strftime("%Y-%m") == month:
            total += _value(r)
    if workspace_id and db.conn.execute("SELECT 1 FROM sqlite_master WHERE name='training_tests'").fetchone():
        total += float(db.conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM training_tests WHERE workspace_id=? AND simulated=0 AND substr(created_at, 1, 7)=?",
                                       (workspace_id, month)).fetchone()[0])
    return round(total, 4)


def spend_report(db: Database, monthly_cap_usd: float, days: int = 30, workspace_id: str | None = None) -> dict:
    now = datetime.now().astimezone()
    month = now.strftime("%Y-%m")
    names = {r["id"]: r for r in db.conn.execute("SELECT id, product_json, mode, status, budget_usd FROM productions")}
    rows = _attempts(db, workspace_id)

    real = [r for r in rows if not r["simulated"]]
    sim = [r for r in rows if r["simulated"]]
    month_rows = [r for r in real if _local(r["created_at"]).strftime("%Y-%m") == month]
    month_confirmed = sum(r["confirmed_cost_usd"] for r in month_rows if r["confirmed_cost_usd"] is not None)
    month_estimated = sum(r["estimated_cost_usd"] or 0 for r in month_rows if r["confirmed_cost_usd"] is None)
    month_total = month_confirmed + month_estimated

    start = (now - timedelta(days=days - 1)).date()
    daily = defaultdict(float)
    for r in real:
        d = _local(r["created_at"]).date()
        if d >= start:
            daily[d] += _value(r)
    series = [{"day": (start + timedelta(days=i)).isoformat(), "usd": round(daily[start + timedelta(days=i)], 4)}
              for i in range(days)]

    by_kind = defaultdict(lambda: {"usd": 0.0, "count": 0, "failed": 0})
    by_model = defaultdict(lambda: {"usd": 0.0, "count": 0})
    by_prod = defaultdict(lambda: {"usd": 0.0, "count": 0})
    for r in real:
        k = by_kind[r["kind"]]
        k["usd"] += _value(r)
        k["count"] += 1
        k["failed"] += r["status"] == "failed"
        by_model[r["model"]]["usd"] += _value(r)
        by_model[r["model"]]["count"] += 1
        by_prod[r["production_id"]]["usd"] += _value(r)
        by_prod[r["production_id"]]["count"] += 1

    import json
    productions = []
    for pid, agg in sorted(by_prod.items(), key=lambda kv: -kv[1]["usd"]):
        p = names.get(pid)
        productions.append({"id": pid, "name": json.loads(p["product_json"]).get("name", "") if p else pid,
                            "status": p["status"] if p else "", "budget_usd": p["budget_usd"] if p else None,
                            "usd": round(agg["usd"], 4), "count": agg["count"]})
    recent = [{"ts": r["created_at"], "production_id": r["production_id"], "scene": r["scene_idx"],
               "kind": KIND_LABELS.get(r["kind"], r["kind"]), "model": r["model"], "status": r["status"],
               "estimated_usd": r["estimated_cost_usd"], "confirmed_usd": r["confirmed_cost_usd"],
               "source": r["pricing_source"]} for r in reversed(real[-25:])]
    return {
        "month": month,
        "monthly_cap_usd": monthly_cap_usd,
        "month_total_usd": round(month_total, 4),
        "month_confirmed_usd": round(month_confirmed, 4),
        "month_unconfirmed_estimate_usd": round(month_estimated, 4),
        "month_remaining_usd": round(max(monthly_cap_usd - month_total, 0), 4) if monthly_cap_usd else None,
        "all_time_real_usd": round(sum(_value(r) for r in real), 4),
        "simulated_equivalent_usd": round(sum(r["estimated_cost_usd"] or 0 for r in sim), 4),
        "daily": series,
        "by_kind": [{"kind": KIND_LABELS.get(k, k), "usd": round(v["usd"], 4), "count": v["count"],
                     "failed": v["failed"]} for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1]["usd"])],
        "by_model": [{"model": k, "usd": round(v["usd"], 4), "count": v["count"]}
                     for k, v in sorted(by_model.items(), key=lambda kv: -kv[1]["usd"])],
        "by_production": productions,
        "recent": recent,
        "note": "A Gemini API não informa o custo final de cada chamada: valores reais são estimativas pela tabela "
                "de preços (consultada em 26/10/2026) até você conferir na fatura do Google.",
    }


def _has_table(db: Database, name: str) -> bool:
    return bool(db.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def platform_month_spend(db: Database, month: str | None = None) -> float:
    """Gasto real do mês na plataforma inteira: gerações/revisões, testes de treinamento e conversa com IA."""
    now = datetime.now().astimezone()
    month = month or now.strftime("%Y-%m")
    total = sum(_value(r) for r in _attempts(db, None, "simulated=0") if _local(r["created_at"]).strftime("%Y-%m") == month)
    if _has_table(db, "training_tests"):
        total += float(db.conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM training_tests WHERE simulated=0 AND "
                                       "substr(created_at, 1, 7)=?", (month,)).fetchone()[0])
    if _has_table(db, "chat_log"):
        start = datetime.strptime(month + "-01", "%Y-%m-%d").astimezone()
        end = (start + timedelta(days=32)).replace(day=1)
        total += float(db.conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM chat_log WHERE at>=? AND at<?",
                                       (start.timestamp(), end.timestamp())).fetchone()[0])
    return round(total, 6)


def agent_day_spend(db: Database, workspace_id: str | None, agent: str) -> float:
    """Gasto real de hoje (fuso local) de um agente: chamadas do orquestrador, testes de treinamento e conversa.
    Sem workspace (produções da CLI), conta as produções sem workspace."""
    from .paid_gate import KIND_AGENT

    kinds = [k for k, a in KIND_AGENT.items() if a == agent]
    today = datetime.now().astimezone().date()
    total = 0.0
    if kinds:
        marks = ",".join("?" * len(kinds))
        if workspace_id is None:
            rows = db.conn.execute(f"SELECT * FROM attempts WHERE simulated=0 AND kind IN ({marks}) AND production_id IN "
                                   "(SELECT id FROM productions WHERE workspace_id IS NULL)", kinds).fetchall()
        else:
            rows = db.conn.execute(f"SELECT * FROM attempts WHERE simulated=0 AND kind IN ({marks}) AND production_id IN "
                                   "(SELECT id FROM productions WHERE workspace_id=?)", (*kinds, workspace_id)).fetchall()
        total += sum(_value(r) for r in rows if _local(r["created_at"]).date() == today)
    day0 = datetime.combine(today, datetime.min.time()).astimezone()
    if workspace_id is not None and _has_table(db, "training_tests"):
        for r in db.conn.execute("SELECT cost_usd, created_at FROM training_tests WHERE simulated=0 AND workspace_id=? "
                                 "AND agent_id=?", (workspace_id, agent)):
            if _local(r["created_at"]).date() == today:
                total += r["cost_usd"] or 0.0
    if _has_table(db, "chat_log"):
        total += float(db.conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM chat_log WHERE agent=? AND at>=? AND "
                                       "workspace_id IS ?", (agent, day0.timestamp(), workspace_id)).fetchone()[0])
    return round(total, 6)
