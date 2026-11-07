"""Utilitários dos testes de backup (sem testes aqui)."""
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from studio import runtime
from studio.accounts import Accounts
from studio.credits import Ledger
from studio.db import Database

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))



def _bash():
    for cand in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"):
        if os.path.exists(cand):
            return cand
    if os.name == "nt":
        return None                       # o bash do WSL não entende caminhos do Windows
    return shutil.which("bash")


BASH = _bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="bash (Git Bash/Linux) indisponível")

SECRET = "SEGREDO-FAKE-nao-pode-vazar-0123456789"


def posix(p) -> str:
    return Path(p).as_posix()


def make_data(root: Path, with_media=True) -> dict:
    """Pasta de dados descartável: banco migrado + uma produção com um arquivo de mídia referenciado."""
    root.mkdir(parents=True, exist_ok=True)
    db = Database(root / "studio.sqlite3")
    acc = Accounts(db)
    uid, wid = acc.create_user("a@example.com", "senha-forte-123")
    Ledger(db).add(wid, 500, kind="grant")
    pid = "prod_aaaaaaaaaa"
    now = "2026-01-01T00:00:00+00:00"
    db.conn.execute("INSERT INTO productions(id,status,mode,format_id,product_json,profiles_json,budget_usd,created_at,updated_at,workspace_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)", (pid, "completed", "simulated", "f", "{}", "{}", 1.0, now, now, wid))
    rel = "scenes/scene_0/images/attempt_01.png"
    data = b"\x89PNG-fake-bytes"
    import hashlib
    db.conn.execute("INSERT INTO attempts(id,production_id,scene_idx,kind,attempt_no,status,provider,model,simulated,input_hash,output_path,output_sha256,created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", ("att_1", pid, 0, "image", 1, "succeeded", "p", "m", 1, "h", rel,
                                                             hashlib.sha256(data).hexdigest(), now))
    db.conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    db.close()
    if with_media:
        f = root / "productions" / pid / rel
        f.parent.mkdir(parents=True)
        f.write_bytes(data)
    return {"pid": pid, "rel": rel, "wid": wid}




def run_sh(script, *args, env=None, cwd=None):
    e = {**os.environ, "PYTHON": sys.executable, **(env or {})}
    return subprocess.run([BASH, posix(SCRIPTS / script), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, timeout=120, cwd=cwd)


def fake_bin(tmp_path, name, body="") -> Path:
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    f = d / name
    f.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return d


def backup_env(tmp_path, data, **extra):
    log = tmp_path / "rclone.log"
    d = fake_bin(tmp_path, "rclone", f'echo "$@" >> "{posix(log)}"\n'
                 f'echo "ENV:$RCLONE_CONFIG_KBK_SECRET_ACCESS_KEY" >> "{posix(tmp_path / "rclone.env")}"\n'
                 'if [ "$1" = size ]; then echo \'{"count":1,"bytes":1}\'; fi\n'
                 'if [ "$1" = rcat ]; then cat > /dev/null; fi\n'
                 # sync "envia" 1 objeto por pasta (linha no formato do rclone -v, que o script conta)
                 'if [ "$1" = sync ]; then echo "INFO  : x: Copied (new)" >&2; fi\n'
                 # manifesto: copia o arquivo local para manifest.json, ou simula o 501 do R2
                 'case "$1 $3" in "copyto "*/manifests/*)\n'
                 '  if [ "${FAKE_RCLONE_MANIFEST:-}" = 501 ]; then\n'
                 '    echo "ERROR : Failed to copy: NotImplemented: status code: 501" >&2; exit 1; fi\n'
                 f'  cp "$2" "{posix(tmp_path / "manifest.json")}";;\n'
                 'esac\n')
    env = {"PATH": posix(d) + os.pathsep + os.environ["PATH"], "STUDIO_ENV": "staging", "STUDIO_DATA_DIR": posix(data),
           "BACKUP_R2_ENDPOINT": "https://conta.r2.example", "BACKUP_R2_ACCESS_KEY_ID": "AK-FAKE",
           "BACKUP_R2_SECRET_ACCESS_KEY": SECRET, **extra}
    return env, log


def run_entry(tmp_path, env_extra):
    d = fake_bin(tmp_path, "litestream", f'echo "LS $@" > "{posix(tmp_path / "ls.log")}"\n'
                 f'echo "KEY=$LITESTREAM_ACCESS_KEY_ID" >> "{posix(tmp_path / "ls.log")}"\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BACKUP_", "STUDIO_", "LITESTREAM"))}
    env.update(PATH=posix(d) + os.pathsep + os.environ["PATH"], STUDIO_DATA_DIR=posix(tmp_path / "d"), **env_extra)
    return subprocess.run([BASH, posix(ROOT / "docker" / "entrypoint.sh"), "echo", "SERVIDOR", "subiu"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=60)


def _clean_backup_env(monkeypatch):
    for v in (*runtime.BACKUP_VARS, "STUDIO_ALLOW_NO_BACKUP", "STUDIO_ENV"):
        monkeypatch.delenv(v, raising=False)
