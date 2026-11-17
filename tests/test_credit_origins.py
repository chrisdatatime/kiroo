"""Saldo por origem (Configurações › Créditos): lotes do livro (Fase 6). Antes era uma leitura suposta do saldo único
(bônus → liberados → comprados); agora cada entrada é um lote com origem real (bônus, plano, avulso) e o consumo segue
bônus → plano → avulso de verdade. Os testes de ordem, validade e devolução estão em tests/test_ledger_origins.py."""

from __future__ import annotations

from studio.credits import Ledger, origin_rows

from .test_credits import ws_db


def by_key(rows):
    return {r["key"]: (r["received_cc"], r["left_cc"]) for r in rows}


def test_origin_rows_follow_the_consumption_order_and_hide_empty_origins():
    lots = [{"origin": "topup", "received_cc": 20000, "left_cc": 6000, "expires_at": None},
            {"origin": "bonus", "received_cc": 2000, "left_cc": 0, "expires_at": None},
            {"origin": "subscription", "received_cc": 12000, "left_cc": 12000, "expires_at": "2026-12-16T00:00:00+00:00"}]
    rows = origin_rows(lots)
    assert [r["key"] for r in rows] == ["bonus", "subscription", "topup"]
    assert by_key(rows) == {"bonus": (2000, 0), "subscription": (12000, 12000), "topup": (20000, 6000)}
    assert rows[1]["label"] == "Créditos do plano" and rows[1]["expires_at"].startswith("2026-12-16")
    assert origin_rows([]) == []
    assert rows[0]["label"] == "Bônus de boas-vindas" and rows[0]["received"] == "20" and rows[0]["left"] == "0"


def test_ledger_origins_reads_the_lots(settings):
    db, wid = ws_db(settings)
    led = Ledger(db)
    led.add(wid, 2000, kind="welcome_bonus", note="bônus")
    led.add(wid, 5000, kind="grant", note="teste")              # liberação da equipe = avulso (não expira)
    rows = by_key(led.origins(wid))
    bal = led.balance(wid)
    assert sum(left for _, left in rows.values()) == max(bal, 0)
    assert rows["bonus"][0] == 2000 and rows["topup"][0] == 5000
