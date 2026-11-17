"""Livro de créditos por origem (Fase 6): ordem de consumo bônus → plano → avulso, validade dos créditos do plano,
devolução para a mesma origem (erro técnico), estorno só do que não foi usado e a migração 16 (saldo atual → avulso)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from studio import migrations
from studio.credits import InsufficientCredits, Ledger
from studio.db import Database
from studio.migrations import migrate

from .test_credits import ws_db

import pytest


def iso(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


def left(led, wid):
    """Quanto resta de cada origem (só lotes que valem agora)."""
    out = {}
    for lot in led.lots(wid, valid_only=True):
        out[lot["origin"]] = out.get(lot["origin"], 0) + lot["remaining_cc"]
    return out


def funded(settings):
    db, wid = ws_db(settings)
    led = Ledger(db)
    led.add(wid, 2000, kind="welcome_bonus", note="bônus")
    led.add(wid, 12000, kind="subscription", expires_at=iso(30), ext_ref="invoice:in_1", note="ciclo")
    led.add(wid, 10000, kind="purchase", ext_ref="topup:kpay_1", note="avulso")
    return db, wid, led


# ------------------------------------------------------------------ ordem de consumo
def test_consumption_order_is_bonus_then_plan_then_topup(settings):
    db, wid, led = funded(settings)
    assert led.balance(wid) == 24000
    led.reserve_pool(wid, "prod_a", 2000, ref="base")                       # 1º vídeo: o bônus inteiro
    assert left(led, wid) == {"bonus": 0, "subscription": 12000, "topup": 10000}
    led.reserve_pool(wid, "prod_b", 13000, ref="base")                      # passa do plano: o resto sai do avulso
    assert left(led, wid) == {"bonus": 0, "subscription": 0, "topup": 9000}
    assert led.balance(wid) == 9000


def test_plan_lot_that_expires_first_is_used_first(settings):
    db, wid = ws_db(settings)
    led = Ledger(db)
    led.add(wid, 2000, kind="subscription", expires_at=iso(20), ext_ref="upgrade:late")
    led.add(wid, 2000, kind="subscription", expires_at=iso(2), ext_ref="invoice:soon")
    led.reserve_pool(wid, "prod_a", 2000, ref="base")
    lots = {lot["source"]: lot["remaining_cc"] for lot in led.lots(wid)}
    assert lots == {"upgrade:late": 2000, "invoice:soon": 0}


# ------------------------------------------------------------------ validade (créditos do plano não acumulam)
def test_expired_plan_credits_leave_the_balance_and_become_an_expire_entry(settings):
    db, wid = ws_db(settings)
    led = Ledger(db)
    led.add(wid, 12000, kind="subscription", expires_at=iso(-0.01), ext_ref="invoice:old")
    assert led.balance(wid) == 0                                            # o vencido já não conta na leitura
    with pytest.raises(InsufficientCredits):
        led.can_reserve(wid, 2000)
    assert led.expire_due(wid) == 12000                                     # a baixa vira lançamento
    assert led.expire_due(wid) == 0                                         # uma vez só
    led.add(wid, 5000, kind="purchase", ext_ref="topup:kpay_9")
    assert [o["key"] for o in led.origins(wid)] == ["topup"]                # o plano vencido nem aparece nas barras
    kinds = [r["kind"] for r in led.statement(wid)]
    assert "expire" in kinds and led.balance(wid) == 5000
    row = next(r for r in led.statement(wid) if r["kind"] == "expire")
    assert row["credits"] == "−120" and row["status_label"] == "Expirado"


def test_topup_and_bonus_never_expire(settings):
    db, wid = ws_db(settings)
    led = Ledger(db)
    led.add(wid, 2000, kind="welcome_bonus")
    led.add(wid, 5000, kind="purchase", ext_ref="topup:x")
    assert all(lot["expires_at"] is None for lot in led.lots(wid))


# ------------------------------------------------------------------ erro técnico devolve para a mesma origem
def test_technical_failure_returns_credits_to_the_same_origin(settings):
    db, wid, led = funded(settings)
    led.reserve_pool(wid, "prod_bonus", 2000, ref="base")                  # sai do bônus
    led.reserve_pool(wid, "prod_plan", 2000, ref="base")                   # sai do plano
    assert left(led, wid) == {"bonus": 0, "subscription": 10000, "topup": 10000}
    led.close_pool("prod_plan", note="falha técnica: sem custo")           # devolve tudo: volta para o PLANO
    assert left(led, wid) == {"bonus": 0, "subscription": 12000, "topup": 10000}
    led.close_pool("prod_bonus", note="falha técnica: sem custo")          # volta para o BÔNUS
    assert left(led, wid) == {"bonus": 2000, "subscription": 12000, "topup": 10000}
    assert led.balance(wid) == 24000


def test_partial_use_keeps_the_first_origins_spent_and_returns_the_last(settings):
    db, wid, led = funded(settings)
    led.reserve_pool(wid, "prod_x", 4000, ref="base")                      # 20 do bônus + 20 do plano
    hid = led.pool_id("prod_x")
    led._insert(workspace_id=wid, kind="drawdown", amount_cc=2000, hold_id=hid, production_id="prod_x", ext_ref="draw:a")
    led._insert(workspace_id=wid, kind="debit", amount_cc=-2000, hold_id=hid, production_id="prod_x", ext_ref="debit:a")
    assert led.close_pool("prod_x") == 2000                                # sobra 20: volta para o plano (o último usado)
    assert left(led, wid) == {"bonus": 0, "subscription": 12000, "topup": 10000}
    assert led.balance(wid) == 22000


def test_return_to_an_expired_plan_lot_expires_again(settings):
    db, wid = ws_db(settings)
    led = Ledger(db)
    led.add(wid, 2000, kind="subscription", expires_at=iso(1), ext_ref="invoice:c1")
    led.reserve_pool(wid, "prod_y", 2000, ref="base")
    db.conn.execute("UPDATE credit_lots SET expires_at=?", (iso(-0.01),))  # o ciclo acabou com a produção em curso
    led.close_pool("prod_y", note="falha técnica")
    assert led.balance(wid) == 0                                           # voltou ao plano, que já venceu
    assert [r["kind"] for r in db.conn.execute("SELECT kind FROM credit_entries ORDER BY rowid")][-1] == "expire"


def test_hold_settle_flow_still_charges_once(settings):
    """Fluxo antigo (reserva por chamada): devolve a reserva e debita o custo; o débito sai na ordem certa."""
    db, wid, led = funded(settings)
    hid = led.hold(wid, "prod_z", 0.0001, "image")
    reserved = -db.conn.execute("SELECT amount_cc FROM credit_entries WHERE hold_id=? AND kind='reserve'", (hid,)).fetchone()[0]
    led.release(hid, "recusado sem custo")
    assert led.balance(wid) == 24000 and left(led, wid)["bonus"] == 2000 and reserved > 0


# ------------------------------------------------------------------ estorno: só o que não foi usado
def test_revoke_takes_only_unused_credits_and_never_goes_negative(settings):
    db, wid = ws_db(settings)
    led = Ledger(db)
    led.add(wid, 10000, kind="purchase", ext_ref="topup:kpay_r", payment_id="kpay_r")
    led.reserve_pool(wid, "prod_r", 3000, ref="base")
    lot = led.lots(wid)[0]["id"]
    assert led.revoke_lot(lot, 10000, note="reembolso", close=True) == 7000
    assert led.revoke_lot(lot, 10000, note="reembolso", close=True) == 0   # evento repetido: nada mais
    assert led.balance(wid) == 0
    led.close_pool("prod_r", note="falha técnica")                         # a reserva volta para um lote estornado
    assert led.balance(wid) == 0                                           # ... e sai de novo


def test_exempt_account_consumes_without_lots(settings):
    db, wid = ws_db(settings, exempt=True)
    led = Ledger(db)
    led.reserve_pool(wid, "prod_e", 2000, ref="base")
    assert led.balance(wid) == -2000 and led.lots(wid) == []


# ------------------------------------------------------------------ migração 16
def test_migration_16_turns_the_current_balance_into_a_topup_lot_without_expiry(tmp_path):
    db = Database(tmp_path / "m.sqlite3")
    assert migrations.LATEST >= 16
    ins = "INSERT INTO credit_entries(id, workspace_id, kind, amount_cc, ext_ref, created_at) VALUES (?,?,?,?,?,?)"
    db.conn.execute(ins, ("e1", "ws_a", "grant", 50000, "x1", "2026-11-01"))
    db.conn.execute(ins, ("e2", "ws_a", "debit", -2000, "x2", "2026-11-02"))
    db.conn.execute(ins, ("e3", "ws_b", "reversal", -500, "x3", "2026-11-02"))   # saldo negativo: sem lote
    db.conn.execute("DELETE FROM credit_lots")
    db.conn.execute("PRAGMA user_version = 15")
    assert migrate(db.conn) == [16]
    lots = db.conn.execute("SELECT workspace_id, origin, amount_cc, remaining_cc, expires_at, source FROM credit_lots").fetchall()
    assert [tuple(r) for r in lots] == [("ws_a", "topup", 48000, 48000, None, "migration:16")]
    assert Ledger(db).balance("ws_a") == 48000
    db.conn.execute("PRAGMA user_version = 15")
    assert migrate(db.conn) == [16] and db.conn.execute("SELECT COUNT(*) FROM credit_lots").fetchone()[0] == 1  # idempotente
    db.close()


def test_open_reservation_from_before_the_migration_returns_as_topup(settings):
    db, wid = ws_db(settings)
    led = Ledger(db)
    ins = "INSERT INTO credit_entries(id, workspace_id, kind, amount_cc, hold_id, production_id, stage, ext_ref, created_at)" \
          " VALUES (?,?,?,?,?,?,?,?,?)"
    db.conn.execute(ins, ("old_g", wid, "grant", 10000, None, None, None, "old:g", "2026-11-01"))
    db.conn.execute(ins, ("old_r", wid, "reserve", -2000, "pool_prod_old", "prod_old", "prebudget", "pool:prod_old:base",
                          "2026-11-01"))
    # a migração 16 viu saldo 80 (a reserva já tinha saído) e criou o lote avulso com ele
    db.conn.execute("INSERT INTO credit_lots(id, workspace_id, origin, amount_cc, remaining_cc, source, created_at)"
                    " VALUES ('lot_m16', ?, 'topup', 8000, 8000, 'migration:16', '2026-11-01')", (wid,))
    assert led.close_pool("prod_old") == 2000                               # reserva sem histórico de lote
    assert left(led, wid) == {"topup": 10000} and led.balance(wid) == 10000
