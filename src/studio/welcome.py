"""Bônus de boas-vindas: STUDIO_WELCOME_CREDITS (padrão 20 = 1 vídeo) uma vez por pessoa, depois de confirmar o e-mail.

Quando: no momento em que o e-mail fica confirmado (código de 6 dígitos, link de nova senha ou entrada pelo Google com
e-mail confirmado pelo Google). Cada usuário tem UMA decisão (concedido ou recusado, com motivo) em `welcome_bonuses`.

Anti-abuso (na ordem):
  * e-mail confirmado (sem isso, nem decide: tenta de novo na próxima confirmação);
  * um bônus por e-mail NORMALIZADO (minúsculas, sem +tag, sem pontos no gmail/googlemail);
  * um por dispositivo (id persistente do navegador, cookie `kiroo_dev`; sem id = recusado);
  * no máximo WELCOME_PER_IP (2) por IP em 24 h;
  * teto global por dia (horário de Brasília) STUDIO_WELCOME_DAILY_CAP (padrão 100), com aviso no log e nas métricas.
Índices únicos parciais (migração 11) fecham a corrida entre pedidos simultâneos.

O lançamento é `welcome_bonus` no livro: não é compra (não dá plano, não entra na receita) e nada o estorna. O vídeo
feito com ele é igual a qualquer outro (sem marca d'água).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from .credits import Ledger
from .db import Database, new_id, now

log = logging.getLogger("studio.welcome")

BRT = timezone(timedelta(hours=-3), "BRT")
WELCOME_PER_IP = 2
DEVICE_COOKIE = "kiroo_dev"
DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
GMAIL = {"gmail.com", "googlemail.com"}

GRANTED_TEXT = "Seu primeiro vídeo é por nossa conta. {n} créditos já estão na sua conta."


def credits() -> int:
    try:
        return max(int(os.environ.get("STUDIO_WELCOME_CREDITS") or 20), 0)
    except ValueError:
        return 20


def daily_cap() -> int:
    try:
        return max(int(os.environ.get("STUDIO_WELCOME_DAILY_CAP") or 100), 0)
    except ValueError:
        return 100


def normalize_email(email: str) -> str:
    """Fulano.Silva+loja@GMail.com → fulanosilva@gmail.com. Outros domínios: minúsculas e sem +tag."""
    e = (email or "").strip().lower()
    local, _, domain = e.rpartition("@")
    if not local or not domain:
        return e
    local = local.split("+", 1)[0]
    if domain in GMAIL:
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


def valid_device(device_id: str | None) -> str | None:
    d = (device_id or "").strip()
    return d if DEVICE_RE.fullmatch(d) else None


def _h(kind: str, value: str) -> str:
    return hashlib.sha256(f"kiroo-welcome:{kind}:{value}".encode()).hexdigest()


def _day_start_utc(at: datetime) -> str:
    d = at.astimezone(BRT).replace(hour=0, minute=0, second=0, microsecond=0)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


def _month_start_utc(at: datetime) -> str:
    d = at.astimezone(BRT).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


def state(db: Database, user_id: str) -> dict | None:
    """Bônus CONCEDIDO a este usuário (ou None)."""
    row = db.conn.execute("SELECT credits, created_at FROM welcome_bonuses WHERE user_id=? AND status='granted'",
                          (user_id,)).fetchone()
    return {"credits": row["credits"], "granted_at": row["created_at"]} if row else None


def try_grant(db: Database, *, user_id: str, workspace_id: str | None, device_id: str | None, ip: str,
              at: datetime | None = None) -> dict:
    """Decide (uma vez) o bônus deste usuário. Devolve {granted, credits, reason, message?}. Nunca levanta por regra
    de negócio: recusa vira reason (já decidido, sem e-mail confirmado, e-mail/dispositivo/IP repetido, teto)."""
    n = credits()
    u = db.conn.execute("SELECT email, email_verified_at FROM users WHERE id=?", (user_id,)).fetchone()
    if u is None or n <= 0:
        return {"granted": False, "credits": 0, "reason": "off" if n <= 0 else "no_user"}
    if not u["email_verified_at"]:
        return {"granted": False, "credits": 0, "reason": "email_unverified"}   # nem decide: espera a confirmação
    prev = db.conn.execute("SELECT status, reason, credits FROM welcome_bonuses WHERE user_id=? "
                           "ORDER BY (status='granted') DESC, created_at LIMIT 1", (user_id,)).fetchone()
    if prev is not None:
        return {"granted": False, "credits": 0, "reason": "already", "previous": prev["status"]}
    if workspace_id is None:
        ws = db.conn.execute("SELECT workspace_id FROM memberships WHERE user_id=? ORDER BY (role='owner') DESC, rowid LIMIT 1",
                             (user_id,)).fetchone()
        workspace_id = ws[0] if ws else None
    at = at or datetime.now(timezone.utc)
    email_norm = normalize_email(u["email"])
    dev = valid_device(device_id)
    dev_h = _h("device", dev) if dev else None
    ip_h = _h("ip", ip) if ip else None
    led = Ledger(db)

    with led.transaction():
        reason = None
        if workspace_id is None:
            reason = "no_workspace"
        elif db.conn.execute("SELECT 1 FROM welcome_bonuses WHERE email_norm=? AND status='granted'", (email_norm,)).fetchone():
            reason = "email"
        elif dev_h is None:
            reason = "no_device"
        elif db.conn.execute("SELECT 1 FROM welcome_bonuses WHERE device_hash=? AND status='granted'", (dev_h,)).fetchone():
            reason = "device"
        elif ip_h and db.conn.execute(
                "SELECT COUNT(*) FROM welcome_bonuses WHERE ip_hash=? AND status='granted' AND created_at>=?",
                (ip_h, (at - timedelta(hours=24)).isoformat(timespec="seconds"))).fetchone()[0] >= WELCOME_PER_IP:
            reason = "ip"
        elif db.conn.execute("SELECT COUNT(*) FROM welcome_bonuses WHERE status='granted' AND created_at>=?",
                             (_day_start_utc(at),)).fetchone()[0] >= daily_cap():
            reason = "daily_cap"
        bid = new_id("wb")
        if reason:
            db.conn.execute("INSERT INTO welcome_bonuses(id, user_id, workspace_id, email_norm, device_hash, ip_hash, "
                            "status, reason, credits, created_at) VALUES (?,?,?,?,?,?,?,?,0,?)",
                            (bid, user_id, workspace_id, email_norm, dev_h, ip_h, "denied", reason,
                             at.isoformat(timespec="seconds")))
        else:
            try:
                db.conn.execute("INSERT INTO welcome_bonuses(id, user_id, workspace_id, email_norm, device_hash, ip_hash, "
                                "status, credits, created_at) VALUES (?,?,?,?,?,?,'granted',?,?)",
                                (bid, user_id, workspace_id, email_norm, dev_h, ip_h, n, at.isoformat(timespec="seconds")))
            except sqlite3.IntegrityError:   # corrida: outro pedido concedeu para o mesmo e-mail/dispositivo/usuário
                reason = "race"
            else:
                eid = led.add(workspace_id, n * 100, kind="welcome_bonus", note="bônus de boas-vindas",
                              ext_ref=f"welcome:{user_id}")
                db.conn.execute("UPDATE welcome_bonuses SET entry_id=? WHERE id=?", (eid, bid))

    if reason:
        level = logging.WARNING if reason == "daily_cap" else logging.INFO
        log.log(level, "bônus de boas-vindas recusado", extra={"event": "welcome_denied", "reason": reason})
        return {"granted": False, "credits": 0, "reason": reason}
    log.info("bônus de boas-vindas concedido", extra={"event": "welcome_granted", "credits": n})
    return {"granted": True, "credits": n, "reason": None, "message": GRANTED_TEXT.format(n=n)}


def metrics(db: Database, at: datetime | None = None) -> dict:
    """Para o administrador: concedidos hoje/mês, quantos viraram compra paga e recusas de hoje por motivo."""
    at = at or datetime.now(timezone.utc)
    try:
        day, month = _day_start_utc(at), _month_start_utc(at)
        q = db.conn.execute
        today = q("SELECT COUNT(*) FROM welcome_bonuses WHERE status='granted' AND created_at>=?", (day,)).fetchone()[0]
        mon = q("SELECT COUNT(*) FROM welcome_bonuses WHERE status='granted' AND created_at>=?", (month,)).fetchone()[0]
        conv = ("SELECT COUNT(*) FROM welcome_bonuses w WHERE w.status='granted' {} AND EXISTS (SELECT 1 FROM payments p "
                "WHERE p.account_id=w.workspace_id AND p.paid_at IS NOT NULL AND p.paid_at>=w.created_at)")
        conv_month = q(conv.format("AND w.created_at>=?"), (month,)).fetchone()[0]
        total = q("SELECT COUNT(*) FROM welcome_bonuses WHERE status='granted'").fetchone()[0]
        conv_total = q(conv.format("")).fetchone()[0]
        denied = {r[0]: r[1] for r in q("SELECT reason, COUNT(*) FROM welcome_bonuses WHERE status='denied' AND "
                                        "created_at>=? GROUP BY reason", (day,)).fetchall()}
    except sqlite3.OperationalError:   # banco antes da migração 11
        return {"granted_today": 0, "granted_month": 0, "converted_month": 0, "granted_total": 0, "converted_total": 0,
                "denied_today": {}, "daily_cap": daily_cap(), "cap_reached_today": False, "credits": credits()}
    cap = daily_cap()
    return {"granted_today": today, "granted_month": mon, "converted_month": conv_month, "granted_total": total,
            "converted_total": conv_total, "denied_today": denied, "daily_cap": cap,
            "cap_reached_today": today >= cap, "credits": credits()}
