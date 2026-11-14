"""Contrato canonico do pacote: parser sobre o mapeamento externo, com pacote completo e com cada falha parcial."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio import fal_contract as fc
from studio.config import PROJECT_ROOT

from .fal_fixtures import sample_contract, sample_result

C = sample_contract()


def parse(**kw):
    return fc.parse_result(sample_result(**kw), "dark", C)


def test_complete_package():
    pkg = parse()
    assert pkg.missing() == [] and pkg.failure_kind() is None and pkg.warnings == []
    assert pkg.video.url.endswith("final.mp4") and pkg.hero.url.endswith("hero.jpg")
    assert pkg.title == "Copo azul de aco inox" and pkg.caption.startswith("Mantem")


def test_intermediate_audio_output_is_ignored():
    pkg = parse()
    assert not hasattr(pkg, "narration") and not hasattr(pkg, "music")
    assert "voz.mp3" not in repr(fc.package_to_dict(pkg))


def test_without_envelope_the_result_is_the_output():
    pkg = fc.parse_result(sample_result(envelope=False), "light", C)
    assert pkg.failure_kind() is None and pkg.nodes == {} and pkg.hero.recover is None


def test_envelope_gives_recovery_info_for_the_hero():
    assert parse().hero.recover == {"endpoint": "fal-ai/img/a", "request_id": "r-hero", "path": "image.url"}


def test_missing_video_is_technical_failure():
    pkg = parse(drop=["video"])
    assert pkg.missing() == ["video"] and pkg.failure_kind() == "technical"


def test_hero_missing_url_keeps_only_the_recovery_handle():
    pkg = parse(drop=["images.0"])
    assert pkg.hero.url is None and pkg.hero.recover is not None      # a pipeline tenta recuperar pelo no


def test_missing_hero_without_recovery_info_is_incomplete():
    pkg = fc.parse_result(sample_result(drop=["images.0"], envelope=False), "dark", C)
    assert pkg.missing() == ["hero"] and pkg.failure_kind() == "incomplete"


def test_missing_text_is_only_a_warning():
    pkg = parse(drop=["output"])
    assert pkg.failure_kind() is None and pkg.title == "" and pkg.caption == "" and pkg.warnings


@pytest.mark.parametrize("raw", ["isto nao e json {", "", "   ", "[1, 2]", "null", '{"title": "", "caption": ""}',
                                 '{"title": 3, "caption": null}'])
def test_invalid_or_empty_text_yields_no_text_and_a_warning(raw):
    pkg = parse(text=raw)
    assert (pkg.title, pkg.caption) == ("", "") and pkg.failure_kind() is None and len(pkg.warnings) == 1


def test_text_with_only_one_field_keeps_it_and_warns():
    pkg = parse(text='{"title": "Copo", "caption": ""}')
    assert (pkg.title, pkg.caption) == ("Copo", "") and "legenda" in pkg.warnings[0]
    pkg = parse(text='{"title": "", "caption": "So legenda"}')
    assert (pkg.title, pkg.caption) == ("", "So legenda") and "titulo" in pkg.warnings[0]


def test_text_in_a_code_fence_or_already_decoded_is_read():
    assert fc.parse_text_output('```json\n{"title": "A", "caption": "B"}\n```')[:2] == ("A", "B")
    assert fc.parse_text_output('Aqui vai: {"title": "A", "caption": "B"} fim')[:2] == ("A", "B")
    assert fc.parse_text_output({"title": " A ", "caption": "B"})[:2] == ("A", "B")


def test_non_url_values_are_ignored():
    r = sample_result(envelope=False)
    r["video"]["url"] = "file:///etc/passwd"
    r["images"][0]["url"] = "javascript:alert(1)"
    pkg = fc.parse_result(r, "dark", C)
    assert pkg.video is None and pkg.hero is None and pkg.missing() == ["video", "hero"]


def test_package_roundtrip_through_result_json():
    pkg = parse(text="invalido")
    again = fc.package_from_dict(fc.package_to_dict(pkg))
    assert again.video.url == pkg.video.url and again.hero.recover == pkg.hero.recover and again.warnings == pkg.warnings


def test_get_path_is_safe():
    assert fc.get_path({"a": [{"b": 1}]}, "a.0.b") == 1
    for bad in ("a.5.b", "x.y", "", "A CONFIRMAR (Fase 0)", "a.b"):
        assert fc.get_path({"a": [{"b": 1}]}, bad) is None


def test_build_input_sends_only_the_image_url():
    assert fc.build_input(C, "dark", "https://x/y.jpg") == {"image_url": "https://x/y.jpg"}


def test_real_contract_confirmed_fields_and_open_items():
    real = fc.load_contract(PROJECT_ROOT / "profiles")
    for style in fc.STYLES:
        cfg = real["styles"][style]
        assert cfg["input"] == {"image_field": "image_url", "extra": {}}                  # so image_url
        assert cfg["output"] == {"video": "video.url", "image": "images.0.url", "text": "output"}
        assert all(k not in cfg["output"] for k in ("narration", "music", "description", "narration_text"))
        assert cfg["recover"] == {"hero": {"node_id": "node-oTeZSiC32m", "path": "images.0.url"}}
        pend = fc.placeholders(real, style)
        # confirmados saem de placeholders(); so restam recover.hero e o request_id por no do envelope
        assert len(pend) == 2 and all("A CONFIRMAR" in p for p in pend)
        assert "recover.hero" in pend[0] and "request_id" in pend[1]
        assert not any(k in p for p in pend for k in ("image_url", "video.url", "output.image", "indice"))
        assert fc.build_input(real, style, "https://x/y.jpg") == {"image_url": "https://x/y.jpg"}


# ---------------------------------------------------------------- forma real da resposta (fixture SINTETICA)
SHAPE = Path(__file__).parent / "fixtures" / "fal_shape" / "light_result.json"
REAL = fc.load_contract(PROJECT_ROOT / "profiles")


def shape():
    return json.loads(SHAPE.read_text(encoding="utf-8"))


def parse_shape(**over):
    r = {**shape(), **over}
    return fc.parse_result(r, "light", REAL)


def test_shape_fixture_is_synthetic_and_not_in_the_real_folder():
    raw = SHAPE.read_text(encoding="utf-8")
    assert "v3b.fal.media/files/b/example/" in raw and "fal_real" not in str(SHAPE)
    assert set(shape()) == {"video", "images", "output"}                  # so 3 campos de topo, sem audio/audio_2


def test_real_contract_reads_the_real_shape_with_a_json_fence():
    pkg = parse_shape()
    assert pkg.missing() == [] and pkg.failure_kind() is None
    assert pkg.video.url.endswith("video-claro.mp4") and pkg.hero.url.endswith("hero-claro.jpg")
    assert pkg.title == "Copo térmico azul 500 ml" and pkg.caption.startswith("Gelado o dia todo")
    assert "\U0001F9CA" in pkg.caption and "\U0001F499" in pkg.caption          # emoji preservado
    assert pkg.warnings == []


def test_response_without_audio_is_valid():
    r = shape()
    assert "audio" not in r and "audio_2" not in r
    assert parse_shape().failure_kind() is None


def test_extra_audio_outputs_are_ignored():
    pkg = parse_shape(audio={"url": "https://v3b.fal.media/files/b/example/a.mp3"},
                      audio_2={"url": "https://v3b.fal.media/files/b/example/b.mp3"})
    assert pkg.failure_kind() is None and pkg.warnings == []
    assert "a.mp3" not in repr(fc.package_to_dict(pkg)) and "b.mp3" not in repr(fc.package_to_dict(pkg))


def test_image_with_null_file_name_and_size_is_fine():
    img = shape()["images"][0]
    assert img["file_name"] is None and img["file_size"] is None
    pkg = parse_shape()
    assert pkg.hero.url and pkg.hero.mime is None                         # nada depende de file_name/file_size


JSON_TEXT = '{"title": "Titulo", "caption": "Legenda \U0001F60A"}'


@pytest.mark.parametrize("raw", [
    "```json\n" + JSON_TEXT + "\n```",            # cerca com rotulo
    "```JSON\n" + JSON_TEXT + "\n```",            # rotulo em maiusculas
    "```\n" + JSON_TEXT + "\n```",                # cerca sem rotulo
    "```json" + JSON_TEXT + "```",                  # tudo colado
    JSON_TEXT,                                      # JSON puro
    "\n\n  " + JSON_TEXT + "  \n\n",              # espaco e linha em branco ao redor
    "\ufeff\n```json\n" + JSON_TEXT + "\n```\n\n",  # BOM + cerca + quebras
    "  ```json\r\n" + JSON_TEXT + "\r\n```  ",    # CRLF
])
def test_text_parser_accepts_fenced_unfenced_and_padded_json(raw):
    assert fc.parse_text_output(raw) == ("Titulo", "Legenda \U0001F60A", [])


@pytest.mark.parametrize("raw", ["```json\n{quebrado\n```", "```\n```", "```json\n```", "\n\n", "{", "```json\n[]\n```"])
def test_fenced_but_invalid_or_empty_still_warns_and_invents_nothing(raw):
    title, caption, warns = fc.parse_text_output(raw)
    assert (title, caption) == ("", "") and len(warns) == 1


def test_fenced_json_with_empty_fields_warns():
    t, c, w = fc.parse_text_output('```json\n{"title": "", "caption": ""}\n```')
    assert (t, c) == ("", "") and "nao identificou" in w[0]


def test_unknown_style_is_refused():
    with pytest.raises(fc.ContractError):
        fc.parse_result({}, "neon", C)
