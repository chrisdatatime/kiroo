"""Configuracao do workflow unico: WORKFLOW_ID (padrao wf01white) e WORKFLOW_ID_LIGHT como alias legado."""

from __future__ import annotations

from studio.config import Settings, load_settings

DEFAULT = "workflows/christiandeluco/wf01white"


def _load(tmp_path, monkeypatch, **env):
    for k in ("WORKFLOW_ID", "WORKFLOW_ID_LIGHT", "WORKFLOW_ID_DARK", "STUDIO_FAL_DARK_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return load_settings(env_file=tmp_path / "none.env", data_dir=tmp_path / "d")


def test_default_is_the_single_wf01white(tmp_path, monkeypatch):
    assert _load(tmp_path, monkeypatch).workflow_id == DEFAULT


def test_workflow_id_overrides_and_light_is_a_legacy_alias(tmp_path, monkeypatch):
    assert _load(tmp_path, monkeypatch, WORKFLOW_ID="workflows/acme/novo").workflow_id == "workflows/acme/novo"
    assert _load(tmp_path, monkeypatch, WORKFLOW_ID_LIGHT="workflows/acme/legado").workflow_id == "workflows/acme/legado"
    both = _load(tmp_path, monkeypatch, WORKFLOW_ID="workflows/acme/novo", WORKFLOW_ID_LIGHT="workflows/acme/legado")
    assert both.workflow_id == "workflows/acme/novo"                        # WORKFLOW_ID manda


def test_dark_variables_are_gone_and_ignored(tmp_path, monkeypatch):
    s = _load(tmp_path, monkeypatch, WORKFLOW_ID_DARK="workflows/acme/wf01black", STUDIO_FAL_DARK_ENABLED="true")
    assert s.workflow_id == DEFAULT
    assert not hasattr(s, "workflow_id_dark") and not hasattr(s, "fal_dark_enabled")
    assert "workflow_id_light" not in Settings.__dataclass_fields__
