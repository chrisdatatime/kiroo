#!/usr/bin/env python3
"""Valida uma pasta de dados RESTAURADA (somente leitura; nunca altera o banco nem a mídia).

    python scripts/verify_restore.py --data-dir /caminho/restaurado [--hash] [--json]

Confere: integridade do SQLite (integrity_check), chaves estrangeiras, versão do schema, contagem de registros e,
para cada tentativa concluída (attempts.status='succeeded' com output_path), se o arquivo existe em
productions/<id>/<output_path> (e, com --hash, se o SHA-256 bate). Como banco (contínuo) e mídia (diária) têm
frequências diferentes, arquivo ausente é esperado quando o banco é mais novo que o último backup de mídia:
é relatado por produção, sem tratar como corrupção.

Saída: 0 tudo íntegro | 1 banco ausente/corrompido/versão incompatível | 2 banco íntegro, mas há mídia ausente/divergente.
Não imprime e-mails, hashes de senha nem conteúdo de mensagens: só contagens e ids de produção.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

COUNT_TABLES = ("users", "workspaces", "memberships", "productions", "scenes", "attempts", "credit_entries")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(data_dir: Path, *, check_hash: bool = False, expected_version: int | None = None) -> dict:
    report: dict = {"data_dir": str(data_dir), "ok": False, "code": 1, "problems": [], "counts": {}, "media": {}}
    db_path = data_dir / "studio.sqlite3"
    if not db_path.is_file():
        report["problems"].append("studio.sqlite3 ausente")
        return report
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        report["problems"].append(f"não abriu o banco: {type(exc).__name__}")
        return report
    try:
        try:
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.Error as exc:
            report["problems"].append(f"integrity_check falhou: {type(exc).__name__}")
            return report
        if integrity != "ok":
            report["problems"].append(f"integrity_check: {integrity[:120]}")
            return report
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            report["problems"].append(f"{len(fk)} violação(ões) de chave estrangeira")
        version = con.execute("PRAGMA user_version").fetchone()[0]
        report["schema_version"] = version
        if version == 0:
            report["problems"].append("banco sem versão de schema (user_version=0): não é um banco do Kiroo migrado")
        if expected_version is not None and version != expected_version:
            report["problems"].append(f"schema versão {version}, esperado {expected_version}")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in COUNT_TABLES:
            if t in tables:
                report["counts"][t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            else:
                report["problems"].append(f"tabela ausente: {t}")
        missing: dict[str, int] = {}
        bad_hash: dict[str, int] = {}
        checked = 0
        if "attempts" in tables:
            rows = con.execute("SELECT production_id, output_path, output_sha256 FROM attempts"
                               " WHERE status='succeeded' AND output_path IS NOT NULL AND output_path<>''")
            for pid, rel, digest in rows:
                checked += 1
                base = (data_dir / "productions" / pid).resolve()
                f = (base / rel).resolve()
                if base not in f.parents or not f.is_file():
                    missing[pid] = missing.get(pid, 0) + 1
                elif check_hash and digest and _sha256(f) != digest:
                    bad_hash[pid] = bad_hash.get(pid, 0) + 1
        report["media"] = {"files_checked": checked, "missing_files": sum(missing.values()),
                           "productions_with_missing": sorted(missing), "hash_mismatch_files": sum(bad_hash.values()),
                           "productions_with_hash_mismatch": sorted(bad_hash), "hash_checked": check_hash}
    finally:
        con.close()
    if report["problems"]:
        report["code"] = 1
    elif report["media"]["missing_files"] or report["media"]["hash_mismatch_files"]:
        report["code"] = 2
    else:
        report["code"], report["ok"] = 0, True
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--hash", action="store_true", help="confere também o SHA-256 de cada arquivo (lento)")
    ap.add_argument("--expect-version", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = ap.parse_args(argv)
    r = verify(a.data_dir, check_hash=a.hash, expected_version=a.expect_version)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"banco: {'ÍNTEGRO' if not r['problems'] else 'PROBLEMAS'} | schema v{r.get('schema_version', '?')} | registros: {r['counts']}")
        for p in r["problems"]:
            print(f"  ! {p}")
        m = r["media"]
        if m:
            print(f"mídia: {m['files_checked']} arquivo(s) referenciado(s); ausentes={m['missing_files']}; hash divergente={m['hash_mismatch_files']}")
            if m["productions_with_missing"]:
                print("  produções com arquivo ausente (banco mais novo que o backup de mídia?): " + ", ".join(m["productions_with_missing"][:20]))
        print({0: "RESULTADO: OK", 1: "RESULTADO: FALHA", 2: "RESULTADO: BANCO OK, MÍDIA INCOMPLETA"}[r["code"]])
    return r["code"]


if __name__ == "__main__":
    sys.exit(main())
