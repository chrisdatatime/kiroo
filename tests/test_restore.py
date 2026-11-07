"""Restauração: verify_restore e restore.sh (modo local, sem R2)"""
from .backup_common import *  # noqa: F401,F403
from .backup_common import _clean_backup_env  # noqa: F401
from .test_accounts import app  # noqa: F401

import verify_restore  # noqa: E402
from studio.migrations import LATEST  # noqa: E402


# ------------------------------------------------------------------ verify_restore
def test_verify_restore_ok_missing_media_corruption_and_hash(tmp_path):
    info = make_data(tmp_path / "ok")
    r = verify_restore.verify(tmp_path / "ok")
    assert r["ok"] and r["code"] == 0 and r["counts"]["users"] == 1 and r["schema_version"] == LATEST

    (tmp_path / "ok" / "productions" / info["pid"] / info["rel"]).write_bytes(b"adulterado")
    assert verify_restore.verify(tmp_path / "ok")["code"] == 0                       # sem --hash não vê
    h = verify_restore.verify(tmp_path / "ok", check_hash=True)
    assert h["code"] == 2 and h["media"]["productions_with_hash_mismatch"] == [info["pid"]]

    make_data(tmp_path / "miss", with_media=False)
    m = verify_restore.verify(tmp_path / "miss")
    assert m["code"] == 2 and m["media"]["missing_files"] == 1 and "a@example.com" not in json.dumps(m)

    make_data(tmp_path / "bad")
    p = tmp_path / "bad" / "studio.sqlite3"
    raw = bytearray(p.read_bytes())
    raw[4096 * 2: 4096 * 2 + 200] = b"\xff" * 200                                    # estraga páginas internas
    p.write_bytes(raw)
    assert verify_restore.verify(tmp_path / "bad")["code"] == 1
    assert verify_restore.verify(tmp_path / "nada")["code"] == 1



# ------------------------------------------------------------------ restore.sh (modo local, sem R2)
@needs_bash
def test_restore_local_roundtrip_and_never_overwrites(tmp_path):
    src = tmp_path / "src"
    info = make_data(src)
    dest = tmp_path / "restaurado"
    p = run_sh("restore.sh", "--dest", posix(dest), "--local-db", posix(src / "studio.sqlite3"),
               "--local-media", posix(src / "productions" / ".."), env={"STUDIO_ENV": "dev"})
    assert p.returncode == 0, p.stdout + p.stderr
    assert "RESULTADO: OK" in p.stdout and (dest / "studio.sqlite3").is_file()
    assert (dest / "productions" / info["pid"] / info["rel"]).is_file()

    # segunda execução no mesmo destino: recusa e não altera nada
    before = (dest / "studio.sqlite3").read_bytes()
    p2 = run_sh("restore.sh", "--dest", posix(dest), "--local-db", posix(src / "studio.sqlite3"))
    assert p2.returncode == 3 and "nada será sobrescrito" in p2.stderr
    assert (dest / "studio.sqlite3").read_bytes() == before

    # destino dentro do volume real (STUDIO_DATA_DIR) é recusado
    p3 = run_sh("restore.sh", "--dest", posix(src / "dentro"), "--local-db", posix(src / "studio.sqlite3"),
                env={"STUDIO_DATA_DIR": posix(src)})
    assert p3.returncode == 3 and not (src / "dentro" / "studio.sqlite3").exists()


@needs_bash
def test_restore_reports_incomplete_media_exit_5(tmp_path):
    src = tmp_path / "src"
    make_data(src, with_media=False)
    p = run_sh("restore.sh", "--dest", posix(tmp_path / "r"), "--local-db", posix(src / "studio.sqlite3"), "--db-only")
    assert p.returncode == 5 and "MÍDIA INCOMPLETA" in p.stdout


@needs_bash
def test_restore_requires_env_and_credential_names_only(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BACKUP_", "STUDIO_"))}
    p = subprocess.run([BASH, posix(SCRIPTS / "restore.sh"), "--dest", posix(tmp_path / "x")], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=60)
    assert p.returncode == 2 and "STUDIO_ENV" in p.stderr
    env.update(STUDIO_ENV="staging", BACKUP_R2_ENDPOINT=SECRET)
    p = subprocess.run([BASH, posix(SCRIPTS / "restore.sh"), "--dest", posix(tmp_path / "y")], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=60)
    assert p.returncode == 2 and "BACKUP_R2_ACCESS_KEY_ID" in p.stderr and SECRET not in p.stdout + p.stderr


