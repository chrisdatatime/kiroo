"""Métricas internas do administrador (Parte A): só agregados, sem dados pessoais nem segredos.

Fonte: o que o estúdio já registra a cada chamada — `attempts` (operação, provedor, modelo, cena, custo estimado e
confirmado), `events` (`ops_alert` fica no histórico mesmo depois de a produção ser retomada), `chat_log` (custo da
conversa com os agentes) e `training_tests` (testes de treinamento). Nada aqui lê e-mail, nome, ficha do produto,
prompt, caminho de arquivo ou id de pessoa/estúdio; a saída tem só números, rótulos de operação e nomes de provedor.

Custo de cada tentativa = mesma regra do orçamento: confirmado pelo provedor quando houver (e não simulado), senão o
estimado. Real e simulado (DEMO) ficam em blocos separados e nunca se somam.

Expostas em `studio admin metrics` e em `GET /api/admin/metrics` (aba Administrador).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .db import Database

OPERATIONS = {"image": "Imagem", "video": "Vídeo", "review_image": "Conferência de imagem",
              "review_video": "Conferência de vídeo", "plan": "Roteiro (IA)", "chat": "Conversa com agentes",
              "training_test": "Teste de treinamento"}
SCENE_KINDS = ("image", "video")   # "tentativas por cena": gerações de imagem e de vídeo de uma cena
DELIVERED = "completed"
OPS_BUDGET_REACHED = "ops_budget_reached"   # mesmo código de budget.OPS_BUDGET_REACHED


def _since(days: int) -> str | None:
    if not days or days <= 0:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat(timespec="seconds")


def _cost(row) -> float:
    if not row["simulated"] and row["confirmed_cost_usd"] is not None:
        return float(row["confirmed_cost_usd"])
    return float(row["estimated_cost_usd"] or 0.0)


def _r(x: float, nd: int = 4) -> float:
    return round(float(x), nd)


def _avg(total: float, n: int, nd: int = 4) -> float | None:
    return _r(total / n, nd) if n else None


def _has(db: Database, table: str) -> bool:
    return bool(db.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _block(prods: list, attempts: list, interrupted: set[str]) -> dict:
    """Métricas de um modo (real ou simulado). `prods`: produções do período; `attempts`: tentativas delas."""
    cost_by_prod: dict[str, float] = defaultdict(float)
    by_op: dict[str, dict] = defaultdict(lambda: {"usd": 0.0, "calls": 0, "failed": 0})
    by_provider: dict[str, dict] = defaultdict(lambda: {"usd": 0.0, "calls": 0, "failed": 0})
    tries: dict[tuple, int] = defaultdict(int)
    tries_kind: dict[str, dict[tuple, int]] = {k: defaultdict(int) for k in SCENE_KINDS}
    for a in attempts:
        c = _cost(a)
        cost_by_prod[a["production_id"]] += c
        for bucket in (by_op[a["kind"]], by_provider[a["provider"] or "desconhecido"]):
            bucket["usd"] += c
            bucket["calls"] += 1
            bucket["failed"] += a["status"] == "failed"
        if a["kind"] in SCENE_KINDS and a["scene_idx"] is not None:
            key = (a["production_id"], a["scene_idx"])
            tries[key] += 1
            tries_kind[a["kind"]][key] += 1
    delivered = [p["id"] for p in prods if p["status"] == DELIVERED]
    delivered_cost = sum(cost_by_prod[pid] for pid in delivered)
    n_int = sum(1 for p in prods if p["id"] in interrupted)
    return {
        "productions": len(prods),
        "delivered": len(delivered),
        "avg_cost_per_delivered_usd": _avg(delivered_cost, len(delivered)),
        "delivered_cost_usd": _r(delivered_cost),
        "interrupted_by_ops_budget": n_int,
        "interrupted_by_ops_budget_pct": _avg(n_int * 100.0, len(prods), 1),
        "avg_attempts_per_scene": _avg(sum(tries.values()), len(tries), 2),
        "avg_attempts_per_scene_by_kind": {OPERATIONS[k]: _avg(sum(v.values()), len(v), 2) for k, v in tries_kind.items()},
        "scenes_with_attempts": len(tries),
        "by_operation": _rows(by_op, label=lambda k: OPERATIONS.get(k, k)),
        "by_provider": _rows(by_provider, label=lambda k: k),
        "total_usd": _r(sum(cost_by_prod.values())),
    }


def _rows(d: dict, *, label) -> list[dict]:
    out = [{"key": k, "label": label(k), "usd": _r(v["usd"]), "calls": v["calls"], "failed": v["failed"],
            "avg_usd": _avg(v["usd"], v["calls"])} for k, v in d.items()]
    return sorted(out, key=lambda r: (-r["usd"], r["key"]))


def internal_metrics(db: Database, days: int = 30) -> dict:
    """Agregados do período (`days` dias até agora; 0 = desde o início). Produções entram pelo `created_at`."""
    since = _since(days)
    where, args = ("WHERE created_at >= ?", (since,)) if since else ("", ())
    prods = db.conn.execute(f"SELECT id, mode, status FROM productions {where}", args).fetchall()
    attempts = db.conn.execute(   # todas as tentativas das produções do período (mesmo as feitas depois do corte)
        "SELECT production_id, scene_idx, kind, status, provider, simulated, estimated_cost_usd, confirmed_cost_usd "
        f"FROM attempts WHERE production_id IN (SELECT id FROM productions {where})", args).fetchall()
    interrupted = {r[0] for r in db.conn.execute(
        "SELECT DISTINCT production_id FROM events WHERE type='ops_alert' AND (data_json LIKE ? OR message LIKE ?)",
        (f'%"{OPS_BUDGET_REACHED}"%', f"{OPS_BUDGET_REACHED}%")).fetchall()}
    mode_of = {p["id"]: p["mode"] for p in prods}
    out: dict = {"days": int(days or 0), "since": since, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    for mode in ("real", "simulated"):
        out[mode] = _block([p for p in prods if p["mode"] == mode],
                           [a for a in attempts if mode_of.get(a["production_id"]) == mode], interrupted)

    # fora das produções: conversa com os agentes (Anthropic) e testes de treinamento
    extra: dict[str, dict] = {}
    if _has(db, "chat_log"):
        cw, ca = ("WHERE source='llm' AND at >= ?", (datetime.fromisoformat(since).timestamp(),)) if since else ("WHERE source='llm'", ())
        rows = db.conn.execute(f"SELECT COALESCE(NULLIF(provider,''),'anthropic') p, COUNT(*) n, COALESCE(SUM(cost_usd),0) usd "
                               f"FROM chat_log {cw} GROUP BY p ORDER BY p", ca).fetchall()
        for r in rows or [{"p": "gemini", "n": 0, "usd": 0}]:
            extra["chat" if len(rows) <= 1 else f"chat:{r['p']}"] = {"provider": r["p"], "calls": r["n"], "usd": _r(r["usd"])}
    if _has(db, "training_tests"):
        tw = "WHERE executed=1 AND simulated=0" + (" AND created_at >= ?" if since else "")
        r = db.conn.execute(f"SELECT COUNT(*) n, COALESCE(SUM(cost_usd),0) usd FROM training_tests {tw}",
                            (since,) if since else ()).fetchone()
        extra["training_test"] = {"provider": "não registrado", "calls": r["n"], "usd": _r(r["usd"])}
    out["outside_productions"] = [{"key": k, "label": OPERATIONS.get(k.split(":")[0], k) if k.startswith("chat") else OPERATIONS[k], **v, "avg_usd": _avg(v["usd"], v["calls"])}
                                  for k, v in extra.items()]
    return out


def format_text(m: dict) -> str:
    """Texto para `studio admin metrics` (o mesmo conteúdo do JSON)."""
    def usd(x):
        return "—" if x is None else f"US${x:.4f}"
    lines = [f"Métricas internas — {'últimos ' + str(m['days']) + ' dias' if m['days'] else 'desde o início'} "
             f"(gerado {m['generated_at']} UTC)"]
    for mode, title in (("real", "REAL"), ("simulated", "SIMULADO (DEMO, custo equivalente estimado)")):
        b = m[mode]
        lines += ["", f"[{title}]",
                  f"  produções: {b['productions']} | entregues: {b['delivered']} | custo médio por vídeo entregue: "
                  f"{usd(b['avg_cost_per_delivered_usd'])}",
                  f"  interrompidas por orçamento operacional: {b['interrupted_by_ops_budget']} "
                  f"({'—' if b['interrupted_by_ops_budget_pct'] is None else str(b['interrupted_by_ops_budget_pct']) + '%'})",
                  f"  tentativas médias por cena: {b['avg_attempts_per_scene'] if b['avg_attempts_per_scene'] is not None else '—'}"
                  + "".join(f" | {k}: {v if v is not None else '—'}" for k, v in b["avg_attempts_per_scene_by_kind"].items()),
                  "  custo por operação:"]
        lines += [f"    {r['label']:26} {r['calls']:5} chamadas  {usd(r['usd'])}  (média {usd(r['avg_usd'])}, falhas {r['failed']})"
                  for r in b["by_operation"]] or ["    (nada)"]
        lines.append("  custo por provedor:")
        lines += [f"    {r['label']:26} {r['calls']:5} chamadas  {usd(r['usd'])}  (média {usd(r['avg_usd'])})"
                  for r in b["by_provider"]] or ["    (nada)"]
    lines += ["", "[fora das produções]"]
    lines += [f"  {r['label']:26} {r['provider']:15} {r['calls']:5} chamadas  {usd(r['usd'])}" for r in m["outside_productions"]] or ["  (nada)"]
    return "\n".join(lines)
