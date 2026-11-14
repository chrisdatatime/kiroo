"""Compra de créditos pelo Asaas (Pix e cartão na fatura hospedada) e o "Adicionar créditos" manual de antes.

Desligado por padrão (PAYMENTS_ENABLED=false): a tela continua com o contato manual e o administrador libera créditos
(`studio admin grant-credits`). Ligado, o fluxo é:

  1. `checkout`: o servidor calcula o preço pelo catálogo (o navegador só escolhe pacote ou quantidade), garante o
     cliente no Asaas (CPF/CNPJ na primeira compra; o documento fica só no Asaas) e cria a cobrança com
     `externalReference` = nosso id. Pix devolve QR + copia e cola; cartão devolve o `invoiceUrl` (fatura hospedada:
     nenhum dado de cartão passa pelo Kiroo).
  2. Webhook (`receive_event` + `process_event`): grava o evento uma vez só (id do evento único) e responde 200 na hora;
     o processamento NUNCA confia no payload: busca a cobrança na API do Asaas pelo id e confere valor, cliente,
     meio e externalReference contra a cobrança que nós criamos.
  3. `sync`: leva o estado ao que a API diz AGORA. O crédito é por pagamento (Ledger.payment_entry escreve só a
     diferença até o alvo), então evento repetido, fora de ordem ou perdido nunca credita duas vezes.
       pago (Pix: RECEIVED; cartão: CONFIRMED ou RECEIVED)            -> alvo = créditos da compra
       estorno/contestação (REFUNDED, REFUND_*, CHARGEBACK_*,...)     -> alvo = 0 (o saldo pode ficar negativo)
       pendente/vencida/removida                                     -> nada muda no saldo
  4. `reconcile` (`python -m studio payments reconcile`): eventos não processados e cobranças pendentes (webhook perdido).

Saldo negativo (estorno depois de usar os créditos) bloqueia novas produções até regularizar (`negative_balance_block`).
"""

from __future__ import annotations

import hmac
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from . import asaas, catalog
from .credits import Ledger, fmt, fmt_balance
from .db import Database, new_id, now

log = logging.getLogger("studio.payments")

MANUAL = "manual"
ASAAS = "asaas"
BRT = timezone(timedelta(hours=-3), "BRT")   # Brasília sem horário de verão desde 2019 (sem depender de tzdata)

METHODS = {"pix": "PIX", "card": "CREDIT_CARD"}
# meio de pagamento -> billingType aceitos na cobrança lida na API (na fatura o cliente pode pagar no débito)
BILLING_OK = {"pix": {"PIX"}, "card": {"CREDIT_CARD", "DEBIT_CARD"}}
# o que significa PAGO para cada meio (doc: Pix CREATED -> RECEIVED; cartão CREATED -> CONFIRMED -> RECEIVED ~32 dias).
# Pix CONFIRMED NÃO credita: em conta de pessoa física pode ser temporário (bloqueio cautelar de até 72 h).
PAID = {"pix": {"RECEIVED", "RECEIVED_IN_CASH"}, "card": {"CONFIRMED", "RECEIVED", "RECEIVED_IN_CASH"}}
CHARGEBACK = {"CHARGEBACK_REQUESTED", "CHARGEBACK_DISPUTE", "AWAITING_CHARGEBACK_REVERSAL"}
REFUND = {"REFUNDED", "REFUND_REQUESTED", "REFUND_IN_PROGRESS"}
# eventos que disparam conferência na API; os demais são gravados e ignorados com log
RELEVANT_EVENTS = {"PAYMENT_RECEIVED", "PAYMENT_CONFIRMED", "PAYMENT_REFUNDED", "PAYMENT_REFUND_IN_PROGRESS",
                   "PAYMENT_PARTIALLY_REFUNDED", "PAYMENT_CHARGEBACK_REQUESTED", "PAYMENT_CHARGEBACK_DISPUTE",
                   "PAYMENT_AWAITING_CHARGEBACK_REVERSAL", "PAYMENT_RECEIVED_IN_CASH_UNDONE", "PAYMENT_DELETED",
                   "PAYMENT_RESTORED", "PAYMENT_OVERDUE", "PAYMENT_UPDATED", "PAYMENT_REFUND_DENIED"}
OPEN = ("creating", "pending")
ACTIVE_CARD = ("creating", "pending", "paid")

NEW_ACCOUNT_DAYS = 7
CARD_DAILY_LIMIT_CENTS = 60_000
NEW_ACCOUNT_MAX_PACKAGE = "pro"
POLL_SYNC_S = 10           # o polling da tela consulta o Asaas no máximo a cada 10 s por cobrança


class PaymentRefused(ValueError):
    """Pedido recusado com mensagem para o cliente (limite de cartão, documento inválido, catálogo...)."""

    def __init__(self, message: str, code: str = "refused"):
        super().__init__(message)
        self.code = code


class PaymentsDisabled(Exception):
    pass


# =================================================================== configuração
def enabled() -> bool:
    c = asaas.config()
    return c.enabled and asaas.config_error() is None


def provider_name() -> str:
    return ASAAS if enabled() else MANUAL


def make_client(cfg: asaas.AsaasConfig | None = None):
    """Ponto único de criação do cliente (os testes trocam por um Asaas falso)."""
    return asaas.AsaasClient(cfg or asaas.config())


def webhook_token_ok(received: str | None) -> bool:
    """Compara o token do cabeçalho com ASAAS_WEBHOOK_TOKEN em tempo constante. Sem token configurado: recusa."""
    expected = asaas.config().webhook_token
    if not expected or not received:
        return False
    return hmac.compare_digest(received.encode("utf-8"), expected.encode("utf-8"))


# =================================================================== CPF / CNPJ
def _cpf_ok(d: str) -> bool:
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def _cnpj_ok(d: str) -> bool:
    """CNPJ numérico ou alfanumérico (a partir de 07/2026): 12 posições 0-9/A-Z + 2 dígitos verificadores numéricos.
    Valor de cada caractere = código ASCII − 48 (para dígitos é o próprio dígito)."""
    if len(d) != 14 or not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", d) or d == d[0] * 14:
        return False
    vals = [ord(c) - 48 for c in d]
    for n in (12, 13):
        weights = [*range(n - 7, 1, -1), *range(9, 1, -1)]
        r = sum(v * w for v, w in zip(vals[:n], weights)) % 11
        if (0 if r < 2 else 11 - r) != vals[n]:
            return False
    return True


def normalize_document(raw) -> str:
    """Só dígitos (e letras do CNPJ alfanumérico). Recusa CPF/CNPJ com dígito verificador errado."""
    d = re.sub(r"[^0-9A-Za-z]", "", str(raw or "")).upper()
    if (len(d) == 11 and d.isdigit() and _cpf_ok(d)) or (len(d) == 14 and _cnpj_ok(d)):
        return d
    raise PaymentRefused("CPF ou CNPJ inválido: confira os números.", "invalid_document")


# =================================================================== leitura
def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def get(db: Database, payment_id: str):
    return db.conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()


def by_asaas_id(db: Database, asaas_id: str):
    return db.conn.execute("SELECT * FROM payments WHERE asaas_payment_id=?", (asaas_id,)).fetchone()


def view(row) -> dict:
    """O que a tela vê de uma compra (sem cliente, IP ou agente)."""
    return {"id": row["id"], "method": row["method"], "package_code": row["package_code"], "credits": row["credits"],
            "amount_cents": row["amount_cents"], "amount": catalog.brl(row["amount_cents"]), "status": row["status"],
            "created_at": row["created_at"], "paid_at": row["paid_at"],
            "invoice_url": row["invoice_url"] if row["method"] == "card" and row["status"] in OPEN else None}


def negative_balance_block(db: Database, wid: str) -> str | None:
    """Mensagem de bloqueio quando o saldo ficou negativo (estorno/contestação depois de usar os créditos)."""
    led = Ledger(db)
    if led.exempt(wid):
        return None
    bal = led.balance(wid)
    if bal >= 0:
        return None
    return (f"Seu saldo está negativo ({fmt_balance(bal)} créditos) por causa de um estorno ou contestação de compra. "
            "Novas produções ficam bloqueadas até regularizar: compre créditos para cobrir o saldo (o que você já "
            "produziu continua disponível).")


def account_state(db: Database, wid: str) -> dict:
    """Para a tela: precisa de CPF/CNPJ? Quais limites de cartão valem agora?"""
    ws = db.conn.execute("SELECT * FROM workspaces WHERE id=?", (wid,)).fetchone()
    lim = card_limits(db, wid)
    return {"needs_document": not (ws and ws["asaas_customer_id"]), "card": lim,
            "negative_balance": negative_balance_block(db, wid)}


# =================================================================== limites de cartão
def card_limits(db: Database, wid: str, *, at: datetime | None = None) -> dict:
    """Limites de cartão da conta AGORA (janela de 24 h). Conta nova = criada há menos de 7 dias OU sem compra Pix paga:
    1 compra no cartão por dia e no máximo o pacote Pro. Toda conta: até R$ 600 no cartão por dia. Conta com
    contestação/estorno de cartão no histórico: só Pix."""
    at = at or datetime.now(timezone.utc)
    since = (at - timedelta(hours=24)).isoformat(timespec="seconds")
    ws = db.conn.execute("SELECT created_at FROM workspaces WHERE id=?", (wid,)).fetchone()
    young = ws is None or _ts(ws["created_at"]) > at - timedelta(days=NEW_ACCOUNT_DAYS)
    paid_pix = db.conn.execute("SELECT 1 FROM payments WHERE account_id=? AND method='pix' AND paid_at IS NOT NULL",
                               (wid,)).fetchone() is not None
    rows = db.conn.execute(f"SELECT amount_cents FROM payments WHERE account_id=? AND method='card' AND created_at>=? "
                           f"AND status IN ({','.join('?' * len(ACTIVE_CARD))})", (wid, since, *ACTIVE_CARD)).fetchall()
    disputed = db.conn.execute("SELECT 1 FROM payments WHERE account_id=? AND method='card' AND status='chargeback'",
                               (wid,)).fetchone() is not None
    new = young or not paid_pix
    used = sum(r["amount_cents"] for r in rows)
    pro = catalog.package(NEW_ACCOUNT_MAX_PACKAGE)["price_cents"]
    room = max(CARD_DAILY_LIMIT_CENTS - used, 0)
    max_cents = 0 if disputed else (min(room, pro) if new else room)
    if new and rows:
        max_cents = 0
    return {"new_account": new, "disputed": disputed, "used_today_cents": used, "count_today": len(rows),
            "daily_limit_cents": CARD_DAILY_LIMIT_CENTS, "max_cents": max_cents}


def check_card(db: Database, wid: str, amount_cents: int) -> None:
    lim = card_limits(db, wid)
    if lim["disputed"]:
        raise PaymentRefused("Esta conta tem uma contestação de cartão: novas compras só por Pix.", "card_disputed")
    if lim["new_account"] and lim["count_today"] >= 1:
        raise PaymentRefused("Conta nova: 1 compra no cartão por dia. Use Pix ou tente amanhã. (A conta deixa de ser nova "
                             f"depois de {NEW_ACCOUNT_DAYS} dias e de uma compra por Pix.)", "card_new_daily")
    if lim["new_account"] and amount_cents > catalog.package(NEW_ACCOUNT_MAX_PACKAGE)["price_cents"]:
        raise PaymentRefused("Conta nova: no cartão, o limite é o pacote Pro. Para valores maiores, use Pix.",
                             "card_new_max")
    if lim["used_today_cents"] + amount_cents > CARD_DAILY_LIMIT_CENTS:
        raise PaymentRefused(f"Limite diário no cartão: {catalog.brl(CARD_DAILY_LIMIT_CENTS)} por conta. Use Pix ou "
                             "tente amanhã.", "card_daily_limit")


# =================================================================== compra
def _today_brt(days: int = 0) -> str:
    return (datetime.now(BRT) + timedelta(days=days)).date().isoformat()


def ensure_customer(db: Database, client, wid: str, *, name: str, document) -> str:
    """Cliente do Asaas da conta. Primeira compra: exige CPF/CNPJ válido. Procura pelo externalReference (= workspace)
    antes de criar (a API aceita duplicados). Só o id do cliente fica no Kiroo."""
    ws = db.conn.execute("SELECT asaas_customer_id FROM workspaces WHERE id=?", (wid,)).fetchone()
    if ws and ws["asaas_customer_id"]:
        return ws["asaas_customer_id"]
    if not document:
        raise PaymentRefused("Informe o CPF ou CNPJ de quem paga (exigido pelo Asaas na primeira compra).",
                             "document_required")
    doc = normalize_document(document)
    found = client.find_customer(wid)
    cid = found["id"] if found else client.create_customer(name=name or "Cliente Kiroo", cpf_cnpj=doc, email=None,
                                                           external_reference=wid)["id"]
    db.conn.execute("UPDATE workspaces SET asaas_customer_id=? WHERE id=?", (cid, wid))
    return cid


def checkout(db: Database, client, *, wid: str, user_id: str | None, user_name: str, method: str,
             package_code: str | None = None, credits=None, document=None, ip: str = "", user_agent: str = "",
             return_url: str | None = None) -> dict:
    """Cria a compra. Devolve {payment, pix?: {image, payload, expires_at}, redirect_url?}."""
    if method not in METHODS:
        raise PaymentRefused("Escolha Pix ou cartão.", "invalid_method")
    try:
        q = catalog.quote(package_code, credits)
    except catalog.CatalogError as exc:
        raise PaymentRefused(str(exc), "invalid_quote") from exc
    if method == "card":
        reuse = db.conn.execute(
            "SELECT * FROM payments WHERE account_id=? AND method='card' AND status='pending' AND package_code=? AND "
            "credits=? AND invoice_url IS NOT NULL AND created_at>=? ORDER BY created_at DESC LIMIT 1",
            (wid, q["package_code"], q["credits"], (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(
                timespec="seconds"))).fetchone()
        if reuse is not None:   # mesma compra no cartão ainda aberta: volta para a mesma fatura (não conta 2x no limite)
            return {"payment": view(reuse), "redirect_url": reuse["invoice_url"]}
        check_card(db, wid, q["amount_cents"])
    cid = ensure_customer(db, client, wid, name=user_name, document=document)
    pid = new_id("kpay")
    db.conn.execute("INSERT INTO payments(id, account_id, user_id, asaas_customer_id, method, package_code, credits, "
                    "amount_cents, status, created_at, ip, user_agent) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, wid, user_id, cid, method, q["package_code"], q["credits"], q["amount_cents"], "creating",
                     now(), (ip or "")[:64], (user_agent or "")[:300]))
    desc = f"Kiroo: {q['credits']} créditos ({q['label']})"
    success = f"{return_url.rstrip('/')}/?compra={pid}" if return_url and return_url.startswith("https://") else None
    try:
        remote = client.create_payment(customer=cid, billing_type=METHODS[method], value_cents=q["amount_cents"],
                                       due_date=_today_brt(1), description=desc, external_reference=pid,
                                       success_url=success)
    except asaas.AsaasError:
        db.conn.execute("UPDATE payments SET status='failed', note='erro ao criar a cobrança' WHERE id=?", (pid,))
        raise
    db.conn.execute("UPDATE payments SET asaas_payment_id=?, status='pending', remote_status=?, invoice_url=?, synced_at=? "
                    "WHERE id=?", (remote["id"], remote.get("status"), remote.get("invoiceUrl"), now(), pid))
    log.info("compra criada", extra={"event": "payment_created", "payment_id": pid, "method": method,
                                     "amount_cents": q["amount_cents"]})
    out = {"payment": view(get(db, pid))}
    if method == "pix":
        qr = client.pix_qr(remote["id"])
        out["pix"] = {"image": qr.get("encodedImage"), "payload": qr.get("payload"), "expires_at": qr.get("expirationDate")}
    else:
        out["redirect_url"] = remote.get("invoiceUrl")
    return out


# =================================================================== conferência (fonte da verdade = API do Asaas)
def _mismatch(row, remote: dict) -> str | None:
    if remote.get("id") != row["asaas_payment_id"]:
        return "id da cobrança diferente"
    if remote.get("customer") != row["asaas_customer_id"]:
        return "cliente diferente do da cobrança criada"
    try:
        cents = round(float(remote.get("value")) * 100)
    except (TypeError, ValueError):
        return "valor ausente"
    if cents != row["amount_cents"]:
        return f"valor divergente ({cents} != {row['amount_cents']} centavos)"
    if remote.get("externalReference") not in (None, row["id"]):
        return "externalReference diferente"
    if remote.get("billingType") not in BILLING_OK[row["method"]]:
        return f"meio de pagamento diferente ({remote.get('billingType')})"
    return None


def apply_remote(db: Database, row, remote: dict, *, source: str) -> dict:
    """Leva a compra ao estado que a API diz agora. Idempotente e insensível à ordem dos eventos."""
    led = Ledger(db)
    rs = str(remote.get("status") or "")
    bad = _mismatch(row, remote)
    if bad:
        db.conn.execute("UPDATE payments SET status=CASE WHEN status IN ('creating','pending') THEN 'mismatch' ELSE status END,"
                        " remote_status=?, synced_at=?, note=? WHERE id=?", (rs, now(), f"conferência: {bad}"[:300], row["id"]))
        log.warning("cobrança não confere com a que criamos: nada creditado",
                    extra={"event": "payment_mismatch", "payment_id": row["id"], "detail": bad, "source": source})
        return {"payment_id": row["id"], "status": "mismatch", "delta_cc": 0, "detail": bad}
    target = None
    if rs in PAID[row["method"]]:
        target, status = row["credits"] * 100, "paid"
    elif rs in CHARGEBACK:
        target, status = 0, "chargeback"
    elif rs in REFUND:
        target, status = 0, "refunded"
    elif remote.get("deleted"):
        status = "canceled" if row["status"] in OPEN else row["status"]
    elif rs == "OVERDUE":
        status = "expired" if row["status"] in OPEN else row["status"]
    else:   # PENDING, AWAITING_RISK_ANALYSIS, Pix CONFIRMED...: nada muda no saldo
        status = row["status"] if row["status"] not in ("creating", "mismatch") else "pending"
    delta = 0
    if target is not None:
        label = {"paid": f"{row['credits']} créditos ({'Pix' if row['method'] == 'pix' else 'cartão'})",
                 "chargeback": "contestação no cartão", "refunded": "compra estornada"}[status]
        delta = led.payment_entry(row["account_id"], row["id"], target, note=label)
    db.conn.execute("UPDATE payments SET status=?, remote_status=?, synced_at=?, "
                    "paid_at=CASE WHEN ?='paid' AND paid_at IS NULL THEN ? ELSE paid_at END, "
                    "refunded_at=CASE WHEN ? IN ('refunded','chargeback') AND refunded_at IS NULL THEN ? ELSE refunded_at END "
                    "WHERE id=?", (status, rs, now(), status, now(), status, now(), row["id"]))
    if delta:
        log.info("saldo ajustado pela compra", extra={"event": "payment_ledger", "payment_id": row["id"],
                                                      "delta_cc": delta, "status": status, "source": source})
    if status in ("chargeback", "refunded") and led.balance(row["account_id"]) < 0:
        log.warning("saldo negativo depois de estorno/contestação: novas produções bloqueadas",
                    extra={"event": "payment_negative_balance", "payment_id": row["id"]})
    return {"payment_id": row["id"], "status": status, "remote_status": rs, "delta_cc": delta}


def sync(db: Database, client, row, *, source: str = "manual") -> dict:
    if not row["asaas_payment_id"]:
        found = client_find_by_reference(client, row["id"])
        if found is None:
            if row["status"] == "creating" and _ts(row["created_at"]) < datetime.now(timezone.utc) - timedelta(hours=1):
                db.conn.execute("UPDATE payments SET status='failed', note='cobrança não chegou ao Asaas' WHERE id=?",
                                (row["id"],))
                return {"payment_id": row["id"], "status": "failed", "delta_cc": 0}
            return {"payment_id": row["id"], "status": row["status"], "delta_cc": 0}
        db.conn.execute("UPDATE payments SET asaas_payment_id=?, invoice_url=? WHERE id=?",
                        (found["id"], found.get("invoiceUrl"), row["id"]))
        row = get(db, row["id"])
    return apply_remote(db, row, client.get_payment(row["asaas_payment_id"]), source=source)


def client_find_by_reference(client, external_reference: str) -> dict | None:
    finder = getattr(client, "find_payment", None)
    return finder(external_reference) if finder else None


def poll(db: Database, client, row) -> dict:
    """Status para o polling da tela. Pendente: confere no Asaas no máximo a cada POLL_SYNC_S (rede de segurança se o
    webhook atrasar); a decisão é sempre a da API, nunca do navegador."""
    if row["status"] in OPEN and client is not None:
        last = row["synced_at"] or row["created_at"]
        if _ts(last) < datetime.now(timezone.utc) - timedelta(seconds=POLL_SYNC_S):
            try:
                sync(db, client, row, source="poll")
            except asaas.AsaasError as exc:
                log.warning("consulta ao Asaas falhou no polling", extra={"event": "payment_poll_error", "detail": str(exc)})
            row = get(db, row["id"])
    out = view(row)
    if row["status"] == "paid":
        out["balance"] = fmt_balance(Ledger(db).balance(row["account_id"]))
    return out


# =================================================================== webhook
def _safe_raw(data: dict) -> str:
    """Só o que serve para auditoria; nada de cartão, CPF/CNPJ, nome ou e-mail."""
    p = data.get("payment") if isinstance(data.get("payment"), dict) else {}
    keep = {k: p.get(k) for k in ("id", "status", "billingType", "value", "externalReference", "customer", "deleted",
                                  "dueDate", "paymentDate", "confirmedDate") if k in p}
    return json.dumps({"id": data.get("id"), "event": data.get("event"), "dateCreated": data.get("dateCreated"),
                       "payment": keep}, ensure_ascii=False)[:2000]


def receive_event(db: Database, data) -> tuple[int, dict, str | None]:
    """Grava o evento (uma vez por id). Devolve (http, corpo, event_id_para_processar | None)."""
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not isinstance(data.get("event"), str):
        return 400, {"error": "evento sem id"}, None
    eid, etype = data["id"][:200], data["event"][:80]
    p = data.get("payment") if isinstance(data.get("payment"), dict) else {}
    aid = str(p.get("id") or "")[:64] or None
    row = by_asaas_id(db, aid) if aid else None
    cur = db.conn.execute("INSERT OR IGNORE INTO payment_events(asaas_event_id, payment_id, asaas_payment_id, type, "
                          "received_at, raw) VALUES (?,?,?,?,?,?)",
                          (eid, row["id"] if row else None, aid, etype, now(), _safe_raw(data)))
    if cur.rowcount == 0:
        log.info("evento repetido do Asaas: ignorado", extra={"event": "payment_event_duplicate", "type": etype})
        return 200, {"ok": True, "duplicate": True}, None
    return 200, {"ok": True}, eid


def process_event(db: Database, client, event_id: str) -> str:
    ev = db.conn.execute("SELECT * FROM payment_events WHERE asaas_event_id=?", (event_id,)).fetchone()
    if ev is None or ev["processed_at"]:
        return "skip"
    row = by_asaas_id(db, ev["asaas_payment_id"]) if ev["asaas_payment_id"] else None
    if ev["type"] not in RELEVANT_EVENTS:
        outcome = "ignored"
        log.info("evento do Asaas sem efeito no saldo: ignorado", extra={"event": "payment_event_ignored", "type": ev["type"]})
    elif row is None:
        outcome = "unknown_payment"
        log.warning("evento de cobrança que não é nossa: ignorado", extra={"event": "payment_event_unknown", "type": ev["type"]})
    else:
        try:
            r = sync(db, client, row, source=f"webhook:{ev['type']}")
        except asaas.AsaasError as exc:   # fica sem processed_at: o reconcile tenta de novo
            db.conn.execute("UPDATE payment_events SET outcome='error' WHERE asaas_event_id=?", (event_id,))
            log.warning("falha ao conferir evento no Asaas", extra={"event": "payment_event_error", "detail": str(exc)})
            return "error"
        outcome = "synced" if r["status"] != "mismatch" else "mismatch"
        if ev["type"] == "PAYMENT_PARTIALLY_REFUNDED":
            db.conn.execute("UPDATE payments SET note='estorno parcial: revisar e ajustar créditos à mão' WHERE id=?",
                            (row["id"],))
            log.warning("estorno parcial: créditos não mexidos automaticamente; revisar",
                        extra={"event": "payment_partial_refund", "payment_id": row["id"]})
    db.conn.execute("UPDATE payment_events SET processed_at=?, outcome=?, payment_id=COALESCE(payment_id, ?) "
                    "WHERE asaas_event_id=?", (now(), outcome, row["id"] if row else None, event_id))
    return outcome


# =================================================================== reconciliação (webhook perdido)
def reconcile(db: Database, client, *, paid_days: int = 0) -> list[dict]:
    """Processa eventos pendentes e confere no Asaas as cobranças abertas (e as pagas dos últimos `paid_days` dias,
    para pegar estorno/contestação cujo aviso se perdeu)."""
    out = []
    for ev in db.conn.execute("SELECT asaas_event_id FROM payment_events WHERE processed_at IS NULL ORDER BY received_at").fetchall():
        out.append({"event": ev[0], "outcome": process_event(db, client, ev[0])})
    rows = db.conn.execute("SELECT * FROM payments WHERE status IN ('creating','pending','mismatch') ORDER BY created_at").fetchall()
    if paid_days > 0:
        since = (datetime.now(timezone.utc) - timedelta(days=paid_days)).isoformat(timespec="seconds")
        rows += db.conn.execute("SELECT * FROM payments WHERE status IN ('paid','chargeback','refunded') AND created_at>=? "
                                "ORDER BY created_at", (since,)).fetchall()
    for row in rows:
        try:
            out.append(sync(db, client, row, source="reconcile"))
        except asaas.AsaasError as exc:
            out.append({"payment_id": row["id"], "status": row["status"], "error": str(exc)})
    return out


# =================================================================== admin
def list_payments(db: Database, email: str | None = None, limit: int = 50) -> list[dict]:
    q = ("SELECT p.*, u.email FROM payments p LEFT JOIN users u ON u.id=p.user_id "
         + ("WHERE u.email=? " if email else "") + "ORDER BY p.created_at DESC LIMIT ?")
    args = ((email.strip().lower(), limit) if email else (limit,))
    return [dict(r) for r in db.conn.execute(q, args).fetchall()]


def month_metrics(db: Database, at: datetime | None = None) -> dict:
    """Receita BRUTA do mês (horário de Brasília), compras por meio e créditos vendidos × consumidos no mês."""
    at = (at or datetime.now(timezone.utc)).astimezone(BRT)
    start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat(timespec="seconds")
    try:
        paid = db.conn.execute("SELECT method, COUNT(*) n, COALESCE(SUM(amount_cents),0) cents, COALESCE(SUM(credits),0) cr "
                               "FROM payments WHERE paid_at>=? GROUP BY method", (start,)).fetchall()
    except Exception:  # noqa: BLE001 — banco sem a tabela (antes da migração 10)
        paid = []
    consumed = db.conn.execute("SELECT COALESCE(-SUM(amount_cc),0) FROM credit_entries WHERE kind='debit' AND created_at>=?",
                               (start,)).fetchone()[0]
    by = {r["method"]: {"purchases": r["n"], "revenue_cents": r["cents"]} for r in paid}
    for m in METHODS:
        by.setdefault(m, {"purchases": 0, "revenue_cents": 0})
    return {"month": at.strftime("%Y-%m"), "since": start, "gross_revenue_cents": sum(r["cents"] for r in paid),
            "by_method": by, "credits_sold": sum(r["cr"] for r in paid), "credits_consumed": round(consumed / 100, 2)}


# =================================================================== "Adicionar créditos" (manual, quando desligado)
def _contact(subject: str) -> dict | None:
    """STUDIO_SUPPORT_CONTACT: e-mail, endereço https:// (formulário, WhatsApp) ou texto livre. Vazio → sem contato."""
    import os
    raw = (os.environ.get("STUDIO_SUPPORT_CONTACT") or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("https://"):
        return {"label": "Falar com a equipe do Kiroo", "href": raw}
    if "@" in raw and " " not in raw:
        return {"label": raw, "href": f"mailto:{raw}?subject={quote(subject)}"}
    return {"label": raw, "href": None}


def topup_options(missing_cc: int | None = None) -> dict:
    """O que a interface mostra em "Adicionar créditos". `online` = compra pelo site (Asaas) ligada."""
    missing = max(int(missing_cc or 0), 0)
    if enabled():
        return {"provider": ASAAS, "online": True, "title": "Comprar créditos",
                "message": "Compre créditos por Pix ou cartão; o saldo atualiza assim que o pagamento é confirmado.",
                "steps": [], "contact": _contact("Comprar créditos no Kiroo"), "missing_cc": missing}
    subject = "Adicionar créditos no Kiroo"
    steps = ["Fale com a equipe do Kiroo e diga quantos créditos você precisa.",
             "A equipe libera os créditos na sua conta; o saldo atualiza aqui em seguida.",
             "Nada do que você já fez se perde enquanto isso."]
    if missing:
        steps[0] = f"Fale com a equipe do Kiroo e peça pelo menos {fmt(missing)} créditos (o que falta para este ajuste)."
    return {"provider": MANUAL, "online": False, "title": "Adicionar créditos",
            "message": "O pagamento pelo site ainda não está disponível. Por enquanto, os créditos são liberados pela equipe do Kiroo.",
            "steps": steps, "contact": _contact(subject), "missing_cc": missing}

