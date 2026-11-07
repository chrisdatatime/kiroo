#!/usr/bin/env python3
"""OPCIONAL (só se você decidir migrar os dados locais): exporta/importa usuários, workspaces, créditos e produções.

    python scripts/export_local_data.py export --data-dir <ORIGEM> --out bundle.json
    python scripts/export_local_data.py import --data-dir <DESTINO> --in bundle.json [--dry-run]

* export abre o banco de origem SOMENTE LEITURA (não migra, não grava, não toca em arquivos de mídia).
* import usa Database() do destino (aplica as migrações), roda tudo numa transação e é IDEMPOTENTE: registros já
  presentes (mesma chave primária / ext_ref / e-mail) são pulados e contados; rodar duas vezes não duplica nada.
  Conflito de e-mail com outro id ABORTA a importação inteira (nada é gravado, nada é sobrescrito).
* O bundle contém hashes de senha e e-mails: é sensível. O arquivo é criado com permissão restrita; apague depois.
  Sessões, códigos de e-mail, links de senha e tentativas de login NÃO são exportados.
* A mídia não vai no bundle. O bundle lista os ids de produção; copie data/productions/<id>/ à parte
  (e data/workspaces, data/uploads se usados). Treinamento/música ficam fora desta versão.
Saída: 0 ok | 1 erro | 2 uso.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

FORMAT = 1
# (tabela, colunas-chave para idempotência) em ordem de dependência
TABLES = [
    ("users", ("id",)),
    ("workspaces", ("id",)),
    ("memberships", ("user_id", "workspace_id")),
    ("credit_entries", ("id",)),
    ("productions", ("id",)),
    ("scenes", ("production_id", "idx")),
    ("attempts", ("id",)),
    ("reviews", ("id",)),
    ("events", ()),          # id AUTOINCREMENT: identidade lógica abaixo
]
EVENT_KEY = ("production_id", "scene_idx", "ts", "type", "message")


def _rows(con: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    cur = con.execute(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _has(con, table) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def export_data(data_dir: Path) -> dict:
    db = Path(data_dir) / "studio.sqlite3"
    if not db.is_file():
        raise SystemExit(f"banco não encontrado: {db}")
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        out: dict = {"format": FORMAT, "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "source_user_version": con.execute("PRAGMA user_version").fetchone()[0], "tables": {}}
        for table, _ in TABLES:
            if not _has(con, table):
                out["tables"][table] = []
                continue
            out["tables"][table] = _rows(con, f"SELECT * FROM {table}" + (" ORDER BY id" if table == "events" else ""))
        for r in out["tables"]["events"]:
            r.pop("id", None)
        out["production_ids"] = [r["id"] for r in out["tables"]["productions"]]
        return out
    finally:
        con.close()


def import_data(data_dir: Path, bundle: dict, *, dry_run: bool = False) -> dict:
    if bundle.get("format") != FORMAT:
        raise SystemExit(f"formato de bundle não suportado: {bundle.get('format')!r}")
    from studio.db import Database    # aplica as migrações no destino
    db = Database(Path(data_dir) / "studio.sqlite3")
    conn = db.conn
    report: dict = {"dry_run": dry_run, "inserted": {}, "skipped": {}, "conflicts": []}
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table, key in TABLES:
            dest_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            ins = skip = 0
            for row in bundle["tables"].get(table, []):
                row = {k: v for k, v in row.items() if k in dest_cols}
                if table == "users":
                    other = conn.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE", (row["email"],)).fetchone()
                    if other and other[0] != row["id"]:
                        report["conflicts"].append(f"users: e-mail já existe no destino com outro id ({row['id']})")
                        continue
                ident = EVENT_KEY if table == "events" else key
                where = " AND ".join(f"{c} IS ?" for c in ident)
                if conn.execute(f"SELECT 1 FROM {table} WHERE {where}", tuple(row.get(c) for c in ident)).fetchone():
                    skip += 1
                    continue
                if table == "credit_entries" and row.get("ext_ref") and \
                        conn.execute("SELECT 1 FROM credit_entries WHERE ext_ref=?", (row["ext_ref"],)).fetchone():
                    skip += 1                       # mesmo lançamento (ext_ref único) com outro id
                    continue
                cols = list(row)
                conn.execute(f"INSERT INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             tuple(row[c] for c in cols))
                ins += 1
            report["inserted"][table], report["skipped"][table] = ins, skip
            if report["conflicts"]:
                raise SystemExit("importação abortada por conflito (nada foi gravado): " + "; ".join(report["conflicts"]))
        if report["conflicts"]:
            raise SystemExit("importação abortada por conflito (nada foi gravado): " + "; ".join(report["conflicts"]))
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise SystemExit(f"importação recusada: {len(bad)} violação(ões) de chave estrangeira (nada foi gravado)")
        conn.execute("ROLLBACK" if dry_run else "COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        db.close()
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--data-dir", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    i = sub.add_parser("import")
    i.add_argument("--data-dir", type=Path, required=True)
    i.add_argument("--in", dest="inp", type=Path, required=True)
    i.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "export":
        bundle = export_data(a.data_dir)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # não sobrescreve bundle existente
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False)
        print("exportado:", {t: len(r) for t, r in bundle["tables"].items()})
        print("ATENÇÃO: o arquivo contém e-mails e hashes de senha. Guarde com cuidado e apague depois da importação.")
        print(f"produções cuja mídia você precisa copiar à parte: {len(bundle['production_ids'])}")
        return 0
    bundle = json.loads(a.inp.read_text(encoding="utf-8"))
    rep = import_data(a.data_dir, bundle, dry_run=a.dry_run)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
