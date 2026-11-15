"""Migration 13: cenario e plataforma por producao (workflow unico da fal.ai)."""

from __future__ import annotations

from studio import migrations
from studio.db import Database
from studio.migrations import current_version, migrate


def test_migration_13_adds_scene_and_platform_and_maps_dark_to_dark_premium(tmp_path):
    db = Database(tmp_path / "s.sqlite3")
    assert current_version(db.conn) == migrations.LATEST >= 13
    cols = {r[1]: r for r in db.conn.execute("PRAGMA table_info(productions)")}
    assert cols["scene"]["notnull"] == 1 and cols["scene"]["dflt_value"] == "'home_light'"
    assert cols["platform"]["notnull"] == 1 and cols["platform"]["dflt_value"] == "'shopee_video'"
    ins = ("INSERT INTO productions(id, status, mode, format_id, product_json, profiles_json, budget_usd, created_at,"
           " updated_at, engine, style) VALUES (?,?,?,?,?,?,?,?,?,?,?)")
    for pid, style in (("p_dark", "dark"), ("p_light", "light"), ("p_none", None)):
        db.conn.execute(ins, (pid, "completed", "real", "f", "{}", "{}", 1.0, "2026-11-01", "2026-11-01", "fal", style))
    # volta o banco ao estado da versao 12 (sem as colunas novas) e refaz a migracao
    db.conn.execute("ALTER TABLE productions DROP COLUMN scene")
    db.conn.execute("ALTER TABLE productions DROP COLUMN platform")
    db.conn.execute("PRAGMA user_version = 12")
    assert migrate(db.conn)[:1] == [13]                        # a 13 roda (e as seguintes, se houver)
    got = {r["id"]: (r["scene"], r["platform"]) for r in db.conn.execute("SELECT id, scene, platform FROM productions")}
    assert got == {"p_dark": ("dark_premium", "shopee_video"), "p_light": ("home_light", "shopee_video"),
                   "p_none": ("home_light", "shopee_video")}
    assert migrate(db.conn) == []                              # idempotente
    db.close()
