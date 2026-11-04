import json

from studio.agents import craft, creative, editing, sound
from studio.ffmpeg import FFmpeg
from studio.models import ProductSheet
from studio.providers.simulated import placeholder_png
from studio.states import ProductionStatus as PS

from .conftest import create, drive_to_final, requires_ffmpeg


def _ff(settings):
    return FFmpeg(settings.ffmpeg_bin, settings.ffprobe_bin, settings.font_file, "ultrafast")


# ---------------------------------------------------------- especialistas
def test_scene_prompts_carry_specialist_craft(make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)  # prepara e roteiriza (simulado)
    script = orch._script_obj(pid)
    hero, detail, closing = script.scenes
    for s in script.scenes:
        assert "PHOTOGRAPHY CRAFT" in s.image_prompt and "9:16 SAFE AREA" in s.image_prompt
        assert "MOTION CRAFT" in s.animation_prompt and f"first {s.target_duration_s:g} seconds" in s.animation_prompt
    assert "HOOK" in hero.animation_prompt and "telephoto" in detail.image_prompt and "push-in" in closing.animation_prompt
    assert "HANDS:" in hero.image_prompt  # formato só mãos


def test_material_notes_follow_the_sheet(product):
    sheet = ProductSheet(product=product.model_copy(update={"name": "Garrafa térmica de aço inox"}))
    assert "metal" in craft.material_notes(sheet)
    plain = ProductSheet(product=product.model_copy(update={"name": "Coisa", "variant": "azul", "category": None,
                                                            "visual_attributes": {}}))
    assert "official photos" in craft.material_notes(plain)


def test_craft_never_adds_product_facts(product):
    sheet = ProductSheet(product=product)
    text = craft.image_craft("hero", sheet, "hands_only") + craft.motion_craft("hero", 5)
    for word in ("térmic", "capacidade", "BPA", "garantia", "vedação"):
        assert word.lower() not in text.lower()


# ---------------------------------------------------------- editor
def _takes(ff, tmp_path, n=3, seconds=8):
    takes, probes = {}, {}
    for i in range(1, n + 1):
        img = tmp_path / f"s{i}.png"
        img.write_bytes(placeholder_png(str(i), 270, 480))
        takes[i] = ff.still_to_clip(img, tmp_path / f"c{i}.mp4", seconds, 270, 480)
        probes[i] = ff.probe(takes[i])
    return takes, probes


@requires_ffmpeg
def test_dynamic_edit_has_transitions_music_and_sfx(settings, tmp_path, make_orch, product):
    ff = _ff(settings)
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    script = orch._script_obj(pid)
    takes, probes = _takes(ff, tmp_path)
    music, music_path, sfx = orch._sound_for("dinamico", "auto")
    plan = editing.build_edit_plan(script, takes, probes, style="dinamico", music=music, music_path=music_path,
                                   sfx_paths=sfx)
    assert [t.kind for t in plan.transitions] == ["smoothleft", "zoomin"]
    assert plan.total_s() == 15.0 and plan.music.license == sound.STUDIO_LICENSE
    assert [c.label for c in plan.sfx] == ["gancho", "transição 1→2", "transição 2→3", "fechamento"]
    assert editing.validate_edit_plan(plan, probes, script, 1.5) == []
    out = editing.assemble_and_package(ff, plan, tmp_path / "delivery", tmp_path / "work", 13.0)
    info = ff.probe(out["final"])
    assert abs(info["duration_s"] - 15.0) < 0.15 and info["has_audio"]
    lv = ff.audio_levels(out["final"])
    assert -22 < lv["mean_volume_db"] < -8  # trilha audível e normalizada
    nm = ff.probe(out["no_music"])
    assert abs(nm["duration_s"] - 15.0) < 0.15
    assert ff.audio_levels(out["no_music"])["mean_volume_db"] < lv["mean_volume_db"] - 6  # só os efeitos


@requires_ffmpeg
def test_clean_style_is_silent_with_hard_cuts(settings, tmp_path, make_orch, product):
    ff = _ff(settings)
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    script = orch._script_obj(pid)
    takes, probes = _takes(ff, tmp_path)
    music, music_path, sfx = orch._sound_for("limpo", "auto")
    plan = editing.build_edit_plan(script, takes, probes, style="limpo", music=music, music_path=music_path,
                                   sfx_paths=sfx)
    assert plan.music is None and plan.sfx == [] and all(t.kind == "cut" for t in plan.transitions)
    out = editing.assemble_and_package(ff, plan, tmp_path / "delivery", tmp_path / "work", 13.0)
    assert out["no_music"] is None and abs(ff.probe(out["final"])["duration_s"] - 15.0) < 0.15


@requires_ffmpeg
def test_beat_snapping_keeps_duration_in_tolerance(settings, tmp_path, make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    script = orch._script_obj(pid)
    takes, probes = _takes(_ff(settings), tmp_path)
    music, music_path, sfx = orch._sound_for("suave", "auto")  # lo-fi 90 BPM: batida de 0,667 s
    plan = editing.build_edit_plan(script, takes, probes, style="suave", music=music, music_path=music_path,
                                   sfx_paths=sfx)
    beat = 60 / 90
    extras = [t.duration_s for t in plan.transitions] + [0.0]
    useful = [c.duration_s - e for c, e in zip(plan.clips, extras)]  # duração útil de cada cena, sem a sobreposição
    assert all(abs(u / beat - round(u / beat)) < 0.01 for u in useful)
    assert editing.validate_edit_plan(plan, probes, script, 1.5) == []


@requires_ffmpeg
def test_restyle_after_delivery_remounts_without_new_generations(make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    assert drive_to_final(orch, pid) == PS.AWAITING_FINAL_REVIEW
    st = orch._storage(pid)
    meta = json.loads(st.path("delivery/delivery_meta.json").read_text(encoding="utf-8"))
    assert meta["edit_style"] == "dinamico" and meta["music"] and meta["no_music_version"]
    gens = len(orch.db.attempts(pid))
    orch.final_decision(pid, True)
    orch.set_edit(pid, "limpo", "auto")
    assert orch.run(pid) == PS.AWAITING_FINAL_REVIEW
    meta = json.loads(st.path("delivery/delivery_meta.json").read_text(encoding="utf-8"))
    assert meta["edit_style"] == "limpo" and meta["music"] is None and not st.path("delivery/final_sem_musica.mp4").exists()
    assert len(orch.db.attempts(pid)) == gens  # remontar não gera imagem nem vídeo de novo


@requires_ffmpeg
def test_remount_drops_old_on_screen_disclosure(make_orch, product):
    from studio.models import TextOverlay
    orch = make_orch()
    pid = create(orch, product)
    assert drive_to_final(orch, pid) == PS.AWAITING_FINAL_REVIEW
    script = orch._script_obj(pid)
    old = script.model_copy(update={"overlays": [
        TextOverlay(text="Publicidade • Imagens ilustrativas geradas por IA", start_s=0, end_s=15, position="top")]})
    orch.db.update_production(pid, script_json=old.model_dump_json())  # roteiro de antes de 28/10
    orch.set_edit(pid, "suave")
    assert orch.run(pid) == PS.AWAITING_FINAL_REVIEW
    plan = json.loads(orch._storage(pid).path("delivery/edit_plan.json").read_text(encoding="utf-8"))
    assert plan["overlays"] == []


def test_set_edit_validates(make_orch, product):
    import pytest
    from studio.orchestrator import OrchestratorError
    orch = make_orch()
    pid = create(orch, product)
    with pytest.raises(OrchestratorError):
        orch.set_edit(pid, "psicodelico")
    with pytest.raises(OrchestratorError):
        orch.set_edit(pid, "dinamico", "musica_que_nao_existe")


def test_user_library_requires_license(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    (music / "a.mp3").write_bytes(b"x")
    (music / "b.mp3").write_bytes(b"x")
    (music / "library.json").write_text(json.dumps([
        {"id": "com_licenca", "title": "A", "file": "a.mp3", "bpm": 100, "license": "Licença comercial nº 123"},
        {"id": "sem_licenca", "title": "B", "file": "b.mp3"},
    ]), encoding="utf-8")
    ids = {t["id"] for t in sound.library(tmp_path)}
    assert "com_licenca" in ids and "sem_licenca" not in ids and "batida_pop_120" in ids
