"""Workflow simulado: pacote sintetico (1 video com audio, 1 foto, JSON de legenda) e injecao de falhas. Usa FFmpeg
(lavfi), sem rede."""

from __future__ import annotations

import json

import pytest

from studio import package_files as pf
from studio.ffmpeg import FFmpeg
from studio.providers.base import OpState, PermanentError, TransientError, WorkflowRequest
from studio.providers.fal import UncertainSubmit
from studio.providers.simulated_fal import FalSimScript, SimulatedFalWorkflow

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


@pytest.fixture
def ff(settings):
    return FFmpeg(settings.ffmpeg_bin, settings.ffprobe_bin, settings.font_file, "ultrafast")


def make(settings, ff, **kw):
    return SimulatedFalWorkflow(settings.data_dir, ff, FalSimScript(**kw))


def run(sim, tmp_path, style="dark"):
    photo = tmp_path / "foto.jpg"
    photo.write_bytes(b"\xff\xd8\xff" + b"0" * 50)
    info = sim.submit_full(WorkflowRequest(style=style, image_path=photo))
    return info, sim.poll(info.request_id, info.meta)


def test_complete_synthetic_package(settings, ff, tmp_path):
    sim = make(settings, ff)
    info, res = run(sim, tmp_path)
    assert res.state == OpState.SUCCEEDED
    pkg = res.package
    assert pkg.missing() == [] and pkg.failure_kind() is None and pkg.warnings == []
    probe = ff.probe(pkg.video.path)
    assert (probe["width"], probe["height"]) == (540, 960) and abs(probe["duration_s"] - 15.0) < 0.2
    assert probe["has_audio"]                                       # a narracao ja vem embutida no video
    pf.validate("video", sim.fetch(pkg.video))
    assert pf.validate("image", sim.fetch(pkg.hero)) == {"width": 720, "height": 1280}
    assert pkg.title and pkg.caption
    assert not hasattr(pkg, "music") and not hasattr(pkg, "narration")


def test_video_without_audio_can_be_injected(settings, ff, tmp_path):
    _, res = run(make(settings, ff, video_has_audio=False), tmp_path)
    assert res.state == OpState.SUCCEEDED and not ff.probe(res.package.video.path)["has_audio"]


@pytest.mark.parametrize("comp,kind", [("video", "technical"), ("image:hero", "incomplete")])
def test_inject_missing_component(settings, ff, tmp_path, comp, kind):
    _, res = run(make(settings, ff, missing={comp}), tmp_path)
    assert res.state == OpState.SUCCEEDED and res.package.failure_kind() == kind


@pytest.mark.parametrize("raw", ["nao e json", "", '{"title": "", "caption": ""}'])
def test_invalid_or_empty_caption_json_is_a_warning_not_invented_text(settings, ff, tmp_path, raw):
    _, res = run(make(settings, ff, output_text=raw), tmp_path)
    pkg = res.package
    assert pkg.failure_kind() is None and (pkg.title, pkg.caption) == ("", "") and pkg.warnings


def test_caption_json_comes_through_the_same_parser_as_the_real_workflow(settings, ff, tmp_path):
    raw = json.dumps({"title": "T", "caption": "C"})
    _, res = run(make(settings, ff, output_text=raw), tmp_path)
    assert (res.package.title, res.package.caption) == ("T", "C")


def test_corrupt_image_fails_byte_validation(settings, ff, tmp_path):
    _, res = run(make(settings, ff, corrupt={"image:hero"}), tmp_path)
    with pytest.raises(pf.PackageFileError):
        pf.validate("image", res.package.hero.path.read_bytes())


def test_recoverable_image_is_handed_back_only_via_node_recovery(settings, ff, tmp_path):
    sim = make(settings, ff, missing={"image:hero"}, recoverable={"hero"})
    _, res = run(sim, tmp_path)
    art = res.package.hero
    assert art.path is None and art.recover is not None                  # nao veio no pacote
    got = sim.recover_artifact(art)
    assert got is not None and pf.validate("image", sim.fetch(got))["width"] == 720
    assert sim.submit_count == 1                                          # nenhum novo submit


def test_unrecoverable_image_stays_missing(settings, ff, tmp_path):
    sim = make(settings, ff, missing={"image:hero"})
    _, res = run(sim, tmp_path)
    assert res.package.hero is None and sim.recover_calls == 0


def test_polls_before_done_and_state_survives_a_new_instance(settings, ff, tmp_path):
    sim = make(settings, ff, polls_before_done=2)
    info, res = run(sim, tmp_path)
    assert res.state == OpState.RUNNING
    sim2 = make(settings, ff)                      # "reinicio": outro objeto, mesmo disco
    assert sim2.poll(info.request_id).state == OpState.RUNNING
    assert sim2.poll(info.request_id).state == OpState.SUCCEEDED
    assert sim2.submit_count == 0


@pytest.mark.parametrize("kind,exc", [("transient", TransientError), ("permanent", PermanentError),
                                      ("uncertain", UncertainSubmit)])
def test_scripted_submit_failures(settings, ff, tmp_path, kind, exc):
    sim = make(settings, ff, submit_failures=[kind])
    photo = tmp_path / "f.jpg"
    photo.write_bytes(b"\xff\xd8\xff")
    with pytest.raises(exc):
        sim.submit_full(WorkflowRequest("dark", photo))
    assert sim.submit_count == 0


def test_error_on_complete(settings, ff, tmp_path):
    _, res = run(make(settings, ff, error_on_complete="no falhou"), tmp_path)
    assert res.state == OpState.FAILED and "no falhou" in res.error


def test_package_file_validation_rejects_wrong_bytes():
    with pytest.raises(pf.PackageFileError):
        pf.validate("video", b"x" * 30000)
    with pytest.raises(pf.PackageFileError):
        pf.validate("image", b"\xff\xd8" + b"0" * 9000)
    with pytest.raises(pf.PackageFileError):
        pf.validate("image", b"")
