"""Saldo nunca fica negativo sob concorrência: threads com conexões independentes e processos distintos."""
import os
import subprocess
import sys
import threading

from studio.accounts import Accounts
from studio.credits import InsufficientCredits, Ledger, to_cc
from studio.db import Database

COST_USD = 0.05


def _setup(settings, credits_cc):
    db = Database(settings.db_path)
    _, wid = Accounts(db).create_user("c@example.com", "senha-forte-123")
    Ledger(db).add(wid, credits_cc, kind="grant")
    db.close()
    return wid


def test_threads_with_independent_connections_never_overdraw(settings):
    cc = to_cc(COST_USD)
    allowed = 7
    wid = _setup(settings, cc * allowed + cc // 2)          # cabem 7 reservas, sobra meia
    ok, refused, errors = [], [], []
    start = threading.Barrier(24)

    def worker():
        db = Database(settings.db_path)                      # uma conexão por thread
        try:
            start.wait()
            try:
                ok.append(Ledger(db).hold(wid, None, COST_USD, "image"))
            except InsufficientCredits:
                refused.append(1)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            db.close()

    ts = [threading.Thread(target=worker) for _ in range(24)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    assert not errors
    assert len(ok) == allowed and len(refused) == 24 - allowed
    db = Database(settings.db_path)
    assert Ledger(db).balance(wid) == cc // 2 >= 0
    db.close()


def test_concurrent_releases_are_idempotent(settings):
    cc = to_cc(COST_USD)
    wid = _setup(settings, cc * 3)
    db = Database(settings.db_path)
    led = Ledger(db)
    holds = [led.hold(wid, None, COST_USD, "image") for _ in range(3)]
    assert led.balance(wid) == 0
    errs = []

    def rel(h):
        d = Database(settings.db_path)
        try:
            for _ in range(2):                               # a segunda liberação não duplica
                Ledger(d).release(h, "teste")
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)
        finally:
            d.close()

    ts = [threading.Thread(target=rel, args=(h,)) for h in holds for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    assert not errs and led.balance(wid) == cc * 3
    db.close()


CHILD = """
import sys
from pathlib import Path
from studio.db import Database
from studio.credits import Ledger, InsufficientCredits
db = Database(Path(sys.argv[1])); led = Ledger(db)
n = 0
for _ in range(int(sys.argv[3])):
    try:
        led.hold(sys.argv[2], None, float(sys.argv[4]), 'image'); n += 1
    except InsufficientCredits:
        pass
print(n)
"""


def test_separate_processes_never_overdraw(settings):
    cc = to_cc(COST_USD)
    allowed = 10
    wid = _setup(settings, cc * allowed + 1)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    procs = [subprocess.Popen([sys.executable, "-c", CHILD, str(settings.db_path), wid, "8", str(COST_USD)],
                              env=env, stdout=subprocess.PIPE, text=True) for _ in range(4)]
    won = 0
    for p in procs:
        out, _ = p.communicate(timeout=120)
        assert p.returncode == 0
        won += int(out.strip())
    assert won == allowed                                    # 4 processos x 8 tentativas, só 10 cabem
    db = Database(settings.db_path)
    assert Ledger(db).balance(wid) == 1
    db.close()
