"""Fluxo ponta a ponta do motor fal.ai com o workflow SIMULADO: criacao, execucao, entrega (video + 1 foto + legenda), creditos,
idempotencia, retomada, cancelamento, entrega incompleta, recuperacao controlada, decisoes do administrador, custo real
e limpeza. Nenhuma rede e nenhum custo."""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from studio import budget, fal_contract as fc, fal_pipeline as fp, package_files as pf
from studio.accounts import Accounts
from studio.credits import Ledger, to_cc
from studio.db import Database
from studio.ffmpeg import FFmpeg
from studio.models import ProductInput
from studio.orchestrator import DuplicateRequest, Orchestrator, OrchestratorError
from studio.providers.simulated import SimulatedPlanner, SimulatedReviewer, SimulatedVideoGenerator, SimulationScript, \
    SimulatedImageGenerator, placeholder_png
from studio.providers.simulated_fal import FalSimScript, SimulatedFalWorkflow
from studio.states import ProductionStatus as PS

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg
CHARGE = to_cc(budget.workflow_cost("dark")[0])      # 2,00 US$ placeholder -> centesimos de credito


def make(settings, tmp_path, *, real=False, fal_script=None, db=None, **ov):
    s = dataclasses.replace(settings, mode="real" if real else "simulated", allow_paid_calls=real,
                            monthly_cap_usd=100.0 if real else 0.0, fal_api_key="fal-FAKE-0123456789",
                            poll_interval_s=0.0, fal_poll_s=0.0, x264_preset="ultrafast", **ov)
    ff = FFmpeg(s.ffmpeg_bin, s.ffprobe_bin, s.font_file, "ultrafast")
    sim = SimulatedFalWorkflow(s.data_dir, ff, fal_script or FalSimScript(), estimator=budget.workflow_cost)
    script = SimulationScript()
    return Orchestrator(s, db or Database(s.db_path), image_gen=SimulatedImageGenerator(s.data_dir, s.image_model, script),
                        video_gen=SimulatedVideoGenerator(s.data_dir, s.video_model, ff, script), planner=SimulatedPlanner(),
                        reviewer=SimulatedReviewer(script), ffmpeg=ff, sleep=lambda _: None, base_dir=tmp_path, fal_gen=sim)


@pytest.fixture
def photo_product(tmp_path):
    p = tmp_path / "foto.png"
    p.write_bytes(placeholder_png("foto", 540, 960))
    return ProductInput.model_validate({"name": "", "references": [{"path": str(p), "role": "front"}]})


def funded(settings, tmp_path, cc=50_000, **kw):
    db = Database(settings.db_path)
    _, wid = Accounts(db).create_user("cliente@example.com", "senha-forte-123")
    Accounts(db).set_workspace(wid, allow_real=1, mode="real", monthly_cap_usd=100, credits_exempt=0)
    Ledger(db).add(wid, cc, note="teste")
    return make(settings, tmp_path, real=True, db=db, **kw), wid


def new(orch, product, *, style="dark", crid="req-0001", wid=None, confirm=True):
    pid, dup = fp.create_production(orch, product, style=style, workspace_id=wid, client_request_id=crid,
                                    budget_usd=50.0, prebudget=wid is not None and orch.s.mode == "real")
    if wid and confirm and not dup:
        orch.confirm_cost(pid)
    return pid


def status(o, pid):
    return PS(o.db.production(pid)["status"])


def delivery(o, pid):
    return o.s.data_dir / "productions" / pid / "delivery"


# ================================================================= entrega
def test_demo_flow_delivers_video_photo_caption_and_cover(settings, tmp_path, photo_product):
    o = make(settings, tmp_path)
    pid = new(o, photo_product, style="light")
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW
    d = delivery(o, pid)
    names = {p.name for p in d.iterdir()}
    assert {"final.mp4", "product_image_01.jpg", "cover.jpg", "caption.txt", "delivery_meta.json"} <= names
    assert not names & {"product_image_02.jpg", "product_image_03.jpg"}
    info = o.ffmpeg.probe(d / "final.mp4")
    assert abs(info["duration_s"] - 15.0) < 0.3 and (info["width"], info["height"]) == (540, 960) and info["has_audio"]
    assert pf.validate("image", (d / "product_image_01.jpg").read_bytes())["width"] == 720
    cap = (d / "caption.txt").read_text(encoding="utf-8")
    assert cap.startswith("Copo azul de aco inox\n\nMantem a bebida gelada")           # titulo + legenda do JSON do workflow
    row = o.db.production(pid)
    assert row["engine"] == "fal" and row["style"] == "light" and row["delivery_status"] == "complete"
    att = o.db.attempts(pid)[0]
    assert att["kind"] == "workflow" and att["status"] == "succeeded" and att["scene_idx"] is None
    assert json.loads((o.s.data_dir / "productions" / pid / "workflow/attempt_01/result.json").read_text(encoding="utf-8"))["package"]
    meta = json.loads((d / "delivery_meta.json").read_text(encoding="utf-8"))
    assert meta["delivery_status"] == "complete" and meta["text_status"] == "ok" and meta["compose"]["video_action"] == "copy"
    assert set(meta["files"]) == {"final.mp4", "product_image_01.jpg", "cover.jpg"}
    assert meta["files"]["product_image_01.jpg"]["role"] == "hero"
    o.final_decision(pid, True)
    assert status(o, pid) == PS.COMPLETED


def test_final_video_is_the_workflow_video_copied_without_reencode(settings, tmp_path, photo_product):
    o = make(settings, tmp_path)
    pid = new(o, photo_product)
    o.run(pid)
    raw = o.s.data_dir / "productions" / pid / "workflow/attempt_01/video.mp4"
    final = delivery(o, pid) / "final.mp4"
    for m in ("0:v", "0:a"):
        a = o.ffmpeg.run(["-i", str(raw), "-map", m, "-c", "copy", "-f", "md5", "-"]).stdout.strip()
        b = o.ffmpeg.run(["-i", str(final), "-map", m, "-c", "copy", "-f", "md5", "-"]).stdout.strip()
        assert a == b, m


def test_video_outside_the_window_is_cut_or_extended_keeping_audio(settings, tmp_path, photo_product):
    for secs, action in ((17.5, "cut"), (13.5, "extend")):
        o = make(settings, tmp_path, fal_script=FalSimScript(video_seconds=secs))
        pid = new(o, photo_product, crid=f"janela-{action}")
        assert o.run(pid) == PS.AWAITING_FINAL_REVIEW
        meta = json.loads((delivery(o, pid) / "delivery_meta.json").read_text(encoding="utf-8"))
        info = o.ffmpeg.probe(delivery(o, pid) / "final.mp4")
        assert meta["compose"]["video_action"] == action and info["has_audio"] and abs(info["duration_s"] - 15.0) < 0.3


def test_caption_is_the_workflow_text_and_never_invented(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(title="Garrafa azul", caption="Aco inox."))
    pid = new(o, photo_product)
    o.run(pid)
    cap = (delivery(o, pid) / "caption.txt").read_text(encoding="utf-8")
    assert cap.splitlines()[0] == "Garrafa azul" and "Aco inox." in cap


@pytest.mark.parametrize("raw", ["isto nao e json {", "", '{"title": "", "caption": ""}'])
def test_invalid_or_empty_caption_json_still_delivers_with_a_warning_and_no_invented_text(settings, tmp_path, photo_product, raw):
    o, wid = funded(settings, tmp_path, fal_script=FalSimScript(output_text=raw))
    pid = new(o, photo_product, wid=wid)
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW
    d = delivery(o, pid)
    assert (d / "final.mp4").is_file() and (d / "product_image_01.jpg").is_file()
    cap = (d / "caption.txt").read_text(encoding="utf-8")
    assert "Copo" not in cap and "Produto" not in cap and len(cap.splitlines()) <= 2          # so a identificacao de publicidade
    meta = json.loads((d / "delivery_meta.json").read_text(encoding="utf-8"))
    assert meta["text_status"] == "partial" and any("legenda" in w for w in meta["warnings"])
    assert any(e["type"] == "delivery_warning" and "legenda" in e["message"] for e in o.db.events(pid))
    assert Ledger(o.db).pool_state(pid)["used_cc"] == CHARGE                                   # entrega valida: cobra


def test_photo_is_resized_to_at_most_2048px(settings, tmp_path):
    big = tmp_path / "big.png"
    o = make(settings, tmp_path)
    o.ffmpeg.run(["-f", "lavfi", "-i", "color=c=green:s=3200x2400", "-frames:v", "1", str(big)])
    prod = ProductInput.model_validate({"name": "x", "references": [{"path": str(big), "role": "front"}]})
    pid = new(o, prod)
    o.run(pid)
    up = o.s.data_dir / "productions" / pid / "inputs" / "workflow_photo.jpg"
    assert max(pf.jpeg_info(up.read_bytes())) == 2048


def test_each_style_goes_to_its_own_workflow(settings, tmp_path, photo_product):
    o = make(settings, tmp_path)
    a, b = new(o, photo_product, style="dark", crid="c-dark-1"), new(o, photo_product, style="light", crid="c-light-1")
    o.run(a), o.run(b)
    assert json.loads(o.db.attempts(a)[0]["params_json"])["workflow"].endswith("dark")
    assert json.loads(o.db.attempts(b)[0]["params_json"])["workflow"].endswith("light")


# ================================================================= creditos e idempotencia
def test_success_charges_once_and_final_approval_keeps_the_ledger_exact(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path)
    led = Ledger(o.db)
    pid = new(o, photo_product, wid=wid)
    assert led.pool_state(pid)["reserved_cc"] == CHARGE and led.balance(wid) == 50_000 - CHARGE
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW
    assert led.pool_state(pid)["used_cc"] == CHARGE
    o.final_decision(pid, True)
    assert led.balance(wid) == 50_000 - CHARGE and led.pool_state(pid)["closed"]
    assert [c["decision"] for c in led.charges(pid)] == ["charged"]
    o.run(pid), o._settle(pid)
    assert led.balance(wid) == 50_000 - CHARGE and len(led.charges(pid)) == 1       # idempotente


def test_double_click_returns_the_same_production_and_reserves_once(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path)
    p1, d1 = fp.create_production(o, photo_product, style="dark", workspace_id=wid, client_request_id="clique-0001",
                                  budget_usd=50.0, prebudget=True)
    p2, d2 = fp.create_production(o, photo_product, style="dark", workspace_id=wid, client_request_id="clique-0001",
                                  budget_usd=50.0, prebudget=True)
    assert p1 == p2 and (d1, d2) == (False, True)
    assert o.db.conn.execute("SELECT COUNT(*) FROM productions").fetchone()[0] == 1
    assert Ledger(o.db).balance(wid) == 50_000 - CHARGE                               # uma reserva so


def test_unique_index_blocks_a_racing_duplicate_even_without_the_lookup(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path)
    first = new(o, photo_product, wid=wid, crid="corrida-01")
    with pytest.raises(DuplicateRequest) as e:       # a checagem previa foi "ultrapassada" por outra requisicao
        o.create_production(photo_product, format_id="produto_3cenas_15s", art_direction="ambiente_neutro", presenter="bia",
                            budget_usd=50, workspace_id=wid, prebudget=True, engine="fal", style="dark",
                            client_request_id="corrida-01", estimate=budget.estimate_workflow(o.s, "dark"))
    assert e.value.pid == first
    assert Ledger(o.db).balance(wid) == 50_000 - CHARGE and Ledger(o.db).held(wid) == CHARGE
    orphans = o.db.conn.execute("SELECT status FROM productions WHERE workspace_id IS NULL").fetchall()
    assert [r["status"] for r in orphans] == ["cancelled"]                           # a linha criada de sobra e descartada


def test_same_client_request_id_in_another_workspace_is_a_different_production(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path)
    other = Accounts(o.db).create_user("outro@example.com", "senha-forte-123")[1]
    a = new(o, photo_product, wid=wid, crid="mesmo-id-01")
    b, dup = fp.create_production(o, photo_product, style="dark", workspace_id=other, client_request_id="mesmo-id-01",
                                  budget_usd=50.0, prebudget=False)
    assert a != b and dup is False


def test_redo_is_a_new_execution_and_charges_the_same_again(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path)
    p1 = new(o, photo_product, wid=wid, crid="refaz-0001")
    o.run(p1), o.final_decision(p1, True)
    p2 = new(o, photo_product, wid=wid, crid="refaz-0002")
    o.run(p2), o.final_decision(p2, True)
    assert o.fal_gen.submit_count == 2 and Ledger(o.db).balance(wid) == 50_000 - 2 * CHARGE


def test_reassembly_after_final_rejection_does_not_resubmit_or_charge_again(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path)
    pid = new(o, photo_product, wid=wid)
    o.run(pid)
    o.final_decision(pid, False, "remontar")
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW
    assert o.fal_gen.submit_count == 1 and Ledger(o.db).pool_state(pid)["used_cc"] == CHARGE


# ================================================================= falhas
@pytest.mark.parametrize("script", [FalSimScript(error_on_complete="no falhou"), FalSimScript(missing={"video"}),
                                    FalSimScript(video_has_audio=False)])
def test_technical_failure_has_no_debit_and_refunds_the_prebudget(settings, tmp_path, photo_product, script):
    o, wid = funded(settings, tmp_path, fal_script=script)
    pid = new(o, photo_product, wid=wid)
    assert o.run(pid) == PS.FAILED
    led = Ledger(o.db)
    assert led.balance(wid) == 50_000 and led.pool_state(pid)["closed"]                # tudo devolvido
    assert [c["decision"] for c in led.charges(pid)] == ["technical_failure"]
    assert "Nada foi cobrado" in o.db.production(pid)["status_reason"]
    assert not (delivery(o, pid) / "final.mp4").exists()


def test_video_without_audio_is_a_technical_failure_with_no_debit_and_nothing_published(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path, fal_script=FalSimScript(video_has_audio=False))
    pid = new(o, photo_product, wid=wid)
    assert o.run(pid) == PS.FAILED
    assert "sem audio" in " ".join(e["message"] for e in o.db.events(pid))
    assert not (delivery(o, pid) / "final.mp4").exists() and not (delivery(o, pid) / "caption.txt").exists()
    led = Ledger(o.db)
    assert led.balance(wid) == 50_000 and [c["decision"] for c in led.charges(pid)] == ["technical_failure"]
    assert o.db.production(pid)["delivery_status"] != "complete" and o.fal_gen.submit_count == 1       # nao reenvia


def test_corrupt_video_is_a_technical_failure(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path)
    pid = new(o, photo_product, wid=wid)
    orig = o.fal_gen.fetch
    o.fal_gen.fetch = lambda a: b"nao-e-video" * 5000 if a.kind == "video" else orig(a)
    assert o.run(pid) == PS.FAILED and Ledger(o.db).balance(wid) == 50_000


def test_kill_switch_blocks_before_any_submit(settings, tmp_path, photo_product, monkeypatch):
    o, wid = funded(settings, tmp_path)
    pid = new(o, photo_product, wid=wid)
    monkeypatch.setenv("STUDIO_KILL_SWITCH", "1")
    assert o.run(pid) == PS.PAUSED and o.fal_gen.submit_count == 0
    assert o.db.production(pid)["pause_code"].startswith("paid_gate")


def test_without_confirmation_nothing_is_sent(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path)
    pid = new(o, photo_product, wid=wid, confirm=False)
    o.run(pid)
    assert o.fal_gen.submit_count == 0 and status(o, pid) in {PS.VALIDATED, PS.SCRIPTED}
    o.confirm_cost(pid)
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW


def test_insufficient_balance_blocks_creation(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path, cc=100)
    from studio.credits import InsufficientCredits
    with pytest.raises(InsufficientCredits):
        new(o, photo_product, wid=wid)
    assert o.db.conn.execute("SELECT COUNT(*) FROM productions").fetchone()[0] == 0


def test_real_mode_needs_the_fal_key(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path)
    o.s = dataclasses.replace(o.s, fal_api_key=None)
    with pytest.raises(OrchestratorError, match="FAL_KEY"):
        new(o, photo_product, wid=wid)


# ================================================================= retomada e envio incerto
def test_restart_resumes_the_same_remote_execution_without_resubmitting(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(polls_before_done=4))
    pid = new(o, photo_product)
    o.run(pid, wait=False)
    att = o.db.attempts(pid)[0]
    assert att["status"] == "submitted" and att["remote_op_id"] and o.fal_gen.submit_count == 1
    o.db.close()
    o2 = make(settings, tmp_path)                                      # "reinicio": novo processo, mesmo banco e disco
    assert o2.run(pid) == PS.AWAITING_FINAL_REVIEW
    assert o2.fal_gen.submit_count == 0 and len(o2.db.attempts(pid)) == 1


def test_uncertain_submit_is_never_retried_automatically(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path, fal_script=FalSimScript(submit_failures=["uncertain"]))
    pid = new(o, photo_product, wid=wid)
    assert o.run(pid) == PS.PAUSED and o.db.production(pid)["pause_code"] == fp.SUBMIT_UNCERTAIN
    for _ in range(3):                                                  # nem repetindo, nem "reiniciando"
        o.run(pid)
        o2 = make(settings, tmp_path, real=True)
        assert o2.run(pid) == PS.PAUSED and o2.fal_gen.submit_count == 0
    assert o.fal_gen.submit_count == 0 and Ledger(o.db).held(wid) == CHARGE      # reserva intacta
    att = o.db.attempts(pid)[0]
    assert att["status"] == "created" and json.loads(att["remote_meta_json"])["stage"] == "uncertain"


def test_crash_in_the_middle_of_submit_is_treated_as_uncertain(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(polls_before_done=9))
    pid = new(o, photo_product)
    o.run(pid, wait=False)                                            # enviado; agora simulamos a queda NO MEIO do envio
    a = o.db.attempts(pid)[0]
    o.db.update_attempt(a["id"], status="created", remote_op_id=None, submitted_at=None,
                        remote_meta_json=json.dumps({"stage": "submitting"}))
    o2 = make(settings, tmp_path)
    assert o2.run(pid) == PS.PAUSED and o2.fal_gen.submit_count == 0
    assert o2.db.production(pid)["pause_code"] == fp.SUBMIT_UNCERTAIN


def test_admin_not_sent_then_the_flow_continues(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(submit_failures=["uncertain"]))
    pid = new(o, photo_product)
    o.run(pid)
    fp.admin_action(o, pid, "not-sent")
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW and o.fal_gen.submit_count == 1


def test_admin_adopt_polls_the_existing_remote_execution(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(submit_failures=["uncertain"]))
    pid = new(o, photo_product)
    o.run(pid)
    ghost = o.fal_gen.submit_full(__import__("studio.providers.base", fromlist=["x"]).WorkflowRequest(
        "dark", o.s.data_dir / "productions" / pid / "inputs" / "workflow_photo.jpg"))
    fp.admin_action(o, pid, "adopt", request_id=ghost.request_id)
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW and o.fal_gen.submit_count == 1       # so o "fantasma"; nada novo


def test_transient_submit_errors_retry_the_same_attempt(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(submit_failures=["transient", "transient"]))
    pid = new(o, photo_product)
    o.run(pid, wait=False)
    for _ in range(3):
        for a in o.db.attempts(pid):
            o.db.update_attempt(a["id"], next_retry_at=None)
        o.run(pid, wait=False)
    assert len(o.db.attempts(pid)) == 1 and status(o, pid) == PS.AWAITING_FINAL_REVIEW


def test_permanent_refusal_pauses_without_charge_and_can_be_resumed(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path, fal_script=FalSimScript(submit_failures=["permanent"]))
    pid = new(o, photo_product, wid=wid)
    assert o.run(pid) == PS.PAUSED and o.db.production(pid)["pause_code"] == fp.REFUSED
    assert Ledger(o.db).held(wid) == CHARGE
    o.db.resume_production(pid)
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW                       # nada foi aceito antes: pode tentar de novo


def test_timeout_pauses_and_a_resume_alone_never_re_executes(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(polls_before_done=50), fal_timeout_s=-1.0)
    pid = new(o, photo_product)
    assert o.run(pid) == PS.PAUSED and o.db.production(pid)["pause_code"] == fp.TIMEOUT
    assert o.fal_gen.cancelled                                          # tentou cancelar la
    o.db.resume_production(pid)
    assert o.run(pid) == PS.PAUSED and o.db.production(pid)["pause_code"] == fp.ADMIN_REQUIRED
    assert o.fal_gen.submit_count == 1


def test_max_inflight_limits_simultaneous_executions(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(polls_before_done=30), fal_max_inflight=1)
    a, b = new(o, photo_product, crid="inflight-1"), new(o, photo_product, crid="inflight-2")
    o.run(a, wait=False), o.run(b, wait=False)
    assert o.fal_gen.submit_count == 1 and o.db.attempts(b) == []


# ================================================================= cancelamento
def test_cancel_in_flight_calls_remote_cancel_and_refunds_everything(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path, fal_script=FalSimScript(polls_before_done=30))
    pid = new(o, photo_product, wid=wid)
    o.run(pid, wait=False)
    op = o.db.attempts(pid)[0]["remote_op_id"]
    o.cancel(pid)
    assert op in o.fal_gen.cancelled and status(o, pid) == PS.CANCELLED
    att = o.db.attempts(pid)[0]
    assert att["status"] == "failed" and att["superseded"] == 1
    led = Ledger(o.db)
    assert led.balance(wid) == 50_000 and led.pool_state(pid)["closed"]
    assert [c["decision"] for c in led.charges(pid)] == ["technical_failure"]


# ================================================================= entrega incompleta
def test_missing_image_is_never_a_complete_delivery_and_nothing_is_published(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path, fal_script=FalSimScript(missing={"image:hero"}))
    pid = new(o, photo_product, wid=wid)
    assert o.run(pid) == PS.PAUSED
    row = o.db.production(pid)
    assert row["pause_code"] == fp.INCOMPLETE and row["delivery_status"] == "incomplete"
    assert row["status"] != PS.COMPLETED and "finalizando" in row["status_reason"]
    assert json.loads(row["delivery_json"])["missing"] == ["hero"]
    d = delivery(o, pid)
    assert not (d / "final.mp4").exists() and not (d / "product_image_01.jpg").exists()   # nada publicado pela metade
    led = Ledger(o.db)                                                                    # reserva mantida: sem debito
    assert led.pool_state(pid)["used_cc"] == 0 and led.held(wid) == CHARGE and led.charges(pid) == []
    att = o.db.attempts(pid)[0]
    assert att["status"] == "submitted" and json.loads(att["remote_meta_json"])["stage"] == "incomplete"
    for _ in range(3):                                                                    # nunca reexecuta sozinho
        o.run(pid)
        assert make(settings, tmp_path, real=True).run(pid) == PS.PAUSED
    assert o.fal_gen.submit_count == 1


def test_corrupt_image_counts_as_missing(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(corrupt={"image:hero"}))
    pid = new(o, photo_product)
    assert o.run(pid) == PS.PAUSED and json.loads(o.db.production(pid)["delivery_json"])["missing"] == ["hero"]


def test_controlled_recovery_fetches_only_the_missing_image_by_node(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(missing={"image:hero"}, recoverable={"hero"}))
    pid = new(o, photo_product)
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW
    assert o.fal_gen.submit_count == 1 and o.fal_gen.recover_calls == 1
    assert (delivery(o, pid) / "product_image_01.jpg").is_file()
    assert any(e["type"] == "fal_recover" for e in o.db.events(pid))


def test_admin_deliver_partial_settles_and_records_the_decision(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path, fal_script=FalSimScript(missing={"image:hero"}))
    pid = new(o, photo_product, wid=wid)
    o.run(pid)
    fp.admin_action(o, pid, "deliver-partial", reason="cliente aceitou")
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW
    assert o.db.production(pid)["delivery_status"] == "partial"
    assert (delivery(o, pid) / "product_image_01.jpg").exists() is False and (delivery(o, pid) / "final.mp4").exists()
    assert Ledger(o.db).pool_state(pid)["used_cc"] == CHARGE and o.fal_gen.submit_count == 1
    assert any(e["type"] == "admin_decision" for e in o.db.events(pid))


def test_admin_waive_refunds_the_client_and_ends_the_mission(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path, fal_script=FalSimScript(missing={"image:hero"}))
    pid = new(o, photo_product, wid=wid)
    o.run(pid)
    fp.admin_action(o, pid, "waive", reason="falha do fornecedor")
    assert status(o, pid) == PS.CANCELLED and Ledger(o.db).balance(wid) == 50_000 and o.fal_gen.submit_count == 1
    assert [c["decision"] for c in Ledger(o.db).charges(pid)] == ["technical_failure"]


def test_admin_recover_tries_again_without_new_submit(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(missing={"image:hero"}))
    pid = new(o, photo_product)
    o.run(pid)
    fp.admin_action(o, pid, "recover")
    assert o.run(pid) == PS.PAUSED and o.fal_gen.submit_count == 1       # sem info do no: continua incompleto


def test_admin_resubmit_is_explicit_and_goes_through_the_paid_gate(settings, tmp_path, photo_product, monkeypatch):
    o, wid = funded(settings, tmp_path, fal_script=FalSimScript(missing={"image:hero"}))
    pid = new(o, photo_product, wid=wid)
    o.run(pid)
    monkeypatch.setenv("STUDIO_KILL_SWITCH", "1")
    fp.admin_action(o, pid, "resubmit", reason="tentar de novo")
    assert o.run(pid) == PS.PAUSED and o.fal_gen.submit_count == 1       # kill switch barrou a nova execucao
    monkeypatch.delenv("STUDIO_KILL_SWITCH")
    o.fal_gen.script.missing = set()
    o.db.resume_production(pid)
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW and o.fal_gen.submit_count == 2
    led = Ledger(o.db)
    assert led.pool_state(pid)["used_cc"] == CHARGE                       # cliente paga UMA vez; falha anterior nao cobra
    assert sorted(c["decision"] for c in led.charges(pid)) == ["charged", "technical_failure"]


# ================================================================= composicao em revisao
def test_video_too_short_pauses_for_review_keeping_the_reserve(settings, tmp_path, photo_product, monkeypatch):
    o, wid = funded(settings, tmp_path, fal_script=FalSimScript(video_seconds=9.0))
    pid = new(o, photo_product, wid=wid)
    assert o.run(pid) == PS.PAUSED and o.db.production(pid)["pause_code"] == fp.COMPOSE_REVIEW
    assert not (delivery(o, pid) / "final.mp4").exists() and Ledger(o.db).charges(pid) == []
    for k, v in (("STUDIO_FAL_TARGET_S", "9"), ("STUDIO_FAL_MIN_S", "8"), ("STUDIO_FAL_MAX_S", "10")):
        monkeypatch.setenv(k, v)                                           # decisao do admin: aceitar a janela real
    o.db.resume_production(pid)
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW and o.fal_gen.submit_count == 1


# ================================================================= custo real (sem novo debito)
class FakeBilling:
    simulated = False

    def __init__(self, total=1.7):
        self.total, self.calls = total, []

    def reconcile_cost(self, ids):
        self.calls.append(ids)
        return self.total


def test_reconcile_records_supplier_cost_without_any_new_debit(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path)
    pid = new(o, photo_product, wid=wid)
    o.run(pid)
    att = o.db.attempts(pid)[0]
    o.db.update_attempt(att["id"], simulated=0)            # como se fosse uma execucao real
    led = Ledger(o.db)
    entries, bal = o.db.conn.execute("SELECT COUNT(*) FROM credit_entries").fetchone()[0], led.balance(wid)
    gen = FakeBilling(1.7)
    out = fp.reconcile_costs(o.db, gen, pid=pid)
    assert out[0]["status"] == "ok" and gen.calls[0] == [att["remote_op_id"]]
    a2 = o.db.attempt(att["id"])
    assert a2["confirmed_cost_usd"] == 1.7 and a2["cost_reconciled_at"] and a2["estimated_cost_usd"] == 2.0
    o._settle(pid)
    assert o.db.conn.execute("SELECT COUNT(*) FROM credit_entries").fetchone()[0] == entries and led.balance(wid) == bal
    assert fp.reconcile_costs(o.db, gen, pid=pid) == []                   # idempotente
    assert [c["cost_usd"] for c in led.charges(pid)] == [2.0]             # o cliente segue pagando o fixo por estilo


def test_reconcile_skips_attempts_not_yet_decided_in_the_ledger(settings, tmp_path, photo_product):
    o, wid = funded(settings, tmp_path, fal_script=FalSimScript(missing={"image:hero"}))
    pid = new(o, photo_product, wid=wid)
    o.run(pid)
    o.db.update_attempt(o.db.attempts(pid)[0]["id"], simulated=0)
    gen = FakeBilling()
    assert fp.reconcile_costs(o.db, gen) == [] and gen.calls == []


# ================================================================= retencao: so os intermediarios
def _complete_old(o, pid, days=30):
    o.final_decision(pid, True)
    old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    o.db.conn.execute("UPDATE productions SET updated_at=? WHERE id=?", (old, pid))


def test_cleanup_removes_only_raw_intermediates_and_keeps_delivery_and_history(settings, tmp_path, photo_product):
    o = make(settings, tmp_path)
    pid = new(o, photo_product)
    o.run(pid)
    _complete_old(o, pid)
    root = o.s.data_dir / "productions" / pid
    raw = sorted(p.name for p in (root / "workflow/attempt_01").iterdir())
    assert "result.json" in raw and "video.mp4" in raw
    before = {p.name: p.read_bytes() for p in (root / "delivery").iterdir() if p.is_file()}
    r = fp.cleanup_intermediates(o.s.data_dir, o.db, 7)
    assert r["removed"] >= 2 and r["freed_bytes"] > 0
    assert [p.name for p in (root / "workflow/attempt_01").iterdir()] == ["result.json"]
    after = {p.name: p.read_bytes() for p in (root / "delivery").iterdir() if p.is_file()}
    assert before == after                                                # delivery/ identica, byte a byte
    assert fp.cleanup_intermediates(o.s.data_dir, o.db, 7)["removed"] == 0


def test_cleanup_respects_retention_and_never_touches_gemini_productions(settings, tmp_path, photo_product):
    o = make(settings, tmp_path)
    pid = new(o, photo_product)
    o.run(pid)
    o.final_decision(pid, True)                                           # recente: dentro da retencao
    assert fp.cleanup_intermediates(o.s.data_dir, o.db, 7)["removed"] == 0
    g = o.db.create_production(mode="simulated", format_id="x", product={"name": "g"}, profiles={}, budget_usd=1)
    o.db.set_production_status(g, PS.CANCELLED, "x")
    o.db.conn.execute("UPDATE productions SET updated_at='2020-01-01T00:00:00+00:00' WHERE id=?", (g,))
    gdir = o.s.data_dir / "productions" / g / "workflow" / "attempt_01"
    gdir.mkdir(parents=True)
    (gdir / "video.mp4").write_bytes(b"x")
    assert fp.cleanup_intermediates(o.s.data_dir, o.db, 7)["removed"] == 0 and (gdir / "video.mp4").exists()


def test_cleanup_path_guard_never_allows_delivery_or_anything_outside(settings, tmp_path, photo_product):
    o = make(settings, tmp_path)
    pid = new(o, photo_product)
    o.run(pid)
    root = o.s.data_dir / "productions" / pid
    d = root / "delivery"
    for bad in (d / "final.mp4", d / "product_image_01.jpg", root / "workflow/attempt_01/result.json",
                root / "workflow/attempt_01/../../delivery/final.mp4", root / "workflow/delivery/final.mp4",
                root / "workflow/attempt_01/../attempt_01/result.json", root / "inputs/workflow_photo.jpg",
                tmp_path / "foto.png", root / "workflow/not_an_attempt/video.mp4"):
        assert fp._safe_intermediate(root, bad) is False, bad
    assert fp._safe_intermediate(root, root / "workflow/attempt_01/video.mp4") is True
    # link simbolico apontando para delivery/: resolve antes de decidir (pula o teste onde o SO nao permite criar)
    link = root / "workflow" / "attempt_01" / "link.mp4"
    try:
        os.symlink(d / "final.mp4", link)
    except (OSError, NotImplementedError):
        link = None                  # sem permissao para criar link simbolico neste sistema: o resto do teste segue
    if link is not None:
        assert fp._safe_intermediate(root, link) is False
    _complete_old(o, pid)
    fp.cleanup_intermediates(o.s.data_dir, o.db, 7)
    assert (d / "final.mp4").is_file() and len(list(d.glob("product_image_*.jpg"))) == 1


def test_cleanup_never_runs_on_active_or_paused_productions(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(missing={"image:hero"}))
    pid = new(o, photo_product)
    o.run(pid)                                                            # pausada (entrega incompleta): ainda precisa dos brutos
    o.db.conn.execute("UPDATE productions SET updated_at='2020-01-01T00:00:00+00:00' WHERE id=?", (pid,))
    assert fp.cleanup_intermediates(o.s.data_dir, o.db, 7)["removed"] == 0
    assert (o.s.data_dir / "productions" / pid / "workflow/attempt_01/video.mp4").is_file()


# ================================================================= o que a interface enxerga
def test_view_shows_finalizing_for_an_incomplete_delivery_and_hides_technical_detail(settings, tmp_path, photo_product):
    from studio.web import view
    o = make(settings, tmp_path, fal_script=FalSimScript(missing={"image:hero"}))
    pid = new(o, photo_product)
    o.run(pid)
    P = view.snapshot(o.s, o.db, pid)["production"]
    assert P["engine"] == "fal" and P["status"] == "paused" and P["fal"]["finalizing"] is True
    assert P["delivery_status"] == "incomplete" and P["fal"]["missing_images"] == ["hero"]
    assert P["delivery"] == {} and P["fal"]["image"]["url"] is None      # nada publicado
    assert "finalizando" in P["reason"] and "fal" not in P["reason"].lower().replace("finalizando", "")
    assert P["pause_code"] == fp.INCOMPLETE                                                 # o admin enxerga o codigo


def test_view_lists_the_package_when_complete(settings, tmp_path, photo_product):
    from studio.web import view
    o = make(settings, tmp_path, fal_script=FalSimScript(title="Titulo do video", caption="Legenda do video."))
    pid = new(o, photo_product)
    o.run(pid)
    P = view.snapshot(o.s, o.db, pid)["production"]
    assert set(P["delivery"]) == {"final.mp4", "product_image_01.jpg", "cover.jpg", "caption.txt"}
    assert P["fal"]["title"] == "Titulo do video" and P["fal"]["caption"] == "Legenda do video."
    assert P["fal"]["image"]["label"] == "Hero Shot" and P["fal"]["image"]["url"]
    assert P["fal"]["finalizing"] is False and P["fal"]["style_label"] == "Escuro"


def test_next_video_summary_is_the_fixed_package_price_per_style(settings, tmp_path, photo_product):
    from studio.web import view
    o, wid = funded(settings, tmp_path)
    pid = new(o, photo_product, wid=wid, confirm=False)
    sm = view.snapshot(o.s, o.db, pid, workspace_id=wid)["production"]["confirmation"]["summary"]
    assert sm["engine"] == "fal" and sm["style"] == "dark" and sm["total_cc"] == CHARGE and sm["scenes"] == 0
    assert sm["included_adjustments_per_scene"] == 0


def test_caption_txt_keeps_emoji_in_utf8_when_the_text_comes_in_a_markdown_fence(settings, tmp_path, photo_product):
    raw = "```json\n" + json.dumps({"title": "Copo térmico 🧊", "caption": "Gelado o dia todo 💙 #copo"}, ensure_ascii=False) + "\n```"
    o = make(settings, tmp_path, fal_script=FalSimScript(output_text=raw))
    pid = new(o, photo_product)
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW
    cap = (delivery(o, pid) / "caption.txt").read_bytes().decode("utf-8")           # UTF-8 puro, sem perda
    assert cap.startswith("Copo térmico 🧊\n\nGelado o dia todo 💙 #copo")
    meta = json.loads((delivery(o, pid) / "delivery_meta.json").read_text(encoding="utf-8"))
    assert meta["title"] == "Copo térmico 🧊" and meta["text_status"] == "ok"


def test_result_json_keeps_the_raw_envelope_for_the_first_real_round(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(output_text="```json\n{\"title\": \"T\", \"caption\": \"C\"}\n```"))
    pid = new(o, photo_product)
    assert o.run(pid) == PS.AWAITING_FINAL_REVIEW
    f = o.s.data_dir / "productions" / pid / "workflow/attempt_01/result.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    raw = data["raw"]
    assert set(raw) == {"output", "nodes"} and set(raw["output"]) == {"video", "images", "output"}   # envelope bruto, 3 campos
    assert raw["output"]["output"].startswith("```json") and raw["nodes"]["sim"]["request_id"] == data["request_id"]
    assert data["package"]["title"] == "T"
    # e a limpeza de intermediarios nunca apaga o result.json
    assert fp._safe_intermediate(o.s.data_dir / "productions" / pid, f) is False


def test_photo_recovery_refused_by_the_provider_ends_as_an_incomplete_delivery(settings, tmp_path, photo_product):
    o = make(settings, tmp_path, fal_script=FalSimScript(missing={"image:hero"}, recoverable={"hero"}))
    orig = o.fal_gen.recover_artifact

    def refuse(art, style="light"):
        raise __import__("studio.providers.base", fromlist=["x"]).PermanentError("recuperacao de foto pelo no ainda A CONFIRMAR")
    o.fal_gen.recover_artifact = refuse
    pid = new(o, photo_product)
    assert o.run(pid) == PS.PAUSED and o.db.production(pid)["pause_code"] == fp.INCOMPLETE       # manual: nada reenviado
    assert o.fal_gen.submit_count == 1 and any(e["type"] == "fal_recover" and "falhou" in e["message"] for e in o.db.events(pid))
    o.fal_gen.recover_artifact = orig
