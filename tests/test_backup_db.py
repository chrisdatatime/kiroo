"""Backup do banco: entrypoint/Litestream, avisos, exigência em production, ordem de parada"""
from .backup_common import *  # noqa: F401,F403
from .backup_common import _clean_backup_env  # noqa: F401
from .test_accounts import app  # noqa: F401


# ------------------------------------------------------------------ entrypoint com litestream falso
@needs_bash
def test_entrypoint_dev_without_backup_starts_server_directly(tmp_path):
    p = run_entry(tmp_path, {})
    assert p.returncode == 0 and "SERVIDOR subiu" in p.stdout and not (tmp_path / "ls.log").exists()


@needs_bash
def test_entrypoint_staging_without_backup_warns_loudly_but_starts(tmp_path):
    p = run_entry(tmp_path, {"STUDIO_ENV": "staging"})
    assert p.returncode == 0 and "SERVIDOR subiu" in p.stdout
    assert "BACKUP DO BANCO NÃO CONFIGURADO" in p.stderr and "BACKUP_R2_ENDPOINT" in p.stderr


@needs_bash
def test_entrypoint_with_backup_runs_litestream_exec_without_leaking_secret(tmp_path):
    p = run_entry(tmp_path, {"STUDIO_ENV": "production", "BACKUP_R2_ENDPOINT": "https://c.r2.example",
                             "BACKUP_R2_ACCESS_KEY_ID": "AK1", "BACKUP_R2_SECRET_ACCESS_KEY": SECRET})
    log = (tmp_path / "ls.log").read_text()
    assert "LS replicate -config /etc/litestream.yml -exec echo SERVIDOR subiu" in log and "KEY=AK1" in log
    assert SECRET not in log and SECRET not in p.stdout + p.stderr


@needs_bash
def test_entrypoint_rejects_invalid_env(tmp_path):
    assert run_entry(tmp_path, {"STUDIO_ENV": "prod"}).returncode == 2


# ------------------------------------------------------------------ volume montado como root (Railway)
def test_entrypoint_conserta_volume_e_desce_de_privilegio_antes_de_subir():
    """O conserto do dono acontece como root e a troca de usuário vem ANTES do Litestream e do servidor.

    A prova dinâmica (docker, volume de verdade, com controle positivo) está em scripts/verify_volume_uid.py.
    """
    t = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    i_chown = t.index('chown "$APP_UID:$APP_GID" "$DATA"')
    i_recursivo = t.index('chown -R "$APP_UID:$APP_GID" "$DATA"')
    i_drop = t.index("exec setpriv --reuid=")
    assert i_chown < i_recursivo < i_drop                                  # conserta, depois desce
    assert i_drop < t.index('exec "$@"') and i_drop < t.index("exec litestream replicate")
    assert '[ "$(id -u)" = "0" ]' in t                                     # só mexe em privilégio se for root
    assert '[ "${KIROO_PRIV_DROPPED:-0}" != "1" ]' in t                    # a re-execução não entra em laço
    for flag in ("--clear-groups", "--no-new-privs", "--inh-caps=-all"):   # nada de capacidade herdada
        assert flag in t, flag
    assert "KIROO_SKIP_PRIV_DROP" in t and "ROOT (plano B)" in t           # plano B existe e avisa alto
    assert "-quit" in t                                                    # não varre o volume inteiro sem precisar


def test_dockerfile_garante_setpriv_no_build():
    df = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "util-linux" in df and "command -v setpriv" in df                # sem setpriv o app ficaria como root


@needs_bash
def test_entrypoint_sem_root_nao_toca_em_privilegio(tmp_path):
    """Caminho Docker/compose (já entra como kiroo): nenhum chown, nenhum aviso de root."""
    p = run_entry(tmp_path, {"STUDIO_ENV": "staging"})
    assert p.returncode == 0 and "SERVIDOR subiu" in p.stdout
    assert "ajustando o dono" not in p.stderr and "ROOT" not in p.stderr



# ------------------------------------------------------------------ configuração e avisos do servidor
def test_backup_warning_only_in_staging_and_production():
    full = {"BACKUP_R2_ENDPOINT": "e", "BACKUP_R2_ACCESS_KEY_ID": "a", "BACKUP_R2_SECRET_ACCESS_KEY": "s"}
    assert runtime.backup_warning({}) is None and runtime.backup_warning({"STUDIO_ENV": "dev"}) is None
    w = runtime.backup_warning({"STUDIO_ENV": "production"})
    assert "NÃO CONFIGURADO" in w and "BACKUP_R2_SECRET_ACCESS_KEY" in w
    assert runtime.backup_warning({"STUDIO_ENV": "staging", **full}) is None
    secret_env = {"STUDIO_ENV": "staging", "BACKUP_R2_ENDPOINT": SECRET}
    assert SECRET not in runtime.backup_warning(secret_env)                              # só nomes, nunca valores
    with pytest.raises(ValueError):
        runtime.environment_name({"STUDIO_ENV": "prod"})


def test_readyz_warns_when_backup_missing_in_staging(app, monkeypatch):
    for v in runtime.BACKUP_VARS:
        monkeypatch.delenv(v, raising=False)
    host = {"Host": "10.0.0.5:8765"}
    monkeypatch.setenv("STUDIO_ENV", "staging")
    body = json.loads(app.handle("GET", "/readyz", host, b"").body)
    assert body["status"] == "ready" and body["warnings"] == ["backup_not_configured"]
    monkeypatch.setenv("STUDIO_ENV", "dev")
    assert "warnings" not in json.loads(app.handle("GET", "/readyz", host, b"").body)


def test_litestream_config_and_lock_have_no_credentials():
    text = (ROOT / "litestream.yml").read_text(encoding="utf-8")
    assert "${BACKUP_R2_ENDPOINT}" in text and "${BACKUP_R2_PREFIX}/db" in text and "${STUDIO_DATA_DIR}/studio.sqlite3" in text
    assert not re.search(r"(access-key-id|secret-access-key)\s*:\s*[^$\s]", text)          # nunca valor literal
    assert not re.search(r"[0-9a-f]{32,}", text)


def test_dockerfile_wires_entrypoint_and_pins_litestream():
    df = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["tini", "--", "kiroo-entrypoint"]' in df and "litestream.yml" in df and "fetch_litestream.py" in df
    sys.path.insert(0, str(ROOT / "docker"))
    import fetch_litestream
    real = fetch_litestream.read_lock(ROOT / "docker" / "litestream.lock")                # sha256 fixado (523cacd)
    assert re.fullmatch(r"[0-9a-f]{64}", real["sha256"])
    ok = {"version": "1", "url": "https://github.com/benbjohnson/litestream/releases/download/v0/x.tar.gz", "sha256": "a" * 64}
    p = ROOT / "docker" / "_t.lock"
    p.write_text(json.dumps(ok))
    try:
        assert fetch_litestream.read_lock(p)["sha256"] == "a" * 64
        p.write_text(json.dumps({**ok, "url": "https://evil.example/x.tar.gz"}))
        with pytest.raises(fetch_litestream.LitestreamError, match="URL"):
            fetch_litestream.read_lock(p)
    finally:
        p.unlink()



# ------------------------------------------------------------------ production exige backup
def test_production_without_backup_refuses_to_start_unless_overridden():
    full = {"BACKUP_R2_ENDPOINT": "e", "BACKUP_R2_ACCESS_KEY_ID": "a", "BACKUP_R2_SECRET_ACCESS_KEY": SECRET}
    msg = runtime.backup_start_error({"STUDIO_ENV": "production"})
    assert msg and "BACKUP_R2_ENDPOINT" in msg and "STUDIO_ALLOW_NO_BACKUP=1" in msg and SECRET not in msg
    assert runtime.backup_start_error({"STUDIO_ENV": "production", "STUDIO_ALLOW_NO_BACKUP": "1"}) is None
    assert runtime.backup_start_error({"STUDIO_ENV": "production", "STUDIO_ALLOW_NO_BACKUP": "true"}) is not None   # só "1"
    assert runtime.backup_start_error({"STUDIO_ENV": "production", **full}) is None
    assert runtime.backup_start_error({"STUDIO_ENV": "production", **{**full, "BACKUP_R2_ENDPOINT": ""}}) is not None
    for env in ("staging", "dev"):                                   # comportamento anterior: sobe (com aviso)
        assert runtime.backup_start_error({"STUDIO_ENV": env}) is None
        assert runtime.backup_warning({"STUDIO_ENV": env}) is None or env == "staging"


def test_serve_exits_before_binding_in_production_without_backup(monkeypatch):
    from studio.web import server
    _clean_backup_env(monkeypatch)
    monkeypatch.setenv("STUDIO_ENV", "production")
    with pytest.raises(SystemExit, match="sem backup"):
        server.serve(port=0, open_browser=False)


def test_readyz_503_in_production_when_override_used_and_200_in_staging(app, monkeypatch):
    _clean_backup_env(monkeypatch)
    host = {"Host": "10.0.0.5:8765"}
    monkeypatch.setenv("STUDIO_ENV", "production")
    monkeypatch.setenv("STUDIO_ALLOW_NO_BACKUP", "1")
    r = app.handle("GET", "/readyz", host, b"")
    assert r.status == 503 and json.loads(r.body)["warnings"] == ["backup_not_configured"]
    monkeypatch.setenv("STUDIO_ENV", "staging")
    r = app.handle("GET", "/readyz", host, b"")
    assert r.status == 200 and json.loads(r.body)["warnings"] == ["backup_not_configured"]
    for v, val in zip(runtime.BACKUP_VARS, ("e", "a", "s")):
        monkeypatch.setenv(v, val)
    monkeypatch.setenv("STUDIO_ENV", "production")
    r = app.handle("GET", "/readyz", host, b"")
    assert r.status == 200 and "warnings" not in json.loads(r.body)



# ------------------------------------------------------------------ Litestream x encerramento
def test_app_only_runs_passive_checkpoints():
    for f in list((ROOT / "src").rglob("*.py")) + list(SCRIPTS.glob("*.py")) + list((ROOT / "docker").glob("*")):
        if f.is_file():
            t = f.read_text(encoding="utf-8", errors="ignore")
            assert not re.search(r"wal_checkpoint\s*\(\s*(TRUNCATE|RESTART|FULL)", t, re.I), f
            assert not re.search(r"wal_checkpoint\s*(=|\()?\s*(TRUNCATE|RESTART)", t, re.I), f


def test_entrypoint_hands_process_to_litestream_via_exec():
    t = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert 'exec litestream replicate -config "$CFG" -exec "$*"' in t       # sem shell no meio: sinais vão direto
    assert 'ENTRYPOINT ["tini", "--", "kiroo-entrypoint"]' in (ROOT / "Dockerfile").read_text(encoding="utf-8")
