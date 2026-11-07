"""backup_media.sh com rclone FALSO"""
from .backup_common import *  # noqa: F401,F403
from .backup_common import _clean_backup_env  # noqa: F401
from .test_accounts import app  # noqa: F401


# ------------------------------------------------------------------ backup_media.sh com rclone falso
@needs_bash
def test_backup_media_never_deletes_without_versioning(tmp_path):
    data = tmp_path / "data"
    make_data(data)
    (data / "uploads").mkdir()
    (data / "uploads" / "u.txt").write_text("x")
    env, log = backup_env(tmp_path, data)
    p = run_sh("backup_media.sh", env=env)
    assert p.returncode == 0, p.stdout + p.stderr
    calls = log.read_text().splitlines()
    syncs = [c for c in calls if c.startswith("sync ")]
    assert len(syncs) >= 2
    for c in syncs:
        assert "--backup-dir" in c and "/archive/" in c and "/current/" in c            # versiona o que seria sobrescrito/apagado
        assert c.split()[2].startswith("KBK:kiroo-backups/staging/media/current/")
    joined = " ".join(calls)
    assert not re.search(r"\b(delete|deletefile|purge|cleanup|move|moveto)\b", joined) and "--delete-excluded" not in joined
    assert any(c.startswith("rcat ") and "/manifests/" in c for c in calls)
    assert SECRET not in p.stdout + p.stderr and SECRET not in joined                    # segredo só no ambiente do rclone


@needs_bash
def test_backup_media_refuses_empty_source_and_missing_env(tmp_path):
    data = tmp_path / "data"
    (data / "productions").mkdir(parents=True)                                          # volume "montado errado": vazio
    env, log = backup_env(tmp_path, data)
    p = run_sh("backup_media.sh", env=env)
    assert p.returncode == 3 and not log.exists()                                       # nenhum rclone foi chamado
    env2, _ = backup_env(tmp_path, data)
    env2.pop("BACKUP_R2_SECRET_ACCESS_KEY")
    env2.pop("STUDIO_ENV")
    assert run_sh("backup_media.sh", env=env2).returncode == 2
    env3, _ = backup_env(tmp_path, data)
    env3.pop("BACKUP_R2_SECRET_ACCESS_KEY")
    p3 = run_sh("backup_media.sh", env=env3)
    assert p3.returncode == 2 and "BACKUP_R2_SECRET_ACCESS_KEY" in p3.stderr


@needs_bash
def test_backup_media_dry_run_writes_no_manifest(tmp_path):
    data = tmp_path / "data"
    make_data(data)
    env, log = backup_env(tmp_path, data)
    assert run_sh("backup_media.sh", "--dry-run", env=env).returncode == 0
    calls = log.read_text()
    assert "--dry-run" in calls and "rcat" not in calls


