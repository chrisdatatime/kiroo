"""Composicao do pacote fal.ai: planejamento puro (sem FFmpeg) e montagem real sobre amostras sinteticas (lavfi)."""

from __future__ import annotations

import dataclasses

import pytest

from studio.agents import composer as cp
from studio.agents.composer import ComposeConfig, ComposeNeedsReview, plan_composition
from studio.ffmpeg import FFmpeg

from .conftest import requires_ffmpeg

CFG = ComposeConfig()


# ---------------------------------------------------------------- planejamento puro
def test_plan_copy_when_within_tolerance():
    p = plan_composition(15.1, 540, 960, 11.5, CFG)
    assert p.video_action == "copy" and p.atempo == 1.0 and p.final_s == 15.1


def test_plan_cut_long_video_with_reencode():
    p = plan_composition(18.0, 540, 960, 11.5, CFG)
    assert p.video_action == "cut" and p.final_s == 15.0


def test_plan_between_tolerance_and_window_is_normalized_to_target():
    assert plan_composition(15.8, 540, 960, 11.5, CFG).video_action == "cut"
    assert plan_composition(14.2, 540, 960, 11.5, CFG).video_action == "extend"


def test_plan_extend_short_video_up_to_two_seconds():
    p = plan_composition(13.2, 540, 960, 11.5, CFG)
    assert p.video_action == "extend" and abs(p.pad_s - 1.8) < 1e-6 and p.final_s == 15.0


def test_plan_video_too_short_needs_review():
    with pytest.raises(ComposeNeedsReview) as e:
        plan_composition(12.0, 540, 960, 11.5, CFG)
    assert e.value.code == "video_too_short"


def test_plan_not_vertical_needs_review():
    with pytest.raises(ComposeNeedsReview) as e:
        plan_composition(15.0, 1920, 1080, 11.5, CFG)
    assert e.value.code == "video_not_vertical"


def test_plan_narration_that_fits_is_untouched():
    p = plan_composition(15.0, 540, 960, 14.2, CFG)       # espaco = 15 - 0,3 - 0,5 = 14,2
    assert p.atempo == 1.0


def test_plan_small_overflow_uses_atempo_within_the_cap():
    p = plan_composition(15.0, 540, 960, 15.0, CFG)       # precisa de ~x1,056
    assert 1.05 < p.atempo <= 1.08 and p.narration_s <= 14.2 + 1e-6


def test_plan_narration_beyond_the_cap_needs_review_and_never_cuts():
    with pytest.raises(ComposeNeedsReview) as e:
        plan_composition(15.0, 540, 960, 16.0, CFG)
    assert e.value.code == "narration_too_long" and "nada foi cortado" in str(e.value)


def test_atempo_cap_is_configurable():
    cfg = dataclasses.replace(CFG, atempo_max=1.2)
    assert plan_composition(15.0, 540, 960, 16.0, cfg).atempo > 1.08


def test_config_from_env():
    c = ComposeConfig.from_env({"STUDIO_FAL_ATEMPO_MAX": "1.15", "STUDIO_FAL_TARGET_S": "12"})
    assert c.atempo_max == 1.15 and c.target_s == 12.0
    assert ComposeConfig.from_env({"STUDIO_FAL_ATEMPO_MAX": "abc"}).atempo_max == 1.08


# ---------------------------------------------------------------- caption
def test_caption_uses_name_when_present_and_description_when_empty():
    fmt = {"disclosure": {"caption_text": "Publicidade."}, "caption": {"hashtags": ["#a"], "max_chars": 2200}}
    t, w = cp.build_caption("Copo azul", "Descricao do workflow.", fmt)
    assert t.splitlines()[0] == "Copo azul" and "Descricao do workflow." in t and "Publicidade." in t and w
    t2, _ = cp.build_caption("", "Copo azul de aco inox. Muito bonito.", fmt)
    assert t2.splitlines()[0].startswith("Copo azul de aco inox")


# ---------------------------------------------------------------- montagem real
@pytest.fixture
def ff(settings):
    return FFmpeg(settings.ffmpeg_bin, settings.ffprobe_bin, settings.font_file, "ultrafast")


def vid(ff, p, seconds, size="540x960"):
    ff.run(["-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}", "-c:v", "libx264",
            "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an", str(p)])
    return p


def nar(ff, p, seconds):
    ff.run(["-f", "lavfi", "-i", f"aevalsrc='0.45*sin(2*PI*190*t)*(0.55+0.45*sin(2*PI*3.3*t))':s=48000:d={seconds}",
            "-ac", "1", str(p)])
    return p


def mus(ff, p, seconds=20):
    ff.run(["-f", "lavfi", "-i", "aevalsrc='0.5*(sin(2*PI*261.6*t)+sin(2*PI*329.6*t)+sin(2*PI*392*t))/3':s=48000:"
                               f"d={seconds}", "-ac", "2", str(p)])
    return p


@pytest.fixture
def media(ff, tmp_path):
    return {"video": vid(ff, tmp_path / "v.mp4", 15.0), "narr": nar(ff, tmp_path / "n.wav", 11.5),
            "music": mus(ff, tmp_path / "m.wav")}


@requires_ffmpeg
def test_compose_full_package_keeps_video_stream_and_ducks_music(ff, media, tmp_path):
    out = tmp_path / "out" / "final.mp4"
    rep = cp.compose(ff, media["video"], media["narr"], media["music"], out, tmp_path / "work", CFG)
    info = ff.probe(out)
    assert abs(info["duration_s"] - 15.0) < 0.3 and (info["width"], info["height"]) == (540, 960) and info["has_audio"]
    assert rep.plan.video_action == "copy" and info["video_codec"] == "h264"
    assert rep.music and rep.duck_db is not None and rep.duck_db >= 10.0           # trilha >= 10 dB abaixo da fala
    # conferencia independente do ducking no arquivo final: depois da fala a trilha volta (media sobe)
    speech = cp.segment_mean_db(ff, out, 1.0, 9.0)
    tail = cp.segment_mean_db(ff, out, 13.0, 1.0)
    assert speech is not None and tail is not None and speech > tail
    assert -30 < rep.checks["mean_volume_db"] < -8


@requires_ffmpeg
def test_compose_copy_is_really_a_stream_copy(ff, media, tmp_path):
    out = tmp_path / "f.mp4"
    cp.compose(ff, media["video"], media["narr"], None, out, tmp_path / "w", CFG)
    a = ff.run(["-i", str(media["video"]), "-map", "0:v", "-c", "copy", "-f", "md5", "-"]).stdout.strip()
    b = ff.run(["-i", str(out), "-map", "0:v", "-c", "copy", "-f", "md5", "-"]).stdout.strip()
    assert a == b                                          # mesmos pacotes de video: sem recodificar


@requires_ffmpeg
def test_compose_narration_that_fits_has_no_atempo(ff, media, tmp_path):
    rep = cp.compose(ff, media["video"], media["narr"], media["music"], tmp_path / "f.mp4", tmp_path / "w", CFG)
    assert rep.plan.atempo == 1.0


@requires_ffmpeg
def test_compose_narration_needing_atempo(ff, media, tmp_path):
    long_nar = nar(ff, tmp_path / "n2.wav", 14.9)
    rep = cp.compose(ff, media["video"], long_nar, media["music"], tmp_path / "f.mp4", tmp_path / "w", CFG)
    assert 1.0 < rep.plan.atempo <= 1.08 and abs(rep.duration_s - 15.0) < 0.3
    assert any("acelerada" in w for w in rep.warnings)


@requires_ffmpeg
def test_compose_narration_that_does_not_fit_pauses_and_delivers_nothing(ff, media, tmp_path):
    too_long = nar(ff, tmp_path / "n3.wav", 16.5)
    out = tmp_path / "f.mp4"
    with pytest.raises(ComposeNeedsReview) as e:
        cp.compose(ff, media["video"], too_long, media["music"], out, tmp_path / "w", CFG)
    assert e.value.code == "narration_too_long" and not out.exists()


@requires_ffmpeg
def test_compose_long_video_is_cut_with_reencode(ff, media, tmp_path):
    long_v = vid(ff, tmp_path / "v18.mp4", 18.0)
    rep = cp.compose(ff, long_v, media["narr"], media["music"], tmp_path / "f.mp4", tmp_path / "w", CFG)
    assert rep.plan.video_action == "cut" and abs(rep.duration_s - 15.0) < 0.3


@requires_ffmpeg
def test_compose_short_video_is_extended_with_last_frame(ff, media, tmp_path):
    short_v = vid(ff, tmp_path / "v13.mp4", 13.4)
    rep = cp.compose(ff, short_v, media["narr"], media["music"], tmp_path / "f.mp4", tmp_path / "w", CFG)
    assert rep.plan.video_action == "extend" and abs(rep.duration_s - 15.0) < 0.3


@requires_ffmpeg
def test_compose_video_far_too_short_needs_review(ff, media, tmp_path):
    with pytest.raises(ComposeNeedsReview, match="curto"):
        cp.compose(ff, vid(ff, tmp_path / "v9.mp4", 9.0), media["narr"], None, tmp_path / "f.mp4", tmp_path / "w", CFG)


@requires_ffmpeg
def test_compose_without_music_is_allowed(ff, media, tmp_path):
    rep = cp.compose(ff, media["video"], media["narr"], None, tmp_path / "f.mp4", tmp_path / "w", CFG)
    assert not rep.music and rep.duck_db is None and ff.probe(rep.out)["has_audio"]


@requires_ffmpeg
def test_compose_music_that_cannot_be_ducked_enough_needs_review(ff, media, tmp_path):
    cfg = dataclasses.replace(CFG, duck_min_db=90.0)
    with pytest.raises(ComposeNeedsReview) as e:
        cp.compose(ff, media["video"], media["narr"], media["music"], tmp_path / "f.mp4", tmp_path / "w", cfg)
    assert e.value.code == "music_too_loud"


@requires_ffmpeg
def test_cover_is_extracted_near_the_end(ff, media, tmp_path):
    out = tmp_path / "f.mp4"
    cp.compose(ff, media["video"], media["narr"], None, out, tmp_path / "w", CFG)
    jpg = cp.make_cover(ff, out, tmp_path / "cover.jpg", CFG)
    from studio import package_files as pf
    assert pf.validate("image", jpg.read_bytes())["height"] == 960


@requires_ffmpeg
def test_validate_output_rejects_wrong_duration(ff, media, tmp_path):
    with pytest.raises(ComposeNeedsReview) as e:
        cp.validate_output(ff, vid(ff, tmp_path / "x.mp4", 8.0), CFG)
    assert e.value.code == "output_invalid"


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
