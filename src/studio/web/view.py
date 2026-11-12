"""Monta o estado exibido no escritório: o que cada agente está fazendo, a partir do banco.

Nada aqui é encenado: status e falas vêm dos estados das cenas, das tentativas e dos
eventos persistidos pelo orquestrador.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import quote

from ..agent_config import agents_with_overrides, field_options
from ..config import Settings
from ..db import Database
from ..reports import cost_summary
from ..spend import month_real_spend
from ..states import PRODUCTION_LABELS, SCENE_LABELS, ProductionStatus as PS, SceneStatus as SS

_STATUS_TO_AGENT = {
    PS.RECEIVED: "orchestrator", PS.VALIDATED: "prep", PS.AWAITING_REFERENCES: "prep", PS.SCRIPTED: "creative",
    PS.PRODUCING: "orchestrator", PS.EDITING: "editor", PS.AWAITING_FINAL_REVIEW: "editor",
    PS.COMPLETED: "operator", PS.PAUSED: "orchestrator", PS.FAILED: "orchestrator", PS.CANCELLED: "operator",
}
_SCENE_TO_AGENT = {
    SS.PENDING: "orchestrator", SS.GENERATING_IMAGE: "images", SS.AWAITING_IMAGE_APPROVAL: "review",
    SS.IMAGE_APPROVED: "operator", SS.GENERATING_VIDEO: "videos", SS.AWAITING_VIDEO_APPROVAL: "review",
    SS.VIDEO_APPROVED: "operator", SS.BLOCKED: "orchestrator",
}


def event_agent(e) -> str:
    t, msg = e["type"], (e["message"] or "")
    if t.startswith("attempt_") or t == "transient_error":
        first = msg.split(" ", 1)[0].rstrip(":")
        if first in ("image", "video"):
            return "images" if first == "image" else "videos"
        if first == "plan":
            return "creative"
        if first.startswith("review"):
            return "review"
        return "orchestrator"
    if t == "review":
        return "operator" if " human:" in msg or "demo-auto" in msg else "review"
    if t == "auto_correction":
        return "review"
    if t in ("sheet_issue", "product_updated"):
        return "prep"
    if t in ("planner_failed", "script_rejected", "prompt_edited"):
        return "creative"
    if t == "delivery_warning":
        return "editor"
    if t == "production_status" and e["to_state"]:
        return _STATUS_TO_AGENT.get(PS(e["to_state"]), "orchestrator")
    if t == "scene_status" and e["to_state"]:
        return _SCENE_TO_AGENT.get(SS(e["to_state"]), "orchestrator")
    return "orchestrator"


def _edit_styles(settings) -> dict:
    from ..agents import editing, sound
    return {"styles": [{"id": k, "label": v["label"], "hint": v["hint"], "music": v["music"]}
                       for k, v in editing.EDIT_STYLES.items()],
            "music": [{k: t.get(k) for k in ("id", "title", "bpm", "mood", "license", "builtin")}
                      for t in sound.library(settings.assets_dir)]}


def _credit_policy() -> dict:
    from .. import billing
    pol = billing.policy()
    return {"fx": pol.fx_brl_per_usd, "margin": pol.margin, "price_brl": pol.credit_price_brl, "provisional": pol.provisional,
            "describe": pol.describe()}


def _age_s(ts: str) -> float:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()


def _media(pid: str, rel: str | None) -> str | None:
    return f"/media/{pid}/{quote(rel)}" if rel else None


_KIND_PT = {"image": "imagem", "video": "vídeo", "plan": "roteiro", "review_image": "revisão da imagem",
            "review_video": "revisão do vídeo"}


def say(e) -> str:
    """Fala curta e legível para o balão do agente."""
    t, msg, scene = e["type"], e["message"] or "", e["scene_idx"]
    prefix = f"Cena {scene}: " if scene else ""
    head = msg.split(" ", 2)
    kind = _KIND_PT.get(head[0].rstrip(":"), head[0]) if head else ""
    num = head[1] if len(head) > 1 and head[1].startswith("#") else ""
    if t == "attempt_created":
        return f"{prefix}preparando {kind} {num}".strip()
    if t == "attempt_submitted":
        return f"{prefix}{kind} {num} enviado(a) ao provedor".strip()
    if t == "attempt_succeeded":
        return f"{prefix}{kind} {num} pronto(a)".strip()
    if t == "attempt_failed":
        return f"{prefix}{kind} {num} falhou".strip()
    if t == "attempt_reused":
        return f"{prefix}reaproveitei um resultado idêntico já pago"
    if t == "scene_status" and e["to_state"]:
        return prefix + SCENE_LABELS[SS(e["to_state"])].lower()
    if t == "production_status" and e["to_state"]:
        return PRODUCTION_LABELS[PS(e["to_state"])] + (f": {msg}" if msg else "")
    return prefix + msg


def _event_json(e) -> dict:
    return {"id": e["id"], "ts": e["ts"], "scene": e["scene_idx"], "type": e["type"], "agent": event_agent(e),
            "from": e["from_state"], "to": e["to_state"], "message": e["message"] or "", "say": say(e)}


def _attempt_json(pid: str, db: Database, att_id: str | None) -> dict | None:
    if not att_id:
        return None
    a = db.attempt(att_id)
    reviews = []
    for r in db.reviews_for_attempt(att_id):
        res = json.loads(r["result_json"])
        reviews.append({"reviewer": r["reviewer"], "decision": r["decision"], "issues": res.get("issues", []),
                        "suggested_fix": res.get("suggested_fix"), "checks": res.get("checks", {}),
                        "method": res.get("method", ""), "note": res.get("note", "")})
    return {"id": a["id"], "no": a["attempt_no"], "status": a["status"], "simulated": bool(a["simulated"]),
            "model": a["model"], "url": _media(pid, a["output_path"]), "error": a["error"],
            "estimated_cost_usd": a["estimated_cost_usd"], "remote_op_id": a["remote_op_id"], "reviews": reviews}


def _agent_states(db: Database, pid: str | None, running: bool, error: str | None, events: list[dict]) -> dict:
    states = {a: {"status": "idle", "message": "", "since": None} for a in
              ("orchestrator", "prep", "creative", "images", "review", "videos", "editor", "operator")}
    for e in events:  # última fala de cada agente
        states[e["agent"]]["message"] = e["say"]
        states[e["agent"]]["since"] = e["ts"]
    if pid is None:
        for s in states.values():
            s["message"] = s["message"] or "Sem produção selecionada"
        return states

    prod = db.production(pid)
    status = PS(prod["status"])
    reason = prod["status_reason"] or ""

    def set_(agent, st, msg=None):
        states[agent]["status"] = st
        if msg:
            states[agent]["message"] = msg

    if running:
        set_("orchestrator", "working")
    if error:
        set_("orchestrator", "blocked", f"Erro na execução: {error}")
    if status == PS.PAUSED:
        set_("orchestrator", "blocked", reason)
        set_("operator", "needs_you", "Produção pausada: " + reason)
    elif status == PS.FAILED:
        set_("orchestrator", "blocked", reason)
    if status == PS.AWAITING_REFERENCES:
        set_("prep", "blocked", reason)
        set_("operator", "needs_you", "Faltam referências: corrija a ficha")
    elif status in (PS.RECEIVED,) and running:
        set_("prep", "working")
    if status == PS.VALIDATED and running:
        set_("creative", "working", "Escrevendo o roteiro por cena")
    if status == PS.EDITING:
        set_("editor", "working" if running else "idle", "Montando os takes aprovados com FFmpeg")
    if status == PS.AWAITING_FINAL_REVIEW:
        set_("editor", "done", "Pacote pronto: vídeo, capa, legenda e relatórios")
        set_("operator", "needs_you", "Revisão final do vídeo")
    if status == PS.COMPLETED:
        set_("operator", "done", "Produção concluída")

    pending = []
    for sc in db.scenes(pid):
        st = SS(sc["status"])
        kind = "image" if st in (SS.GENERATING_IMAGE, SS.AWAITING_IMAGE_APPROVAL) else "video"
        agent = "images" if kind == "image" else "videos"
        if st in (SS.GENERATING_IMAGE, SS.GENERATING_VIDEO):
            att_id = sc[f"current_{kind}_attempt"]
            att = db.attempt(att_id) if att_id else None
            if att and att["status"] == "submitted":
                set_(agent, "waiting_remote", f"Cena {sc['idx']}: aguardando o provedor (op {att['remote_op_id']})")
            elif att and att["next_retry_at"]:
                set_(agent, "waiting_remote", f"Cena {sc['idx']}: falha temporária, nova tentativa agendada")
            elif states[agent]["status"] == "idle":
                set_(agent, "working" if running else "idle", f"Cena {sc['idx']}: gerando {'imagem' if kind == 'image' else 'vídeo'}")
        elif st in (SS.AWAITING_IMAGE_APPROVAL, SS.AWAITING_VIDEO_APPROVAL):
            pending.append(f"{'imagem' if st == SS.AWAITING_IMAGE_APPROVAL else 'vídeo'} da cena {sc['idx']}")
        elif st == SS.BLOCKED:
            blocked_agent = "videos" if sc["approved_image_attempt"] else "images"
            set_(blocked_agent, "blocked", f"Cena {sc['idx']} bloqueada: tentativas esgotadas")
            pending.append(f"cena {sc['idx']} bloqueada")
    if pending:
        set_("operator", "needs_you", "Aguardando você: " + ", ".join(pending))
    for a, s in states.items():  # fala recente = trabalhando (revisão é instantânea)
        if s["status"] == "idle" and s["since"] and running and _age_s(s["since"]) < 4:
            s["status"] = "working"
    return states


def snapshot(settings: Settings, db: Database, pid: str | None, *, since: int = 0, running: bool = False,
             error: str | None = None, workspace_id: str | None = None) -> dict:
    productions = [{"id": r["id"], "mode": r["mode"], "status": r["status"],
                    "label": PRODUCTION_LABELS[PS(r["status"])],
                    "name": json.loads(r["product_json"]).get("name", ""), "created_at": r["created_at"]}
                   for r in db.productions(workspace_id)]
    if pid is None and productions:
        pid = productions[0]["id"]
    all_events = [_event_json(e) for e in db.events(pid)] if pid else []
    data = {
        "settings": {
            "mode": settings.mode, "allow_paid_calls": settings.allow_paid_calls,
            "api_key_defined": bool(settings.gemini_api_key), "ffmpeg": bool(settings.ffmpeg_bin),
            "monthly_cap_usd": settings.monthly_cap_usd, "month_spend_usd": month_real_spend(db, workspace_id=workspace_id),
            "credit_policy": _credit_policy(),
            "edit_styles": _edit_styles(settings),
            "values": {k: getattr(settings, k) for k in field_options()},
        },
        "field_options": field_options(),
        "agents": agents_with_overrides(settings.data_dir),
        "agent_states": _agent_states(db, pid, running, error, all_events),
        "productions": productions,
        "selected": pid,
        "events": [e for e in all_events if e["id"] > since][-200:],
        "last_event_id": all_events[-1]["id"] if all_events else 0,
        "production": None,
    }
    if not pid:
        return data
    p = db.production(pid)
    product = json.loads(p["product_json"])
    has_pool = "prebudget_cc" in p.keys() and p["prebudget_cc"] is not None
    if has_pool:
        from .. import budget as budget_mod
        from ..credits import Ledger, to_cc
        included = budget_mod.included_adjustments_per_scene()
        extra_cc = {st: to_cc(budget_mod.adjustment_cost_usd(settings, st)) for st in ("image", "video")}
    scenes = []
    for sc in db.scenes(pid):
        spec = json.loads(sc["spec_json"])
        adj = None
        if has_pool:   # ajustes do cliente: incluídos no pré-orçamento e custo (visível) de um extra
            used, auth = sc["adjustments_used"], sc["adjustments_authorized"]
            adj = {"included": included, "used": used, "authorized": auth, "free_left": max(included + auth - used, 0),
                   "extra_cost_cc": dict(extra_cc),
                   "extra_cost_credits": {k: -(-v // 100) for k, v in extra_cc.items()}}
        scenes.append({
            "idx": sc["idx"], "title": spec["title"], "status": sc["status"],
            "label": SCENE_LABELS[SS(sc["status"])], "motion": spec["motion"],
            "target_duration_s": spec["target_duration_s"], "criteria": spec["approval_criteria"],
            "image": _attempt_json(pid, db, sc["current_image_attempt"]),
            "video": _attempt_json(pid, db, sc["current_video_attempt"]),
            "approved_image": sc["approved_image_attempt"], "approved_video": sc["approved_video_attempt"],
            "image_attempts": db.count_generation_attempts(pid, sc["idx"], "image"),
            "video_attempts": db.count_generation_attempts(pid, sc["idx"], "video"),
            "adjustments": adj,
        })
    st = PS(p["status"])
    delivery = {}
    if st in (PS.AWAITING_FINAL_REVIEW, PS.COMPLETED):
        delivery = {name: f"/media/{pid}/delivery/{name}" for name in
                    ("final.mp4", "cover.jpg", "caption.txt", "product.json", "review_report.md", "cost_report.md",
                     "script.md")}
        if (settings.data_dir / "productions" / pid / "delivery" / "final_sem_musica.mp4").is_file():
            delivery["final_sem_musica.mp4"] = f"/media/{pid}/delivery/final_sem_musica.mp4"
    meta_file = settings.data_dir / "productions" / pid / "delivery" / "delivery_meta.json"
    edit_meta = {}
    if delivery and meta_file.is_file():
        try:
            m = json.loads(meta_file.read_text(encoding="utf-8"))
            edit_meta = {k: m.get(k) for k in ("edit_style", "transitions", "music", "sfx", "no_music_version")}
        except ValueError:
            pass
    costs = cost_summary(db, pid)
    committed = 0.0
    for a in db.attempts(pid):
        committed += (a["estimated_cost_usd"] or 0) if (a["simulated"] or a["confirmed_cost_usd"] is None) else a["confirmed_cost_usd"]
    sheet = json.loads(p["sheet_json"]) if p["sheet_json"] else None
    refs = (sheet or {}).get("product", product).get("references", [])
    from .. import billing
    pol = billing.policy()
    go_ahead = p["go_ahead"] if "go_ahead" in p.keys() else "all"
    sc_rows = db.scenes(pid)
    gate = None
    if st == PS.PRODUCING and go_ahead == "none" and sc_rows:
        gate = "images"
    elif st == PS.PRODUCING and go_ahead == "images" and sc_rows and all(r["approved_image_attempt"] for r in sc_rows)             and all(r["status"] in (SS.IMAGE_APPROVED, SS.PENDING) for r in sc_rows):
        gate = "videos"
    pool = Ledger(db).pool_state(pid) if has_pool else None
    caption_file = settings.data_dir / "productions" / pid / "delivery" / "caption.txt"
    data["production"] = {
        "go_ahead": go_ahead,
        "autonomy": p["autonomy"] if "autonomy" in p.keys() else "classico",
        "edit": {"style": p["edit_style"] if "edit_style" in p.keys() else "dinamico",
                 "music": p["music_id"] if "music_id" in p.keys() else "auto", "last": edit_meta,
                 "music_choice": json.loads(p["music_json"]) if "music_json" in p.keys() and p["music_json"] else None},
        "training_versions": ({a: e["version"] for a, e in json.loads(p["training_json"])["agents"].items()}
                              if "training_json" in p.keys() and p["training_json"] else None),
        "creative": product.get("creative"),
        "gate": gate,
        # Com pré-orçamento, o que o cliente vê é o SALDO dele: reservado para este vídeo e usado até agora.
        # O orçamento operacional (budget_usd) é interno e não aparece como "limite" para o cliente.
        "credits": ({"spent": -(-pool["used_cc"] // 100), "budget": -(-pool["reserved_cc"] // 100), "prebudget": True,
                     "policy": pol.describe()} if has_pool else
                    {"spent": pol.credits(committed), "budget": pol.credits(p["budget_usd"]), "prebudget": False,
                     "policy": pol.describe()}),
        "pause_code": p["pause_code"] if "pause_code" in p.keys() else None,
        # "Seu próximo vídeo": exigido em modo real com pré-orçamento; sem confirmação nada é gasto
        "confirmation": ({"required": True, "confirmed": p["cost_confirmed_at"] is not None,
                          "summary": budget_mod.next_video_summary(db, settings, pid)}
                         if has_pool and p["mode"] == "real" else {"required": False, "confirmed": True, "summary": None}),
        "estimates": billing.stage_estimates(settings, n_scenes=len(sc_rows) or 3),
        "caption": caption_file.read_text(encoding="utf-8") if caption_file.is_file() else None,
        "sheet": {
            "issues": (sheet or {}).get("issues", []),
            "unknown_fields": (sheet or {}).get("unknown_fields", []),
            "references": [{"role": r.get("role"), "source": r.get("source"),
                            "url": _media(pid, r["stored_path"]) if r.get("stored_path") else None}
                           for r in refs],
        },
        "video_context": product.get("video_context", ""),
        "visual_attributes": product.get("visual_attributes", {}),
        "id": pid, "mode": p["mode"], "status": p["status"], "label": PRODUCTION_LABELS[st],
        "reason": p["status_reason"], "format_id": p["format_id"], "product": {
            "name": product.get("name"), "variant": product.get("variant"), "link": product.get("affiliate_link")},
        "costs": {**costs, "committed_usd": round(committed, 4)}, "scenes": scenes, "delivery": delivery,
        "running": running, "error": error,
    }
    return data
