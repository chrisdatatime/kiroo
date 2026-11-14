"""Telas de Preferências refeitas: Créditos e extrato (saldo inteiro, selos do extrato, "Por vídeo", CSV), Minha conta
(nome, senha, CPF/CNPJ mascarado, vantagens por plano, exclusão) e Sobre (links e rodapé que dependem do ambiente)."""

from __future__ import annotations

import json

import pytest

from studio import plans, site_info
from studio.accounts import AuthError, mask_tax_doc
from studio.credits import (Ledger, entry_status, entry_texts, fmt_balance, fmt_charge, fmt_entry, statement_csv)

from .test_prebudget import ws_db
from .test_upload_demo_spend import HOST, app, post  # noqa: F401 (fixture)

ENVS = ("STUDIO_SUPPORT_CONTACT", "STUDIO_SUPPORT_WHATSAPP", "STUDIO_HELP_URL", "STUDIO_TERMS_URL", "STUDIO_PRIVACY_URL",
        "STUDIO_CHANGELOG_URL", "STUDIO_LEGAL_NAME", "STUDIO_LEGAL_CNPJ", "STUDIO_BUILD_VERSION", "STUDIO_BUILD_COMMIT",
        "STUDIO_PAYMENTS_PROVIDER")
CPF, CNPJ = "529.982.247-25", "11.222.333/0001-81"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for v in ENVS:
        monkeypatch.delenv(v, raising=False)


def get(app, path):
    return app.handle("GET", path, {**HOST}, b"")


# ------------------------------------------------------------------ saldo inteiro, arredondado para baixo
@pytest.mark.parametrize("cc,text", [(0, "0"), (99, "0"), (100, "1"), (1999, "19"), (2000, "20"), (200000, "2.000"),
                                     (-40, "−1"), (-100, "−1"), (-101, "−2")])
def test_balance_is_rounded_down_to_whole_credits(cc, text):
    assert fmt_balance(cc) == text


def test_summary_balance_and_reserved_are_whole_credits_but_the_ledger_keeps_decimals(settings):
    db, wid = ws_db(settings)
    led = Ledger(db)
    led.add(wid, 1999, note="teste")
    sm = led.summary(wid)
    assert sm["balance_cc"] == 1999 and sm["balance"] == "19" and sm["balance_exact"] == "19,99"
    assert sm["held"] == "0"


# ------------------------------------------------------------------ extrato: status, textos e valores
@pytest.mark.parametrize("kind,code,label", [
    ("purchase", "paid", "Pago"), ("debit", "done", "Concluído"), ("adjust", "done", "Concluído"),
    ("refund", "not_charged", "Não cobrado"), ("release", "not_charged", "Não cobrado"),
    ("welcome_bonus", "gift", "Presente"), ("grant", "gift", "Presente"), ("reversal", "reversed", "Estornado")])
def test_statement_status_mapping(kind, code, label):
    assert entry_status(kind, 0) == (code, label)


@pytest.mark.parametrize("cc,text", [(2000, "+20"), (-2000, "−20"), (0, "0"), (150, "+1"), (-99, "0"), (-150, "−1"),
                                     (200000, "+2.000")])
def test_statement_credits_are_whole_with_sign(cc, text):
    assert fmt_entry(cc) == text


def test_video_charge_is_20_or_0():
    assert fmt_charge(2000) == "20" and fmt_charge(0) == "0" and fmt_charge(-5) == "0"


def test_statement_texts():
    assert entry_texts("purchase", package="pro", method="pix") == ("Compra · Pro", "Pix")
    assert entry_texts("purchase", package="avulso", method="card") == ("Compra · Avulso", "Cartão")
    assert entry_texts("welcome_bonus") == ("Bônus de boas-vindas", "Seu primeiro vídeo")
    assert entry_texts("debit", product="Tênis", style="light") == ("Vídeo · Tênis", "Estilo Claro")
    assert entry_texts("refund", product="Tênis", style="dark") == ("Vídeo · Tênis", "Estilo Escuro")


def _seed(settings):
    db, wid = ws_db(settings)
    led = Ledger(db)
    db.conn.execute("INSERT INTO payments(id, account_id, method, package_code, credits, amount_cents, status, created_at)"
                    " VALUES ('kpay_0000000001',?, 'pix','pro',200,7990,'paid','2026-11-01T10:00:00')", (wid,))
    led.payment_entry(wid, "kpay_0000000001", 20000, note="compra")
    led.add(wid, 2000, kind="welcome_bonus", note="boas-vindas", ext_ref="wb:1")
    for pid, prod, style in (("prod_ok", "Tênis", "light"), ("prod_fail", "Mochila", "dark")):
        db.conn.execute("INSERT INTO productions(id, status, mode, format_id, product_json, profiles_json, budget_usd,"
                        " created_at, updated_at, style) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (pid, "delivered", "real", "f", json.dumps({"name": prod}), "{}", 1.0, "2026-11-02", "2026-11-02", style))
    led._insert(workspace_id=wid, kind="reserve", amount_cc=-2000, hold_id="pool:prod_ok", production_id="prod_ok",
                stage="prebudget", ext_ref="pool:prod_ok:base")
    led._insert(workspace_id=wid, kind="debit", amount_cc=-2000, hold_id="pool:prod_ok", production_id="prod_ok",
                stage="workflow", ext_ref="debit:a1")
    led._insert(workspace_id=wid, kind="reserve", amount_cc=-2000, hold_id="pool:prod_fail", production_id="prod_fail",
                stage="prebudget", ext_ref="pool:prod_fail:base")
    led._insert(workspace_id=wid, kind="release", amount_cc=2000, hold_id="pool:prod_fail", production_id="prod_fail",
                stage="prebudget", ext_ref="release:pool:prod_fail")
    led.payment_entry(wid, "kpay_0000000001", 0, note="estorno")
    return db, wid, led


def test_statement_rows_for_each_kind(settings):
    db, wid, led = _seed(settings)
    rows = {(r["title"], r["status"]): r for r in led.statement(wid)}
    assert rows[("Compra · Pro", "paid")]["credits"] == "+200" and rows[("Compra · Pro", "paid")]["subtitle"] == "Pix"
    assert rows[("Estorno de compra · Pro", "reversed")]["credits"] == "−200"
    assert rows[("Bônus de boas-vindas", "gift")]["credits"] == "+20"
    ok = rows[("Vídeo · Tênis", "done")]
    assert ok["credits"] == "−20" and ok["subtitle"] == "Estilo Claro" and ok["status_label"] == "Concluído"
    nc = rows[("Vídeo · Mochila", "not_charged")]
    assert nc["credits"] == "0" and nc["amount_cc"] == 0 and nc["status_label"] == "Não cobrado"


def test_per_video_view_has_no_call_level_detail(settings):
    db, wid, led = _seed(settings)
    by = {v["product"]: v for v in led.videos(wid)}
    assert by["Tênis"]["credits"] == "20" and by["Tênis"]["style"] == "Estilo Claro" and by["Tênis"]["status"] == "done"
    assert by["Mochila"]["credits"] == "0" and by["Mochila"]["status"] == "not_charged"
    assert set(by["Tênis"]) == {"production_id", "product", "style", "at", "credits_cc", "credits", "status", "status_label"}


def test_credits_endpoint_for_the_customer_has_videos_and_no_usage(app):
    d = json.loads(get(app, "/api/credits").body)
    assert "usage" not in d and d["videos"] == [] and d["held"] == "0" and isinstance(d["statement"], list)


# ------------------------------------------------------------------ CSV
def test_csv_columns_whole_credits_and_formula_injection(settings):
    db, wid, led = _seed(settings)
    csv = statement_csv(led.statement(wid))
    lines = csv.strip().split("\r\n")
    assert lines[0] == '"Data";"Descrição";"Detalhe";"Status";"Créditos"'
    assert any('"Compra · Pro";"Pix";"Pago";"+200"' in ln for ln in lines)
    assert any('"Vídeo · Mochila";"Estilo Escuro";"Não cobrado";"0"' in ln for ln in lines)
    evil = statement_csv([{"at": "2026-01-01T00:00:00", "title": '=HYPERLINK("x")', "subtitle": "a\nb", "status_label": "Pago",
                           "credits": "+20"}])
    assert "\"'=HYPERLINK(\"\"x\"\")\"" in evil and "a b" in evil


def test_csv_endpoint_downloads_the_statement(app):
    r = get(app, "/api/credits/statement.csv")
    assert r.status == 200 and r.content_type.startswith("text/csv")
    assert "attachment" in r.headers["Content-Disposition"] and r.body.startswith("﻿".encode("utf-8"))


# ------------------------------------------------------------------ CPF/CNPJ
def test_tax_doc_mask_shows_only_the_last_two_digits():
    assert mask_tax_doc("52998224725") == "•••.•••.•••-25"
    assert mask_tax_doc("11222333000181") == "••.•••.•••/••••-81"
    assert mask_tax_doc("") == "" and mask_tax_doc(None) == "" and mask_tax_doc("123") == ""
    assert "5299" not in mask_tax_doc("52998224725")


def test_tax_doc_endpoint_validates_saves_masks_and_clears(app):
    bad = post(app, "/api/account/tax-doc", {"document": "111.111.111-11"})
    assert bad.status == 400
    ok = post(app, "/api/account/tax-doc", {"document": CPF})
    assert ok.status == 200 and json.loads(ok.body)["tax_doc"] == "•••.•••.•••-25" and "52998" not in ok.body.decode()
    me = json.loads(get(app, "/api/me").body)
    assert me["user"]["tax_doc"] == "•••.•••.•••-25" and "52998224725" not in json.dumps(me)
    assert json.loads(post(app, "/api/account/tax-doc", {"document": CNPJ}).body)["tax_doc"] == "••.•••.•••/••••-81"
    assert json.loads(post(app, "/api/account/tax-doc", {"document": ""}).body)["tax_doc"] == ""
    assert json.loads(get(app, "/api/me").body)["user"]["tax_doc"] == ""


# ------------------------------------------------------------------ nome e senha
def test_change_name_and_password(app):
    assert post(app, "/api/account/name", {"name": "  Chris   Souza "}).status == 200
    me = json.loads(get(app, "/api/me").body)
    assert me["user"]["name"] == "Chris Souza" and me["user"]["has_password"] is True
    assert post(app, "/api/account/name", {"name": "   "}).status == 400
    assert post(app, "/api/account/password", {"current": "errada", "new": "outra-senha-123"}).status == 400
    assert post(app, "/api/account/password", {"current": "senha-forte-123", "new": "curta"}).status == 400
    assert post(app, "/api/account/password", {"current": "senha-forte-123", "new": "outra-senha-123"}).status == 200
    assert get(app, "/api/me").status == 200   # a sessão atual continua valida
    s, db, acc = app._db()
    try:
        assert acc.login("chris@example.com", "outra-senha-123")
        with pytest.raises(AuthError):
            acc.login("chris@example.com", "senha-forte-123")
    finally:
        db.close()


def test_delete_account_asks_for_the_email(app):
    r = post(app, "/api/account/delete", {"confirm": "outro@example.com", "password": "TEST_PLACEHOLDER_NOT_A_KEY"})
    assert r.status == 400 and "e-mail" in json.loads(r.body)["error"]


# ------------------------------------------------------------------ plano: vantagens, WhatsApp e e-mail
def test_whatsapp_only_for_pro_and_escala_and_only_with_env(monkeypatch, settings):
    db, wid = ws_db(settings)
    monkeypatch.setenv("STUDIO_SUPPORT_CONTACT", "ajuda@exemplo.com")
    free = plans.view(db, wid)
    assert free["plan"] == "free" and free["support"]["whatsapp"] is None and free["support"]["email"] == "ajuda@exemplo.com"
    assert free["priority_queue"] is False and free["early_access"] is False
    monkeypatch.setenv("STUDIO_SUPPORT_WHATSAPP", "5511999990000")
    db.conn.execute("INSERT INTO payments(id, account_id, method, package_code, credits, amount_cents, status, created_at, paid_at)"
                    " VALUES ('kpay_0000000002',?, 'pix','pro',200,7990,'paid','2026-11-01','2026-11-01')", (wid,))
    pro = plans.view(db, wid)
    assert pro["plan"] == "pro" and pro["support"]["whatsapp"] == "https://wa.me/5511999990000"
    assert pro["priority_queue"] is True and pro["early_access"] is False
    monkeypatch.delenv("STUDIO_SUPPORT_WHATSAPP")
    assert plans.view(db, wid)["support"]["whatsapp"] is None   # sem env: o botão some e a tela cai no e-mail


# ------------------------------------------------------------------ Sobre: itens condicionais por env
def test_site_info_hides_everything_without_envs():
    v = site_info.view()
    assert v["changelog_url"] is v["help_url"] is v["terms_url"] is v["privacy_url"] is v["contact"] is None
    assert v["legal_name"] is None and v["legal_cnpj"] is None


def test_site_info_with_envs_and_unsafe_links(monkeypatch):
    monkeypatch.setenv("STUDIO_HELP_URL", "https://ajuda.exemplo.com/")
    monkeypatch.setenv("STUDIO_TERMS_URL", "javascript:alert(1)")
    monkeypatch.setenv("STUDIO_PRIVACY_URL", "http://inseguro.exemplo.com")
    monkeypatch.setenv("STUDIO_CHANGELOG_URL", "https://exemplo.com/novidades")
    monkeypatch.setenv("STUDIO_SUPPORT_CONTACT", "ajuda@exemplo.com")
    monkeypatch.setenv("STUDIO_LEGAL_NAME", "Kiroo Tecnologia Ltda")
    monkeypatch.setenv("STUDIO_LEGAL_CNPJ", "11.222.333/0001-81")
    monkeypatch.setenv("STUDIO_BUILD_VERSION", "v0.7.0")
    v = site_info.view()
    assert v["help_url"] == "https://ajuda.exemplo.com/" and v["changelog_url"] == "https://exemplo.com/novidades"
    assert v["terms_url"] is None and v["privacy_url"] is None          # só https://
    assert v["contact"]["href"].startswith("mailto:ajuda@exemplo.com") and v["version"] == "v0.7.0"
    assert v["legal_name"] == "Kiroo Tecnologia Ltda" and v["legal_cnpj"] == "11.222.333/0001-81"


def test_version_falls_back_to_short_commit(monkeypatch):
    from studio import buildinfo
    buildinfo.commit.cache_clear()
    monkeypatch.setenv("STUDIO_BUILD_COMMIT", "3e3373c9d3b8f1a2")
    try:
        assert site_info.version() == "3e3373c"
    finally:
        buildinfo.commit.cache_clear()


def test_me_exposes_site_block(app, monkeypatch):
    monkeypatch.setenv("STUDIO_HELP_URL", "https://ajuda.exemplo.com/")
    me = json.loads(get(app, "/api/me").body)
    assert me["site"]["help_url"] == "https://ajuda.exemplo.com/" and me["site"]["terms_url"] is None
