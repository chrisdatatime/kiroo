"""Reproduz N vezes o cenário kill-9 do e2e e mostra, por rodada, os snapshots ANTES do kill, NO MOMENTO da morte
(estado confirmado no SQLite) e DEPOIS da retomada, com o diff completo das tentativas.

Uso: python scripts/repro_kill9.py [N] [--json saida.json]      (usa dados temporários próprios; nunca toca em volume real)
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("e2e_shutdown", ROOT / "scripts" / "e2e_shutdown.py")
e2e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e2e)

COLS = "id, scene_idx, kind, attempt_no, status, remote_op_id, created_at, output_sha256"


def full(data: Path, pid: str):
    rows = e2e.q(data, f"SELECT {COLS} FROM attempts WHERE production_id=? ORDER BY created_at, id", pid)
    return [dict(zip(COLS.split(", "), tuple(r))) for r in rows]


def diff(a, b):
    ia, ib = {r["id"]: r for r in a}, {r["id"]: r for r in b}
    out = []
    for k in ia:
        if k not in ib:
            out.append(("REMOVIDA", ia[k], None))
        elif ia[k] != ib[k]:
            out.append(("MUDOU", {c: v for c, v in ia[k].items() if ib[k][c] != v}, {c: ib[k][c] for c in ia[k] if ib[k][c] != ia[k][c]}))
    out += [("NOVA", None, ib[k]) for k in ib if k not in ia]
    return out


def one_round(n: int, base: Path) -> dict:
    from studio.accounts import Accounts
    from studio.db import Database
    data = base / f"r{n}"
    data.mkdir()
    db = Database(data / "studio.sqlite3")
    Accounts(db).create_user(e2e.EMAIL, e2e.PASSWORD, "E2E", verified=True)
    db.close()
    proc = e2e.start(data)
    assert e2e.wait_up(proc), "servidor não subiu"
    cl = e2e.Client(); cl.login()
    st, body = cl.call("POST", "/api/productions", {"name": f"Copo r{n}", "variant": "azul", "affiliate_link": "https://s.shopee.com.br/7VHTuA2W1j",
        "budget": 5, "autonomy": "automatico", "files": [{"name": "f.png", "data": e2e.png(), "role": "front"}], "start": True})
    pid = body["pid"]
    e2e.wait_for(lambda: e2e.q(data, "SELECT COUNT(*) FROM attempts WHERE production_id=?", pid)[0][0] >= 1, 40)
    before = full(data, pid)            # exatamente o que o teste original guarda
    proc.kill(); proc.wait(10)
    at_death = full(data, pid)          # estado confirmado no banco no instante da morte (WAL é recuperado pelo SQLite)
    proc2 = e2e.start(data)
    assert e2e.wait_up(proc2)
    cl2 = e2e.Client(); cl2.login()
    e2e.wait_for(lambda: e2e.prod_status(data, pid) in ("awaiting_final_review", "completed", "failed", "paused")
                 and e2e.q(data, "SELECT state FROM run_state WHERE production_id=?", pid)[0][0] == "idle", 180, 1)
    after = full(data, pid)
    e2e.graceful(proc2)
    try:
        proc2.wait(30)
    except Exception:
        proc2.kill()
    legacy_kept = all((b["id"], b["scene_idx"], b["kind"], b["attempt_no"], b["remote_op_id"]) in
                      {(a["id"], a["scene_idx"], a["kind"], a["attempt_no"], a["remote_op_id"]) for a in after} for b in before)
    key = lambda r: (r["id"], r["scene_idx"], r["kind"], r["attempt_no"], r["remote_op_id"])
    tup = lambda rows: [(r["id"], r["scene_idx"], r["kind"], r["attempt_no"], r["remote_op_id"]) for r in rows]
    fixed_kept, bad_inv = e2e.preserved(tup(at_death), tup(after))   # invariante: ids e ops confirmados preservados; nulo pode ganhar op
    ops = [r["remote_op_id"] for r in after if r["remote_op_id"]]
    dup_ops = len(ops) != len(set(ops))
    final = e2e.prod_status(data, pid)
    events = [r[0] for r in e2e.q(data, "SELECT type FROM events WHERE production_id=? ORDER BY rowid", pid)]
    return {"round": n, "pid": pid, "legacy_assertion_ok": legacy_kept, "fixed_assertion_ok": fixed_kept and not dup_ops, "invariant_violations": bad_inv, "dup_ops": dup_ops, "final_status": final,
            "resume_events": [e for e in events if e in ("interrupted", "resumed", "resume_abandoned")], "before_vs_death": diff(before, at_death),
            "death_vs_after": diff(at_death, after), "before_vs_after": diff(before, after),
            "n_before": len(before), "n_death": len(at_death), "n_after": len(after)}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(args[0]) if args else 20
    out = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
    base = Path(tempfile.mkdtemp(prefix="kiroo-kill9-"))
    results = []
    for i in range(1, n + 1):
        t = time.time()
        r = one_round(i, base)
        results.append(r)
        print(f"rodada {i}: original(pré-kill)={'OK' if r['legacy_assertion_ok'] else 'FALHOU'} corrigida(pós-morte)={'OK' if r['fixed_assertion_ok'] else 'FALHOU'} status={r['final_status']} "
              f"antes={r['n_before']} morte={r['n_death']} depois={r['n_after']} ({time.time()-t:.0f}s)", flush=True)
        for label in ("before_vs_death", "death_vs_after"):
            for kind, a, b in r[label]:
                print(f"   {label}: {kind} {json.dumps(a, default=str)} -> {json.dumps(b, default=str)}", flush=True)
    bad = [r for r in results if not r["legacy_assertion_ok"]]
    print(f"\nasserção original falhou em {len(bad)}/{n} rodadas")
    print("rodadas com perda/mudança entre a MORTE e a retomada (bug real de retomada):",
          sum(1 for r in results if any(d[0] in ('REMOVIDA',) for d in r['death_vs_after'])))
    if out:
        Path(out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
