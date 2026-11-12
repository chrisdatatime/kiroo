import pytest

from studio.factory import build
from studio.models import ReviewDecision
from studio.orchestrator import OrchestratorError
from studio.providers.simulated import SimulationScript
from studio.states import (InvalidTransition, ProductionStatus as PS, SceneStatus as SS,
                           check_production_transition, check_scene_transition)

from .conftest import approve_all_images, create, drive_to_final, requires_ffmpeg

R, A = ReviewDecision.REJECTED, ReviewDecision.APPROVED


# ----------------------------------------------------------------- estados
def test_state_transitions():
    check_production_transition(PS.RECEIVED, PS.VALIDATED)
    check_production_transition(PS.PRODUCING, PS.PAUSED)
    with pytest.raises(InvalidTransition):
        check_production_transition(PS.RECEIVED, PS.EDITING)
    with pytest.raises(InvalidTransition):
        check_production_transition(PS.COMPLETED, PS.PRODUCING)
    with pytest.raises(InvalidTransition):
        check_production_transition(PS.PAUSED, PS.EDITING)  # retomada só via resume
    check_scene_transition(SS.PENDING, SS.GENERATING_IMAGE)
    with pytest.raises(InvalidTransition):
        check_scene_transition(SS.PENDING, SS.GENERATING_VIDEO)  # vídeo nunca sem imagem aprovada
    with pytest.raises(InvalidTransition):
        check_scene_transition(SS.GENERATING_IMAGE, SS.IMAGE_APPROVED)  # aprovação passa pelo portão


def test_transitions_are_persisted_as_events(make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    events = [(e["from_state"], e["to_state"]) for e in orch.db.events(pid) if e["type"] == "production_status"]
    assert events[:3] == [("received", "validated"), ("validated", "scripted"), ("scripted", "producing")]


def test_scene_1_first_then_dependents(make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    status = {s["idx"]: s["status"] for s in orch.db.scenes(pid)}
    assert status == {1: SS.AWAITING_IMAGE_APPROVAL, 2: SS.PENDING, 3: SS.PENDING}
    orch.approve(pid, 1, "image")
    orch.run(pid)
    status = {s["idx"]: s["status"] for s in orch.db.scenes(pid)}
    assert status[2] == SS.AWAITING_IMAGE_APPROVAL and status[3] == SS.AWAITING_IMAGE_APPROVAL
    # cenas 2 e 3 usaram a imagem aprovada da cena 1 como referência
    att = orch.db.attempt(orch.db.scene(pid, 2)["current_image_attempt"])
    assert "scene:1:image" in att["references_json"]


def test_cannot_approve_without_pending_output(make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    with pytest.raises(OrchestratorError):
        orch.approve(pid, 2, "image")
    with pytest.raises(OrchestratorError):
        orch.approve(pid, 1, "video")


# ---------------------------------------------------------------- retomada
@requires_ffmpeg
def test_resume_after_restart_does_not_resubmit(make_orch, product, settings):
    script = SimulationScript(video_polls_before_done=50)
    orch = make_orch(script)
    pid = create(orch, product)
    orch.run(pid)
    orch.approve(pid, 1, "image")
    orch.run(pid, wait=False)  # vídeo da cena 1 enviado, ainda em processamento
    att_id = orch.db.scene(pid, 1)["current_video_attempt"]
    att = orch.db.attempt(att_id)
    assert att["status"] == "submitted" and att["remote_op_id"]
    orch.db.close()

    # "reinício do processo": novo orquestrador, novos provedores, mesmo banco
    orch2 = build(settings, sim_script=SimulationScript(), sleep=lambda _: None)
    orch2.run(pid)
    assert orch2.video_gen.submit_count == 0  # só consultou a operação existente
    att = orch2.db.attempt(att_id)
    assert att["status"] == "succeeded"
    assert orch2.db.scene(pid, 1)["status"] == SS.AWAITING_VIDEO_APPROVAL
    assert len(orch2.db.attempts(pid, 1, "video")) == 1


def test_transient_error_retries_same_attempt_with_backoff(make_orch, product):
    orch = make_orch(SimulationScript(image_submit_failures=["transient", "transient"]))
    pid = create(orch, product)
    orch.run(pid, wait=False)
    att = orch.db.attempt(orch.db.scene(pid, 1)["current_image_attempt"])
    assert att["status"] == "created" and att["transient_retries"] == 1 and att["next_retry_at"]
    orch.db.update_attempt(att["id"], next_retry_at=None)  # simula passagem do tempo
    orch.run(pid, wait=False)
    orch.db.update_attempt(att["id"], next_retry_at=None)
    orch.run(pid, wait=False)
    attempts = orch.db.attempts(pid, 1, "image")
    assert len(attempts) == 1  # mesma tentativa retomada, não uma nova
    assert attempts[0]["status"] == "succeeded" and attempts[0]["transient_retries"] == 2


def test_permanent_error_is_not_retried_forever(make_orch, product):
    orch = make_orch(SimulationScript(image_submit_failures=["permanent"] * 10))
    pid = create(orch, product)
    orch.run(pid)
    scene = orch.db.scene(pid, 1)
    assert scene["status"] == SS.BLOCKED and "recusado" in orch.db.events(pid)[-1]["message"]
    attempts = orch.db.attempts(pid, 1, "image")
    assert len(attempts) == 1  # pedido recusado não é repetido igual
    assert attempts[0]["status"] == "failed" and attempts[0]["estimated_cost_usd"] == 0
    orch.grant_attempts(pid, 1, "image", 1)  # operador decide tentar de novo
    orch.run(pid)
    assert len(orch.db.attempts(pid, 1, "image")) == 2


def test_identical_input_reuses_paid_result(make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    first = orch.db.scene(pid, 1)["current_image_attempt"]
    # força a cena a pedir nova geração sem mudar a entrada
    orch.db.update_scene(pid, 1, current_image_attempt=None, status=SS.GENERATING_IMAGE)
    orch.run(pid)
    assert orch.db.scene(pid, 1)["current_image_attempt"] == first
    assert orch.image_gen.submit_count == 1
    assert any(e["type"] == "attempt_reused" for e in orch.db.events(pid))


# --------------------------------------------------------------- orçamento
def test_budget_blocks_new_paid_calls(make_orch, product):
    orch = make_orch()
    pid = create(orch, product, budget=0.07)  # cabe 1 imagem (~0,058), não 2
    orch.run(pid)
    orch.approve(pid, 1, "image")
    orch.run(pid)
    prod = orch.db.production(pid)
    # freio interno: código estável, cliente vê "estamos finalizando" (sem pedido de upgrade) e o admin é avisado
    assert prod["status"] == PS.PAUSED and prod["pause_code"] == "ops_budget_reached"
    assert "finalizando" in prod["status_reason"] and "limite" not in prod["status_reason"].lower()
    assert any(e["type"] == "ops_alert" for e in orch.db.events(pid))
    assert orch.image_gen.submit_count == 1
    assert orch.committed_cost(pid) <= 0.07
    # retomar sem aumentar o limite pausa de novo, sem gastar
    orch.resume(pid)
    orch.run(pid)
    assert orch.db.production(pid)["status"] == PS.PAUSED and orch.image_gen.submit_count == 1
    orch.set_budget(pid, 10)
    orch.resume(pid)
    orch.run(pid)
    assert orch.image_gen.submit_count >= 2


def test_cancel_stops_new_steps(make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    orch.cancel(pid)
    orch.approve(pid, 1, "image")
    assert orch.run(pid) == PS.CANCELLED
    assert orch.image_gen.submit_count == 1


def test_real_mode_requires_budget_and_credentials(settings, product, tmp_path):
    import dataclasses

    from studio.db import Database
    from studio.orchestrator import Orchestrator
    real = dataclasses.replace(settings, mode="real", allow_paid_calls=False)
    orch = Orchestrator(real, Database(tmp_path / "x.db"), image_gen=None, video_gen=None, planner=None,
                        reviewer=None, ffmpeg=None)
    with pytest.raises(OrchestratorError):
        create(orch, product)
    orch.s = dataclasses.replace(real, allow_paid_calls=True)
    with pytest.raises(OrchestratorError):
        create(orch, product, budget=0)


# -------------------------------------------------------------- tentativas
def test_attempt_limit_blocks_scene(make_orch, product):
    orch = make_orch(SimulationScript(image_reviews=[R] * 10))
    pid = create(orch, product)
    orch.run(pid)
    assert orch.db.scene(pid, 1)["status"] == SS.BLOCKED
    assert orch.image_gen.submit_count == 3
    corrections = [e for e in orch.db.events(pid) if e["type"] == "auto_correction"]
    assert len(corrections) == 2
    # operador concede +1 tentativa
    orch.grant_attempts(pid, 1, "image", 1)
    orch.run(pid)
    assert orch.image_gen.submit_count == 4


def test_auto_rejection_feeds_correction_into_next_prompt(make_orch, product):
    orch = make_orch(SimulationScript(image_reviews=[R, A]))
    pid = create(orch, product)
    orch.run(pid)
    attempts = orch.db.attempts(pid, 1, "image")
    assert len(attempts) == 2
    assert "CORRECTIONS FROM PREVIOUS REVIEWS" not in attempts[0]["prompt"]
    assert "NEW, APPLY STRICTLY" in attempts[1]["prompt"]
    assert orch.db.scene(pid, 1)["status"] == SS.AWAITING_IMAGE_APPROVAL


@requires_ffmpeg
def test_reject_one_video_redoes_only_that_take(make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    assert drive_to_final(orch, pid) == PS.AWAITING_FINAL_REVIEW
    before = {(a["scene_idx"], a["kind"]): a["id"] for a in orch.db.attempts(pid) if a["kind"] in ("image", "video")}
    img_submits, vid_submits = orch.image_gen.submit_count, orch.video_gen.submit_count

    orch.reject(pid, 2, "video", "mão atravessa a alça no final")
    assert orch.db.production(pid)["status"] == PS.PRODUCING
    assert drive_to_final(orch, pid) == PS.AWAITING_FINAL_REVIEW
    assert orch.image_gen.submit_count == img_submits
    assert orch.video_gen.submit_count == vid_submits + 1
    new_video = orch.db.attempt(orch.db.scene(pid, 2)["approved_video_attempt"])
    assert "mão atravessa a alça" in new_video["prompt"]
    for idx in (1, 3):
        assert orch.db.scene(pid, idx)["approved_video_attempt"] == before[(idx, "video")]
    # histórico preservado para auditoria
    assert len(orch.db.attempts(pid, 2, "video")) == 2


def test_new_scene1_image_invalidates_only_dependents(make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    approve_all_images(orch, pid)
    orch.run(pid)
    approve_all_images(orch, pid)
    old_s2 = orch.db.scene(pid, 2)["approved_image_attempt"]
    orch.reject(pid, 1, "image", "tampa diferente da referência")
    orch.run(pid)
    orch.approve(pid, 1, "image")
    assert orch.db.scene(pid, 2)["status"] == SS.PENDING
    assert orch.db.scene(pid, 3)["status"] == SS.PENDING
    assert orch.db.attempt(old_s2)["superseded"] == 1


def test_editing_animation_prompt_keeps_image(make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    orch.approve(pid, 1, "image")
    img = orch.db.scene(pid, 1)["approved_image_attempt"]
    orch.edit_scene_prompt(pid, 1, animation_prompt="Slow 10 degree turn. Silent.")
    scene = orch.db.scene(pid, 1)
    assert scene["approved_image_attempt"] == img
    assert scene["status"] in (SS.GENERATING_VIDEO, SS.IMAGE_APPROVED)
    orch.edit_scene_prompt(pid, 1, image_prompt="Different still image prompt.")
    assert orch.db.scene(pid, 1)["status"] == SS.PENDING
    assert orch.db.attempt(img)["superseded"] == 1
