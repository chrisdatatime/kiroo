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
    assert any(c.startswith("copyto ") and "/manifests/" in c for c in calls)
    assert not any(c.startswith("rcat ") for c in calls)
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
    assert "--dry-run" in calls and "rcat" not in calls and "/manifests/" not in calls




@needs_bash
def test_backup_media_manifest_via_copyto_from_local_file(tmp_path):
    data = tmp_path / "data"
    make_data(data)
    (tmp_path / "tmp").mkdir()
    env, log = backup_env(tmp_path, data, TMPDIR=posix(tmp_path / "tmp"))
    p = run_sh("backup_media.sh", env=env)
    assert p.returncode == 0, p.stdout + p.stderr
    calls = log.read_text().splitlines()
    cp = [c for c in calls if c.startswith("copyto ") and "/manifests/" in c]
    assert len(cp) == 1 and "rcat" not in " ".join(calls)
    src, dst = cp[0].split()[1:3]
    # arquivo local, tamanho conhecido, dentro de $TMPDIR (o Git Bash pode reescrever C:/.../Temp como /tmp)
    assert f"{tmp_path.name}/tmp/kiroo-backup-media." in src and src.endswith(".json")
    assert dst.startswith("KBK:kiroo-backups/staging/media/manifests/")
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["status"] == "ok" and m["env"] == "staging" and "productions" in m["dirs"]
    assert [f for f in (tmp_path / "tmp").iterdir() if f.name.startswith("kiroo-backup-media.")] == []   # temporário removido
    assert "enviados=1 objetos" in p.stdout and "manifesto: gravado" in p.stdout


@needs_bash
def test_backup_media_manifest_501_fails_with_exit_1(tmp_path):
    data = tmp_path / "data"
    make_data(data)
    env, log = backup_env(tmp_path, data, FAKE_RCLONE_MANIFEST="501")
    p = run_sh("backup_media.sh", env=env)
    out = p.stdout + p.stderr
    assert p.returncode == 1, out
    assert "concluído" not in out
    assert "manifesto: NÃO GRAVADO" in p.stdout and "501" in p.stderr
    assert "FALHOU" in p.stderr and "manifesto(rc=1)" in p.stderr
    assert "já enviou 1 objeto" in p.stderr and "nada foi apagado" in p.stderr
    assert not re.search(r"\b(delete|deletefile|purge)\b", log.read_text())
    assert SECRET not in out


@needs_bash
def test_backup_media_sync_failure_exits_1(tmp_path):
    data = tmp_path / "data"
    make_data(data)
    env, log = backup_env(tmp_path, data)
    d = fake_bin(tmp_path, "rclone", f'echo "$@" >> "{posix(log)}"\n'
                 'if [ "$1" = sync ]; then echo "Failed to sync: status code: 403" >&2; exit 7; fi\n'
                 'if [ "$1" = size ]; then echo \'{"count":1,"bytes":1}\'; fi\n')
    env["PATH"] = posix(d) + os.pathsep + os.environ["PATH"]
    p = run_sh("backup_media.sh", env=env)
    assert p.returncode == 1 and "sync:productions(rc=7)" in p.stderr, p.stdout + p.stderr
