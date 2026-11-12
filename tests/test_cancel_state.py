"""Cancelar de verdade: depois de "Cancelado", nada roda, nada é enviado nem cobrado, e o /api/state não mostra mais
"Criando imagens / Missão em andamento" (o bug visto depois de cancelar com a reserva já devolvida)."""

import json

from studio.db import Database
from studio.models import ProductInput  # noqa: F401  (fixture product usa)
from studio.providers.simulated import SimulationScript
from studio.states import SceneStatus

from .conftest import approve_all_images, create
from .test_creative_flow import BASE, HOST, PNG, app, post, wait_idle  # noqa: F401

CREATIVE = {"presentation": "product_only", "proposal": "details", "environment": "neutro", "tone": "natural"}
FILES = [{"name": "f.png", "data": PNG, "role": "front"}]


def _state(app, pid):
    return json.loads(app.handle("GET", f"/api/state?pid={pid}", HOST, b"").body)


def _force_generating(settings, pid):
    """Como as produções antigas canceladas (prod_aa78ed1022, prod_57491e2e40): cenas paradas em 'gerando'."""
    db = Database(settings.db_path)
    try:
        for sc in db.scenes(pid):
            db.conn.execute("UPDATE scenes SET status=? WHERE production_id=? AND idx=?",
                            (SceneStatus.GENERATING_IMAGE, pid, sc["idx"]))
    finally:
        db.close()


def test_cancelled_production_state_has_no_spinner_or_pending_work(app, settings):
    st, r = post(app, "/api/productions", {**BASE, "creative": CREATIVE, "files": FILES})
    pid = r["pid"]
    wait_idle(app, pid)
    _force_generating(settings, pid)
    st, data = post(app, f"/api/productions/{pid}/cancel", {})
    assert st == 200, data
    s = _state(app, pid)
    p = s["production"]
    assert p["status"] == "cancelled" and p["ended"] == "cancelled" and p["running"] is False
    assert all(sc["label"] == "Interrompida" and sc["stopped"] for sc in p["scenes"])
    ag = s["agent_states"]
    assert ag["images"]["status"] == "idle" and ag["videos"]["status"] == "idle" and ag["operator"]["status"] != "needs_you"
    assert ag["orchestrator"]["status"] == "done" and "cancelada" in ag["orchestrator"]["message"].lower()
    row = next(x for x in s["productions"] if x["id"] == pid)
    assert row["ended"] == "cancelled" and row["label"] == "Cancelado"
    assert p["presentation"] == "product_only" and p["format_id"] == "produto_3cenas_15s"


def test_cancel_is_final_and_nothing_runs_after(app, settings):
    st, r = post(app, "/api/productions", {**BASE, "creative": CREATIVE, "files": FILES, "start": False})
    pid = r["pid"]
    assert post(app, f"/api/productions/{pid}/cancel", {})[0] == 200
    st, data = post(app, f"/api/productions/{pid}/cancel", {})
    assert st == 400 and "encerrada" in data["error"]          # antes: erro 500 (transição inválida)
    # nenhuma ação de avançar vale numa missão cancelada (nem de uma tela antiga ainda aberta)
    for action, body in (("run", {}), ("go_ahead", {"stage": "images"}), ("resume", {}), ("validate", {}),
                         ("direction", {"creative": CREATIVE}), ("approve", {"scene": 1, "stage": "image"}),
                         ("references", {"files": FILES}), ("confirm", {})):
        st, data = post(app, f"/api/productions/{pid}/{action}", body)
        assert st == 409 and data.get("ended") == "cancelled" and "cancelada" in data["error"], (action, st, data)
    wait_idle(app, pid)
    db = Database(settings.db_path)
    try:
        assert db.production(pid)["status"] == "cancelled"
        assert not db.attempts(pid)                              # nenhuma chamada (nem roteiro) depois de cancelar
    finally:
        db.close()


def test_old_cancelled_production_with_stale_scenes_shows_cancelled(app, settings):
    """Produção cancelada antes desta versão: status no banco = cancelled, cenas paradas em gerando."""
    st, r = post(app, "/api/productions", {**BASE, "creative": CREATIVE, "files": FILES})
    pid = r["pid"]
    wait_idle(app, pid)
    _force_generating(settings, pid)
    db = Database(settings.db_path)
    try:
        db.conn.execute("UPDATE productions SET status='cancelled', status_reason='cancelada pelo operador' WHERE id=?",
                        (pid,))
    finally:
        db.close()
    p = _state(app, pid)["production"]
    assert p["ended"] == "cancelled" and p["running"] is False and all(sc["stopped"] for sc in p["scenes"])


def test_cancel_interrupts_inflight_generation_without_charging(make_orch, product):
    orch = make_orch(SimulationScript(video_polls_before_done=50))
    pid = create(orch, product)
    orch.run(pid)
    approve_all_images(orch, pid)
    orch.run(pid, wait=False)                     # vídeos enviados ao provedor, ainda processando
    inflight = [a for a in orch.db.attempts(pid, kind="video") if a["status"] == "submitted"]
    assert inflight
    submits = orch.video_gen.submit_count
    orch.cancel(pid)
    after = {a["id"]: a for a in orch.db.attempts(pid, kind="video")}
    assert all(after[a["id"]]["status"] == "failed" and after[a["id"]]["superseded"] for a in inflight)
    assert any(e["type"] == "cancel_inflight" for e in orch.db.events(pid))
    # o laço que ainda estivesse no meio de uma consulta não registra o resultado nem cobra
    assert orch._poll(pid, inflight[0]["id"]) == "paused"
    assert orch.db.attempt(inflight[0]["id"])["status"] == "failed"
    assert orch.run(pid) == "cancelled" and orch.video_gen.submit_count == submits


def test_no_paid_call_is_sent_once_cancelled(make_orch, product):
    """Corrida: o cancelamento chega entre criar a tentativa e enviá-la ao provedor."""
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    approve_all_images(orch, pid)
    orch.db.set_production_status(pid, "cancelled", "cancelada pelo operador")
    before = orch.video_gen.submit_count
    att = orch.db.create_attempt(production_id=pid, scene_idx=1, kind="video", provider="simulated", model="sim",
                                 simulated=True, input_hash="x", prompt="p", params={}, references=[],
                                 estimated_cost_usd=0.5, pricing_source="teste")
    assert orch._submit(pid, att) == "paused" and orch.video_gen.submit_count == before
    a = orch.db.attempt(att)
    assert a["status"] == "failed" and a["superseded"] and a["estimated_cost_usd"] == 0.0
