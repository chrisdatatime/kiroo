"""Preparo do video fal.ai: planejamento puro (sem FFmpeg) e verificacao real sobre amostras sinteticas (lavfi).

O workflow entrega UM mp4 com a narracao embutida; nao ha mixagem, trilha, ducking nem atempo."""

from __future__ import annotations

import dataclasses

import pytest

from studio.agents import composer as cp
from studio.agents.composer import ComposeConfig, ComposeNeedsReview, SourceInvalid, plan_composition
from studio.ffmpeg import FFmpeg

from .conftest import requires_ffmpeg

CFG = ComposeConfig()


# ---------------------------------------------------------------- planejamento puro
@pytest.mark.parametrize("seconds", [14.0, 14.5, 15.0, 15.8, 16.0])
def test_plan_copy_anywhere_inside_the_14_to_16_window(seconds):
    p = plan_composition(seconds, 540, 960, CFG)
    assert p.video_action == "copy" and p.final_s == seconds and p.pad_s == 0.0 and p.notes == []


def test_plan_cut_long_video_with_reencode():
    p = plan_composition(18.0, 540, 960, CFG)
    assert p.video_action == "cut" and p.final_s == 15.0 and p.notes
    assert plan_composition(16.2, 540, 960, CFG).video_action == "cut"


def test_plan_extend_short_video_up_to_two_seconds():
    p = plan_composition(13.2, 540, 960, CFG)
    assert p.video_action == "extend" and abs(p.pad_s - 1.8) < 1e-6 and p.final_s == 15.0
    assert plan_composition(13.0, 540, 960, CFG).video_action == "extend"


def test_plan_video_too_short_needs_review():
    with pytest.raises(ComposeNeedsReview) as e:
        plan_composition(12.0, 540, 960, CFG)
    assert e.value.code == "video_too_short"


def test_plan_not_vertical_needs_review():
    with pytest.raises(ComposeNeedsReview) as e:
        plan_composition(15.0, 1920, 1080, CFG)
    assert e.value.code == "video_not_vertical"


def test_config_from_env_and_no_narration_or_music_knobs():
    c = ComposeConfig.from_env({"STUDIO_FAL_TARGET_S": "12", "STUDIO_FAL_MIN_S": "10"})
    assert c.target_s == 12.0 and c.min_s == 10.0 and c.max_s == 16.0
    assert ComposeConfig.from_env({"STUDIO_FAL_TARGET_S": "abc"}).target_s == 15.0
    names = {f.name for f in dataclasses.fields(ComposeConfig)}
    assert not names & {"atempo_max", "music_gain_db", "duck_min_db", "loudness_lufs", "narration_offset_s"}
    assert not hasattr(cp, "segment_mean_db")


# ---------------------------------------------------------------- legenda
FMT = {"disclosure": {"caption_text": "Publicidade."}, "caption": {"hashtags": ["#a"], "max_chars": 2200}}


def test_caption_is_title_plus_caption_plus_disclosure():
    t, w = cp.build_caption("Copo azul", "Mantem gelado.", FMT)
    assert t == "Copo azul\n\nMantem gelado.\n\nPublicidade.\n#a" and w      # aviso: texto de modelo nao verificado


def test_caption_never_invents_text_when_the_workflow_returned_none():
    t, w = cp.build_caption("", "", FMT)
    assert t == "Publicidade.\n#a" and "sem titulo e sem legenda" in w[0]
    t, _ = cp.build_caption("So titulo", "", FMT)
    assert t.startswith("So titulo\n\nPublicidade.")
    assert cp.build_caption("", "", None)[0] == ""


# ---------------------------------------------------------------- verificacao real
@pytest.fixture
def ff(settings):
    return FFmpeg(settings.ffmpeg_bin, settings.ffprobe_bin, settings.font_file, "ultrafast")


def vid(ff, p, seconds, size="540x960", audio=True, tone=190):
    args = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone}:duration={seconds}", "-c:a", "aac"]
    else:
        args += ["-an"]
    ff.run([*args, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(p)])
    return p


@requires_ffmpeg
def test_compose_inside_the_window_is_a_real_stream_copy(ff, tmp_path):
    src = vid(ff, tmp_path / "v.mp4", 15.0)
    out = tmp_path / "out" / "final.mp4"
    rep = cp.compose(ff, src, out, tmp_path / "w", CFG)
    info = ff.probe(out)
    assert rep.plan.video_action == "copy" and info["has_audio"] and info["video_codec"] == "h264"
    assert abs(info["duration_s"] - 15.0) < 0.3 and (info["width"], info["height"]) == (540, 960)
    for m in ("0:v", "0:a"):                                   # mesmos pacotes de video E de audio: nada recodificado
        a = ff.run(["-i", str(src), "-map", m, "-c", "copy", "-f", "md5", "-"]).stdout.strip()
        b = ff.run(["-i", str(out), "-map", m, "-c", "copy", "-f", "md5", "-"]).stdout.strip()
        assert a == b, m


@requires_ffmpeg
def test_compose_keeps_a_16_second_video_without_reencoding(ff, tmp_path):
    rep = cp.compose(ff, vid(ff, tmp_path / "v16.mp4", 15.9), tmp_path / "f.mp4", tmp_path / "w", CFG)
    assert rep.plan.video_action == "copy" and abs(rep.duration_s - 15.9) < 0.3


@requires_ffmpeg
def test_compose_long_video_is_cut_with_fade_and_reencode_keeping_audio(ff, tmp_path):
    rep = cp.compose(ff, vid(ff, tmp_path / "v18.mp4", 18.0), tmp_path / "f.mp4", tmp_path / "w", CFG)
    info = ff.probe(rep.out)
    assert rep.plan.video_action == "cut" and abs(rep.duration_s - 15.0) < 0.3 and info["has_audio"]
    assert any("cortado" in w for w in rep.warnings)


@requires_ffmpeg
def test_compose_short_video_is_extended_with_last_frame_and_keeps_audio(ff, tmp_path):
    rep = cp.compose(ff, vid(ff, tmp_path / "v13.mp4", 13.4), tmp_path / "f.mp4", tmp_path / "w", CFG)
    assert rep.plan.video_action == "extend" and abs(rep.duration_s - 15.0) < 0.3 and ff.probe(rep.out)["has_audio"]


@requires_ffmpeg
def test_compose_video_far_too_short_needs_review(ff, tmp_path):
    out = tmp_path / "f.mp4"
    with pytest.raises(ComposeNeedsReview, match="curto"):
        cp.compose(ff, vid(ff, tmp_path / "v9.mp4", 9.0), out, tmp_path / "w", CFG)
    assert not out.exists()


@requires_ffmpeg
def test_video_without_audio_is_a_source_failure_and_nothing_is_produced(ff, tmp_path):
    silent = vid(ff, tmp_path / "mudo.mp4", 15.0, audio=False)
    out = tmp_path / "f.mp4"
    with pytest.raises(SourceInvalid) as e:
        cp.compose(ff, silent, out, tmp_path / "w", CFG)
    assert e.value.code == "no_audio_stream" and not out.exists()
    with pytest.raises(SourceInvalid):
        cp.check_source(ff, silent)


@requires_ffmpeg
def test_audio_only_file_has_no_video_stream(ff, tmp_path):
    wav = tmp_path / "a.m4a"
    ff.run(["-f", "lavfi", "-i", "sine=frequency=300:duration=15", "-c:a", "aac", str(wav)])
    with pytest.raises(SourceInvalid) as e:
        cp.check_source(ff, wav)
    assert e.value.code == "no_video_stream"


@requires_ffmpeg
def test_unreadable_file_is_a_source_failure(ff, tmp_path):
    junk = tmp_path / "x.mp4"
    junk.write_bytes(b"nao e video" * 5000)
    with pytest.raises(SourceInvalid) as e:
        cp.check_source(ff, junk)
    assert e.value.code == "video_unreadable"


@requires_ffmpeg
def test_cover_is_extracted_near_the_end(ff, tmp_path):
    out = tmp_path / "f.mp4"
    cp.compose(ff, vid(ff, tmp_path / "v.mp4", 15.0), out, tmp_path / "w", CFG)
    jpg = cp.make_cover(ff, out, tmp_path / "cover.jpg", CFG)
    from studio import package_files as pf
    assert pf.validate("image", jpg.read_bytes())["height"] == 960


@requires_ffmpeg
def test_validate_output_rejects_wrong_duration_and_missing_audio(ff, tmp_path):
    with pytest.raises(ComposeNeedsReview) as e:
        cp.validate_output(ff, vid(ff, tmp_path / "x.mp4", 8.0), CFG)
    assert e.value.code == "output_invalid" and "janela" in str(e.value)
    with pytest.raises(ComposeNeedsReview, match="sem audio"):
        cp.validate_output(ff, vid(ff, tmp_path / "y.mp4", 15.0, audio=False), CFG)


@requires_ffmpeg
def test_fit_image_downsizes_to_2048_and_never_upscales(ff, tmp_path):
    from studio import package_files as pf
    big = tmp_path / "big.png"
    ff.run(["-f", "lavfi", "-i", "color=c=blue:s=3000x2000", "-frames:v", "1", str(big)])
    out = ff.fit_image(big, tmp_path / "o" / "big.jpg", 2048)
    assert pf.jpeg_info(out.read_bytes()) == (2048, 1365)
    small = tmp_path / "small.png"
    ff.run(["-f", "lavfi", "-i", "color=c=red:s=800x600", "-frames:v", "1", str(small)])
    assert pf.jpeg_info(ff.fit_image(small, tmp_path / "s.jpg", 2048).read_bytes()) == (800, 600)
