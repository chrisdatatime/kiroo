"""Rotas de treinamento dos agentes e biblioteca musical. Tudo isolado pelo workspace da sessão."""

from __future__ import annotations

import json
import mimetypes
import re
from datetime import datetime

from ..credits import InsufficientCredits, Ledger
from ..db import Database
from ..factory import build
from ..ffmpeg import FFmpeg
from ..music import MusicLibrary
from ..orchestrator import REVIEW_COST_ESTIMATE_USD
from ..spend import month_real_spend
from ..training import BRAND, Training, TrainingError, propose_guideline

ROLE = {"theo": "o diretor criativo", "iris": "a criadora de imagens", "lia": "a criadora de vídeos", "rui": "o revisor", BRAND: "o diretor criativo"}


def _reply(status: int, data):
    from .server import _json
    return _json(status, data)


def _ff(s) -> FFmpeg:
    return FFmpeg(s.ffmpeg_bin, s.ffprobe_bin, s.font_file, s.x264_preset)


def _prefs(tr: Training, wid: str) -> dict:
    return (tr.active(wid, "lia")[1].get("settings") or {}).get("music") or {}


def get_agents(app, path: str, ctx):
    from .server import Response
    s, wid = ctx["s"], ctx["wid"]
    db = Database(s.db_path)
    try:
        tr = Training(db, s.data_dir)
        if path == "/api/training":
            return _reply(200, tr.summary(wid))
        m = re.fullmatch(r"/api/training/([a-z_]+)", path)
        if m:
            return _reply(200, tr.view(wid, m.group(1)))
        lib = MusicLibrary(db, s)
        if path == "/api/music":
            return _reply(200, {"trends": lib.trends(), "kiroo": lib.kiroo(wid), "mine": lib.mine(wid), "prefs": _prefs(tr, wid)})
        m = re.fullmatch(r"/api/music/file/([A-Za-z0-9_.-]+)", path)
        if m:
            f = lib.file_of(wid, m.group(1), _ff(s))
            if f is None:
                return _reply(404, {"error": "não encontrado"})
            return Response(200, mimetypes.guess_type(f.name)[0] or "audio/mpeg", file=f)
        return _reply(404, {"error": "não encontrado"})
    finally:
        db.close()


def _run_test(app, tr: Training, db: Database, agent: str, task: str, ctx) -> dict:
    """Mesma tarefa com a versão ativa e com o rascunho. Sem `execute`, só compara os pedidos (grátis)."""
    s, wid = ctx["s"], ctx["wid"]
    current, draft = tr.build_prompts(wid, agent, task)
    return {"current": current, "draft": draft}


def _execute_test(app, tr, db, agent, task, ctx, confirm_estimate):
    s, wid = ctx["s"], ctx["wid"]
    ws = ctx["ws"]
    current, draft = tr.build_prompts(wid, agent, task)
    orch = build(s)  # usa o modo do workspace: DEMO chama o provedor simulado
    planner = orch.planner
    try:
        simulated = bool(planner.simulated)
        estimate = 0.0 if simulated else 2 * REVIEW_COST_ESTIMATE_USD
        hold = None
        if not simulated:
            if not confirm_estimate:
                raise TrainingError("confirme o consumo estimado antes do teste pago")
            from .. import paid_gate
            try:   # kill switch, ambiente, teto da plataforma e do agente
                paid_gate.check_spend(db, estimate, workspace_id=wid, agent=agent)
            except paid_gate.PaidCallsBlocked as exc:
                raise TrainingError(str(exc)) from None
            cap = paid_gate.effective_cap(ws["monthly_cap_usd"])
            spent = month_real_spend(db, workspace_id=wid)
            if cap <= 0 or spent + estimate > cap:
                raise TrainingError("o teto mensal de gastos não permite este teste")
            try:
                hold = Ledger(db).hold(wid, None, estimate, "Teste de treinamento")
            except InsufficientCredits as exc:
                raise TrainingError("saldo de créditos insuficiente para este teste") from exc
        cost = 0.0
        try:
            r1, m1 = planner.test_task(ROLE.get(agent, "um agente"), current)
            r2, m2 = planner.test_task(ROLE.get(agent, "um agente"), draft)
            cost = float(m1.get("estimated_cost_usd", REVIEW_COST_ESTIMATE_USD if not simulated else 0)) + float(m2.get("estimated_cost_usd", REVIEW_COST_ESTIMATE_USD if not simulated else 0))
        except BaseException:
            Ledger(db).release(hold, "teste de treinamento falhou")
            raise
        Ledger(db).close_direct(hold, cost, f"Teste de treinamento: {agent}")
        return tr.record_test(wid, agent, task, current, draft, executed=True, simulated=simulated, current_result=r1, draft_result=r2, estimated=estimate, cost=cost)
    finally:
        orch.db.close()


def post_agents(app, path: str, p: dict, ctx):
    s, wid = ctx["s"], ctx["wid"]
    db = Database(s.db_path)
    try:
        tr = Training(db, s.data_dir)
        m = re.fullmatch(r"/api/training/([a-z_]+)/([a-z_]+)", path)
        if m:
            agent, op = m.groups()
            if op == "save":
                tr.save_fields(wid, agent, p)
            elif op == "example":
                tr.add_example(wid, agent, str(p.get("kind")), p.get("text", ""), p.get("bad", ""), p.get("good", ""))
            elif op == "remove":
                tr.remove_item(wid, agent, str(p.get("key")), str(p.get("id")))
            elif op == "ref":
                tr.add_ref(wid, agent, p.get("title", ""), p.get("use", ""), p.get("text", ""), p.get("file"))
            elif op == "ref_delete":
                tr.delete_ref(wid, agent, str(p.get("id")))
            elif op == "propose":
                text = propose_guideline(p.get("note", ""), p.get("decision", "reject"))
                return _reply(200, {"text": text, "conflicts": tr.check_guideline(wid, agent, text) if text else []})
            elif op == "check":
                return _reply(200, {"conflicts": tr.check_guideline(wid, agent, str(p.get("text", "")))})
            elif op == "guideline":
                tr.add_guideline(wid, agent, p.get("text", ""), source=p.get("production"), keep_both=bool(p.get("keep_both")), replace=p.get("replace") or [])
            elif op == "discard":
                tr.discard_draft(wid, agent)
            elif op == "test":
                task = str(p.get("task", "")).strip()
                if not task:
                    raise TrainingError("descreva a tarefa de teste")
                if p.get("execute"):
                    if agent in ("nina", "beto"):
                        raise TrainingError("este agente não chama modelo: compare os pedidos, sem execução")
                    return _reply(200, {"test": _execute_test(app, tr, db, agent, task, ctx, bool(p.get("confirm"))), "view": tr.view(wid, agent)})
                cur, draft = tr.build_prompts(wid, agent, task)
                return _reply(200, {"test": tr.record_test(wid, agent, task, cur, draft), "view": tr.view(wid, agent)})
            elif op == "activate":
                tr.activate(wid, agent, p.get("note", ""))
            elif op == "restore":
                tr.restore(wid, agent, int(p.get("version", -1)))
            else:
                return _reply(404, {"error": "não encontrado"})
            return _reply(200, tr.view(wid, agent))

        lib = MusicLibrary(db, s)
        if path == "/api/music/upload":
            return _reply(200, lib.upload(wid, p, _ff(s)))
        if path == "/api/music/update":
            return _reply(200, lib.update(wid, str(p.get("id")), p))
        if path == "/api/music/favorite":
            lib.favorite(wid, str(p.get("id")), bool(p.get("on")))
            return _reply(200, {"ok": True})
        if path == "/api/music/delete":
            lib.delete(wid, str(p.get("id")))
            return _reply(200, {"ok": True})
        if path == "/api/music/suggest":
            return _reply(200, {"items": lib.suggest(wid, category=str(p.get("category", "")), name=str(p.get("name", "")), style=str(p.get("style", "dinamico")), prefs=_prefs(tr, wid))})
        return _reply(404, {"error": "não encontrado"})
    finally:
        db.close()
