"""Saldo por origem (Configurações › Créditos): leitura do livro, consumo suposto na ordem bônus → liberados → comprados."""

from __future__ import annotations

from studio.credits import Ledger, split_by_origin

from .test_credits import ws_db


def by_key(rows):
    return {r["key"]: (r["received_cc"], r["left_cc"]) for r in rows}


def test_bonus_is_spent_first_then_granted_then_purchased():
    got = {"bonus": 2000, "granted": 1000, "purchased": 20000}
    assert by_key(split_by_origin(got, 23000)) == {"bonus": (2000, 2000), "granted": (1000, 1000), "purchased": (20000, 20000)}
    assert by_key(split_by_origin(got, 21000)) == {"bonus": (2000, 0), "granted": (1000, 1000), "purchased": (20000, 20000)}
    assert by_key(split_by_origin(got, 6000)) == {"bonus": (2000, 0), "granted": (1000, 0), "purchased": (20000, 6000)}


def test_origins_without_entries_are_hidden_and_negative_balance_is_zero():
    rows = split_by_origin({"bonus": 2000}, -500)
    assert [r["key"] for r in rows] == ["bonus"] and rows[0]["left_cc"] == 0
    assert split_by_origin({}, 0) == []
    assert rows[0]["label"] == "Bônus de boas-vindas" and rows[0]["received"] == "20" and rows[0]["left"] == "0"


def test_ledger_origins_reads_the_book(settings):
    db, wid = ws_db(settings)
    led = Ledger(db)
    led.add(wid, 2000, kind="welcome_bonus", note="bônus")
    led.add(wid, 5000, kind="grant", note="teste")
    rows = by_key(led.origins(wid))
    bal = led.balance(wid)
    assert sum(left for _, left in rows.values()) == max(bal, 0)
    assert rows["bonus"][0] == 2000 and rows["granted"][0] == 5000
