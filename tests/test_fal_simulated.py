"""Workflow simulado: pacote sintetico completo e injecao de falhas por componente. Usa FFmpeg (lavfi), sem rede."""

from __future__ import annotations

import pytest

from studio import fal_contract as fc, package_files as pf
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
    assert pkg.missing() == [] and pkg.failure_kind() is None
    probe = ff.probe(pkg.video.path)
    assert (probe["width"], probe["height"]) == (540, 960) and abs(probe["duration_s"] - 15.0) < 0.2
    assert ff.probe(pkg.narration.path)["has_audio"] and ff.probe(pkg.music.path)["has_audio"]
    pf.validate("video", sim.fetch(pkg.video))
    pf.validate("narration", sim.fetch(pkg.narration))
    pf.validate("music", sim.fetch(pkg.music))


def test_three_distinct_decodable_jpgs(settings, ff, tmp_path):
    _, res = run(make(settings, ff), tmp_path)
    datas = [res.package.images[r].path.read_bytes() for r in fc.ROLES]
    assert len(set(datas)) == 3
    for d in datas:
        assert pf.validate("image", d) == {"width": 720, "height": 1280}


@pytest.mark.parametrize("comp,kind", [("video", "technical"), ("narration", "technical"), ("music", None),
                                       ("image:hero", "incomplete"), ("image:lifestyle", "incomplete"),
                                       ("image:details", "incomplete")])
def test_inject_missing_component(settings, ff, tmp_path, comp, kind):
    _, res = run(make(settings, ff, missing={comp}), tmp_path)
    assert res.state == OpState.SUCCEEDED and comp in res.package.missing()
    assert res.package.failure_kind() == kind


def test_corrupt_image_fails_byte_validation(settings, ff, tmp_path):
    _, res = run(make(settings, ff, corrupt={"image:details"}), tmp_path)
    ok = pf.validate("image", res.package.images["hero"].path.read_bytes())
    assert ok["height"] == 1280
    with pytest.raises(pf.PackageFileError):
        pf.validate("image", res.package.images["details"].path.read_bytes())


def test_recoverable_image_is_handed_back_only_via_node_recovery(settings, ff, tmp_path):
    sim = make(settings, ff, missing={"image:hero"}, recoverable={"hero"})
    _, res = run(sim, tmp_path)
    art = res.package.images["hero"]
    assert art.path is None and art.recover is not None                  # nao veio no pacote
    got = sim.recover_artifact(art)
    assert got is not None and pf.validate("image", sim.fetch(got))["width"] == 720
    assert sim.submit_count == 1                                          # nenhum novo submit


def test_unrecoverable_image_stays_missing(settings, ff, tmp_path):
    sim = make(settings, ff, missing={"image:details"})
    _, res = run(sim, tmp_path)
    assert res.package.images["details"] is None and sim.recover_calls == 0


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
        pf.validate("narration", b"y" * 5000)
    with pytest.raises(pf.PackageFileError):
        pf.validate("image", b"\xff\xd8" + b"0" * 9000)
    with pytest.raises(pf.PackageFileError):
        pf.validate("image", b"")
