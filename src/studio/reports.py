"""Relatórios de revisão, tentativas/custos e histórico de execução."""

from __future__ import annotations

import json
import shutil

from .db import Database
from .states import PRODUCTION_LABELS, SCENE_LABELS, ProductionStatus, SceneStatus
from .storage import ProductionStorage


def cost_summary(db: Database, pid: str) -> dict:
    rows = db.attempts(pid)
    estimated = sum(r["estimated_cost_usd"] or 0 for r in rows)
    confirmed = sum(r["confirmed_cost_usd"] or 0 for r in rows if r["confirmed_cost_usd"] is not None and not r["simulated"])
    unconfirmed = sum(r["estimated_cost_usd"] or 0 for r in rows if r["confirmed_cost_usd"] is None and not r["simulated"])
    simulated_equiv = sum(r["estimated_cost_usd"] or 0 for r in rows if r["simulated"])
    budget = db.production(pid)["budget_usd"]
    return {
        "budget_usd": budget,
        "estimated_total_usd": round(estimated, 4),
        "confirmed_real_usd": round(confirmed, 4),
        "real_unconfirmed_estimate_usd": round(unconfirmed, 4),
        "simulated_equivalent_usd": round(simulated_equiv, 4),
        "attempts": len(rows),
    }


def _presentation_label(prod) -> str:
    from .creative_options import PRESENTATIONS, presentation_of_format
    pres = (json.loads(prod["product_json"]).get("creative") or {}).get("presentation")
    if pres is None and "direction_required" in prod.keys() and prod["direction_required"]:
        return "a definir na Direção (formato provisório)"
    pres = pres if pres in PRESENTATIONS else presentation_of_format(prod["format_id"])
    return PRESENTATIONS[pres]["label"] if pres else "—"


def write_reports(db: Database, pid: str, st: ProductionStorage) -> None:
    prod = db.production(pid)
    simulated = prod["mode"] == "simulated"
    banner = ("> **MODO SIMULADO** — imagens e vídeos são placeholders; isto NÃO comprova integração real "
              "nem qualidade visual.\n\n" if simulated else "")

    # ---------------------------------------------------------- custos
    attempts = db.attempts(pid)
    summary = cost_summary(db, pid)
    cost_rows = []
    for a in attempts:
        dur = None
        if a["submitted_at"] and a["finished_at"]:
            from datetime import datetime
            dur = (datetime.fromisoformat(a["finished_at"]) - datetime.fromisoformat(a["submitted_at"])).total_seconds()
        cost_rows.append({
            "attempt_id": a["id"], "scene": a["scene_idx"], "kind": a["kind"], "attempt_no": a["attempt_no"],
            "status": a["status"], "superseded": bool(a["superseded"]), "provider": a["provider"], "model": a["model"],
            "simulated": bool(a["simulated"]), "remote_op_id": a["remote_op_id"], "output": a["output_path"],
            "transient_retries": a["transient_retries"], "error": a["error"], "duration_s": dur,
            "estimated_cost_usd": a["estimated_cost_usd"], "confirmed_cost_usd": a["confirmed_cost_usd"],
            "pricing_source": a["pricing_source"], "created_at": a["created_at"],
        })
    st.write_json("reports/cost_report.json", {"production_id": pid, "summary": summary, "attempts": cost_rows})
    lines = [banner + f"# Tentativas e custos — {pid}", "",
             f"- Orçamento: US${summary['budget_usd']:.2f}",
             f"- Custo real confirmado: US${summary['confirmed_real_usd']:.4f}",
             f"- Custo real ainda não confirmado (estimativa): US${summary['real_unconfirmed_estimate_usd']:.4f}",
             f"- Equivalente estimado de chamadas simuladas (não gasto): US${summary['simulated_equivalent_usd']:.4f}", "",
             "| cena | etapa | # | status | provedor/modelo | estimado | confirmado | duração | fonte |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in cost_rows:
        status = r["status"] + (" (substituída)" if r["superseded"] else "")
        conf = "—" if r["confirmed_cost_usd"] is None else f"{r['confirmed_cost_usd']:.4f}"
        dur = "—" if r["duration_s"] is None else f"{r['duration_s']:.0f}s"
        lines.append(f"| {r['scene'] or '-'} | {r['kind']} | {r['attempt_no']} | {status} | {r['provider']}/{r['model']} "
                     f"| {r['estimated_cost_usd']:.4f} | {conf} | {dur} | {r['pricing_source'] or ''} |")
    st.write_text("reports/cost_report.md", "\n".join(lines) + "\n")

    # --------------------------------------------------------- revisões
    lines = [banner + f"# Relatório de revisão — {pid}", "",
             f"Estado: **{PRODUCTION_LABELS[ProductionStatus(prod['status'])]}**",
             f"Apresentação: **{_presentation_label(prod)}** · formato: `{prod['format_id']}`", "",
             "Avaliações automáticas são auxiliares e podem errar; a aprovação de qualidade é do operador.", ""]
    for scene in db.scenes(pid):
        lines += [f"## Cena {scene['idx']} — {SCENE_LABELS[SceneStatus(scene['status'])]}", ""]
        for rev in db.reviews(pid, scene["idx"]):
            res = json.loads(rev["result_json"])
            att = db.attempt(rev["attempt_id"]) if rev["attempt_id"] else None
            label = f"{rev['stage']} #{att['attempt_no']}" if att else rev["stage"]
            lines.append(f"- **{label}** — {rev['reviewer']}: `{rev['decision']}` ({rev['created_at']})")
            for issue in res.get("issues", []):
                lines.append(f"  - problema: {issue}")
            if res.get("suggested_fix"):
                lines.append(f"  - correção sugerida: {res['suggested_fix']}")
            if res.get("checks"):
                lines.append("  - checagens: " + ", ".join(f"{k}={v}" for k, v in res["checks"].items()))
            if res.get("method"):
                lines.append(f"  - método: {res['method']}")
            if res.get("note"):
                lines.append(f"  - nota: {res['note']}")
        lines.append("")
    finals = [r for r in db.reviews(pid) if r["stage"] == "final"]
    if finals:
        lines += ["## Revisão final", ""] + [f"- {r['reviewer']}: `{r['decision']}` — {json.loads(r['result_json']).get('note', '')}" for r in finals]
    warnings = [e for e in db.events(pid) if e["type"] in {"delivery_warning", "sheet_issue"}]
    if warnings:
        lines += ["", "## Alertas", ""] + [f"- {e['message']}" for e in warnings]
    st.write_text("reports/review_report.md", "\n".join(lines) + "\n")

    # -------------------------------------------------------- histórico
    lines = [f"# Histórico de execução — {pid}", "", "| quando (UTC) | cena | evento | de → para | mensagem |", "|---|---|---|---|---|"]
    for e in db.events(pid):
        trans = f"{e['from_state'] or ''} → {e['to_state'] or ''}" if (e["from_state"] or e["to_state"]) else ""
        msg = (e["message"] or "").replace("|", "/").replace("\n", " ")
        lines.append(f"| {e['ts']} | {e['scene_idx'] or ''} | {e['type']} | {trans} | {msg} |")
    st.write_text("reports/execution_log.md", "\n".join(lines) + "\n")

    delivery = st.path("delivery")
    if delivery.exists():
        for name in ("cost_report.md", "cost_report.json", "review_report.md", "execution_log.md"):
            shutil.copy2(st.path("reports", name), delivery / name)
        for name in ("script.md", "script.json", "sheet.json"):
            if st.path(name).exists():
                shutil.copy2(st.path(name), delivery / name)
