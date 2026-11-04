import json
import logging

import pytest

from studio.ffmpeg import FFmpeg, FFmpegError
from studio.logs import RedactingFilter
from studio.models import ClipCut, EditPlan, TextOverlay
from studio.providers.simulated import SimulationScript, placeholder_png
from studio.states import ProductionStatus as PS
from studio.storage import ProductionStorage, StorageError

from .conftest import FAKE_KEY, create, drive_to_final, requires_ffmpeg


def _ff(settings):
    return FFmpeg(settings.ffmpeg_bin, settings.ffprobe_bin, settings.font_file, "ultrafast")


@requires_ffmpeg
def test_assembly_with_valid_files(settings, tmp_path):
    ff = _ff(settings)
    clips = []
    for i in range(3):
        img = tmp_path / f"s{i}.png"
        img.write_bytes(placeholder_png(str(i), 270, 480))
        clips.append(ff.still_to_clip(img, tmp_path / f"c{i}.mp4", 6, 270, 480, tone=(i == 1)))
    text = "Publicidade • IA: teste 'aspas' [colchetes], vírgula; ponto"  # caracteres especiais de filtro
    plan = EditPlan(clips=[ClipCut(scene_index=i + 1, source_path=str(c), start_s=0.5, duration_s=5) for i, c in enumerate(clips)],
                    overlays=[TextOverlay(text=text, start_s=0, end_s=15, position="top")])
    out = ff.assemble(plan, tmp_path / "final.mp4", tmp_path / "work")
    info = ff.probe(out)
    assert abs(info["duration_s"] - 15.0) < 0.15
    assert (info["width"], info["height"]) == (1080, 1920)
    assert info["has_audio"]
    levels = ff.audio_levels(out)
    assert levels["max_volume_db"] is None or levels["max_volume_db"] < -80  # trilha silenciosa; tom do take 2 descartado


@requires_ffmpeg
def test_assembly_rejects_missing_input(settings, tmp_path):
    plan = EditPlan(clips=[ClipCut(scene_index=1, source_path=str(tmp_path / "nao_existe.mp4"), start_s=0, duration_s=5)])
    with pytest.raises(FFmpegError):
        _ff(settings).assemble(plan, tmp_path / "x.mp4", tmp_path / "w")


@requires_ffmpeg
def test_audio_in_take_is_flagged(make_orch, product):
    orch = make_orch(SimulationScript(video_polls_before_done=0, video_with_audio=True))
    pid = create(orch, product)
    orch.run(pid)
    orch.approve(pid, 1, "image")
    orch.run(pid)
    reviews = [json.loads(r["result_json"]) for r in orch.db.reviews(pid, 1) if r["stage"] == "video"]
    assert reviews and reviews[0]["checks"]["audio"] == "problema"
    assert any("áudio audível" in i for i in reviews[0]["issues"])


@requires_ffmpeg
def test_full_simulated_flow_delivers_traceable_package(make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    assert drive_to_final(orch, pid) == PS.AWAITING_FINAL_REVIEW
    st = orch._storage(pid)
    d = st.path("delivery")
    for name in ("final.mp4", "cover.jpg", "caption.txt", "product.json", "script.md", "script.json", "sheet.json",
                 "review_report.md", "cost_report.md", "cost_report.json", "edit_plan.json"):
        assert (d / name).exists(), name
    for i in (1, 2, 3):
        assert (d / "approved" / f"scene_{i}_image.png").exists()
        assert (d / "approved" / f"scene_{i}_take.mp4").exists()
        assert st.path(f"prompts/scene_{i}_image_simulated.txt").exists()
    assert json.loads((d / "product.json").read_text(encoding="utf-8"))["affiliate_link"] == product.affiliate_link
    assert "MODO SIMULADO" in (d / "review_report.md").read_text(encoding="utf-8")
    meta = json.loads((d / "delivery_meta.json").read_text(encoding="utf-8"))
    assert meta["simulated"] is True
    caption = (d / "caption.txt").read_text(encoding="utf-8")
    assert "Publicidade" in caption and "500" not in caption
    # rastreabilidade: cada take aprovado aponta para a imagem aprovada que animou
    for s in orch.db.scenes(pid):
        vid = orch.db.attempt(s["approved_video_attempt"])
        img = orch.db.attempt(s["approved_image_attempt"])
        assert json.loads(vid["references_json"])[0]["sha256"] == img["output_sha256"]
    orch.final_decision(pid, True, "ok")
    assert orch.db.production(pid)["status"] == PS.COMPLETED


@requires_ffmpeg
def test_no_credentials_in_artifacts(make_orch, product, settings):
    orch = make_orch()
    pid = create(orch, product)
    drive_to_final(orch, pid)
    orch.db.close()
    hits = []
    for f in settings.data_dir.rglob("*"):
        if f.is_file() and FAKE_KEY.encode() in f.read_bytes():
            hits.append(f)
    assert hits == []


def test_log_redaction():
    record = logging.LogRecord("studio", logging.INFO, __file__, 1, "chave=%s", (FAKE_KEY,), None)
    RedactingFilter([FAKE_KEY]).filter(record)
    assert FAKE_KEY not in record.getMessage() and "***" in record.getMessage()


def test_settings_repr_hides_key(settings):
    assert FAKE_KEY not in repr(settings)


def test_path_traversal_and_file_validation(tmp_path):
    st = ProductionStorage(tmp_path, "prod_abc123")
    with pytest.raises(StorageError):
        st.path("..", "..", "outside.txt")
    fake = tmp_path / "fake.png"
    fake.write_bytes(b"not a png")
    with pytest.raises(StorageError):
        st.import_file(fake, "inputs")
    with pytest.raises(StorageError):
        ProductionStorage(tmp_path, "../evil")
    exe = tmp_path / "x.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(StorageError):
        st.import_file(exe, "inputs")


def test_original_reference_files_are_not_moved(make_orch, product, refs_dir):
    before = sorted(p.name for p in refs_dir.iterdir())
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    assert sorted(p.name for p in refs_dir.iterdir()) == before
