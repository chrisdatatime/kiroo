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


# ------------------------------------------------------------------ laço diário dentro do contêiner
def run_loop(tmp_path, env, *, watch_pid="0", timeout=60):
    """docker/media_backup_loop.sh com rclone falso. Intervalos curtos para o teste terminar rápido."""
    return subprocess.run([BASH, posix(ROOT / "docker" / "media_backup_loop.sh"), watch_pid],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, **env}, timeout=timeout)


def loop_env(tmp_path, data, **extra):
    env, log = backup_env(tmp_path, data)
    env.update(STUDIO_MEDIA_BACKUP_SCRIPT=posix(ROOT / "scripts" / "backup_media.sh"),
               STUDIO_MEDIA_BACKUP_DELAY_S="0", STUDIO_MEDIA_BACKUP_INTERVAL_S="5",
               STUDIO_MEDIA_BACKUP_MAX_RUNS="1", **extra)
    return env, log


@needs_bash
def test_loop_executa_o_backup_e_registra_o_resultado(tmp_path):
    """Uma volta do laço: chama o backup_media.sh de verdade (com rclone falso) e loga ok."""
    data = tmp_path / "data"
    make_data(data)
    env, log = loop_env(tmp_path, data)
    p = run_loop(tmp_path, env)                                          # MAX_RUNS=1: uma volta e sai
    assert p.returncode == 0, p.stdout + p.stderr
    assert "media_backup: laço ligado" in p.stdout
    assert "media_backup: início" in p.stdout and "media_backup: ok" in p.stdout
    assert "limite de 1 execução(ões) atingido" in p.stdout
    calls = log.read_text().splitlines()
    assert [c for c in calls if c.startswith("sync ")]                   # o backup rodou mesmo
    assert SECRET not in p.stdout + p.stderr and SECRET not in " ".join(calls)


@needs_bash
def test_loop_continua_depois_de_falha_e_nao_vaza_segredo(tmp_path):
    data = tmp_path / "data"
    make_data(data)
    env, log = loop_env(tmp_path, data)
    d = fake_bin(tmp_path, "rclone", f'echo "$@" >> "{posix(log)}"\n'
                 'if [ "$1" = sync ]; then echo "Failed to sync: status code: 403" >&2; exit 7; fi\n'
                 'if [ "$1" = size ]; then echo \'{"count":1,"bytes":1}\'; fi\n')
    env["PATH"] = posix(d) + os.pathsep + os.environ["PATH"]
    p = run_loop(tmp_path, env)
    assert p.returncode == 0                                             # a falha do dia não derruba o laço
    assert "media_backup: FALHOU código=1" in p.stderr and "o laço continua" in p.stderr
    assert SECRET not in p.stdout + p.stderr


@needs_bash
def test_loop_recusa_configuracao_invalida(tmp_path):
    data = tmp_path / "data"
    make_data(data)
    env, _ = loop_env(tmp_path, data)
    for chave, valor in (("STUDIO_MEDIA_BACKUP_INTERVAL_S", "nao-numero"),
                         ("STUDIO_MEDIA_BACKUP_INTERVAL_S", "1"),          # abaixo da fatia mínima
                         ("STUDIO_MEDIA_BACKUP_DELAY_S", "-5"),
                         ("STUDIO_MEDIA_BACKUP_MAX_RUNS", "x"),
                         ("STUDIO_MEDIA_BACKUP_SCRIPT", posix(tmp_path / "nao-existe.sh"))):
        p = run_loop(tmp_path, {**env, chave: valor})
        assert p.returncode == 2, (chave, valor, p.stdout + p.stderr)


@needs_bash
def test_entrypoint_liga_o_laco_em_staging_e_desliga_em_dev(tmp_path):
    """Quem decide ligar é o entrypoint: staging/production sim, dev não, STUDIO_MEDIA_BACKUP vence."""
    loop = fake_bin(tmp_path, "loop.sh", f'echo "LOOP pid=$1" > "{posix(tmp_path / "loop.log")}"\n') / "loop.sh"
    base = {"BACKUP_R2_ENDPOINT": "https://c.r2.example", "BACKUP_R2_ACCESS_KEY_ID": "AK1",
            "BACKUP_R2_SECRET_ACCESS_KEY": SECRET, "STUDIO_MEDIA_BACKUP_LOOP": posix(loop)}
    casos = [({"STUDIO_ENV": "staging"}, True), ({"STUDIO_ENV": "production"}, True),
             ({"STUDIO_ENV": "dev"}, False),
             ({"STUDIO_ENV": "staging", "STUDIO_MEDIA_BACKUP": "0"}, False),
             ({"STUDIO_ENV": "dev", "STUDIO_MEDIA_BACKUP": "1"}, True)]
    for extra, esperado in casos:
        (tmp_path / "loop.log").unlink(missing_ok=True)
        p = run_entry(tmp_path, {**base, **extra})
        ligado = "backup diário da mídia ligado" in p.stderr
        assert ligado is esperado, (extra, p.stderr)
        assert ("backup diário da mídia desligado" in p.stderr) is (not esperado), extra
        if esperado:
            assert "LOOP pid=" in (tmp_path / "loop.log").read_text()     # recebeu o PID a vigiar
        assert SECRET not in p.stdout + p.stderr


@needs_bash
def test_entrypoint_avisa_se_o_laco_faltar_na_imagem(tmp_path):
    p = run_entry(tmp_path, {"STUDIO_ENV": "staging", "BACKUP_R2_ENDPOINT": "https://c.r2.example",
                             "BACKUP_R2_ACCESS_KEY_ID": "AK1", "BACKUP_R2_SECRET_ACCESS_KEY": SECRET,
                             "STUDIO_MEDIA_BACKUP_LOOP": posix(tmp_path / "nao-existe.sh")})
    assert "laço de backup da mídia ausente" in p.stderr and "SEM cópia diária" in p.stderr


def test_dockerfile_instala_o_laco_de_backup():
    df = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "docker/media_backup_loop.sh /usr/local/bin/kiroo-media-backup" in df
    assert "/usr/local/bin/kiroo-media-backup" in re.search(r"^RUN chmod 0755 .*$", df, re.M).group(0)


@needs_bash
def test_loop_sai_com_o_servidor_e_nao_fica_orfao(tmp_path):
    """Sem MAX_RUNS o laço é infinito; ele sai sozinho quando o PID vigiado desaparece."""
    data = tmp_path / "data"
    make_data(data)
    env, log = loop_env(tmp_path, data)
    env.pop("STUDIO_MEDIA_BACKUP_MAX_RUNS")
    p = run_loop(tmp_path, env, watch_pid="999999")                      # PID que não existe
    assert p.returncode == 0
    assert "servidor saiu antes da primeira execução; encerrando" in p.stdout
    assert not log.exists()                                              # nem chamou o rclone
