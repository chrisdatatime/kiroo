"""Exportador opcional de dados locais"""
from .backup_common import *  # noqa: F401,F403
from .backup_common import _clean_backup_env  # noqa: F401
from .test_accounts import app  # noqa: F401

import export_local_data  # noqa: E402


# ------------------------------------------------------------------ exportador opcional
def test_export_import_is_idempotent_and_does_not_touch_source(tmp_path):
    src = tmp_path / "origem"
    info = make_data(src)
    src_bytes = (src / "studio.sqlite3").read_bytes()
    bundle = export_local_data.export_data(src)
    assert (src / "studio.sqlite3").read_bytes() == src_bytes
    assert bundle["production_ids"] == [info["pid"]]
    flat = json.dumps(bundle)
    assert "sessions" not in bundle["tables"] and "password_resets" not in bundle["tables"] and "email_codes" not in bundle["tables"]
    assert "pw_hash" in flat                                                             # necessário para o login continuar valendo

    dest = tmp_path / "destino"
    dry = export_local_data.import_data(dest, bundle, dry_run=True)
    assert dry["inserted"]["users"] == 1
    db = Database(dest / "studio.sqlite3")
    assert db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0              # dry-run não grava
    db.close()
    first = export_local_data.import_data(dest, bundle)
    second = export_local_data.import_data(dest, bundle)
    assert first["inserted"]["productions"] == 1 and first["inserted"]["credit_entries"] >= 1
    assert all(v == 0 for v in second["inserted"].values()) and second["skipped"]["users"] == 1
    db = Database(dest / "studio.sqlite3")
    wid = info["wid"]
    assert Ledger(db).balance(wid) == 500
    assert db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == len(bundle["tables"]["events"])
    db.close()


def test_import_reports_email_conflict_without_overwriting(tmp_path):
    src = tmp_path / "o"
    make_data(src)
    bundle = export_local_data.export_data(src)
    dest = tmp_path / "d"
    db = Database(dest / "studio.sqlite3")
    Accounts(db).create_user("a@example.com", "outra-senha-forte")                       # mesmo e-mail, outro id
    db.close()
    with pytest.raises(SystemExit, match="conflito"):                                    # aborta tudo, nada é gravado
        export_local_data.import_data(dest, bundle)
    db = Database(dest / "studio.sqlite3")
    assert db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM productions").fetchone()[0] == 0
    db.close()


def test_export_cli_refuses_to_overwrite_bundle(tmp_path):
    src = tmp_path / "o"
    make_data(src)
    out = tmp_path / "b.json"
    assert export_local_data.main(["export", "--data-dir", str(src), "--out", str(out)]) == 0
    with pytest.raises(FileExistsError):
        export_local_data.main(["export", "--data-dir", str(src), "--out", str(out)])


