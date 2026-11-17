"""Jurídico e dados: aceites dos Termos, registro de acesso, retenção de mídia, lápides de exclusão e encerramento.

Tudo aqui é regra de produto PARA REVISÃO JURÍDICA; nenhum texto deste módulo afirma aprovação de advogado.

* Aceites (`terms_acceptances`): append-only (triggers da migração 17). `users.terms_*` continuam preenchidos.
* Acesso (`access_log`): usuário, IP, data e user-agent de cadastro/login, apagados após 6 meses. Nunca CPF/CNPJ.
* Retenção: mídia (fotos, vídeos, áudios, entregas) apagada com 60 dias; aviso por e-mail 7 dias antes, uma vez por
  produção. Metadados (id, datas, créditos) ficam para o extrato. Desligada por padrão (STUDIO_RETENTION_ENABLED).
* Lápides (`deletion_tombstones` + `deletions.jsonl`): o que foi apagado de propósito, para reaplicar depois de uma
  restauração de backup (`python -m studio restore reapply-deletions`).
* Encerramento (`account_closures`): conta encerrada pelo Kiroo; guarda o motivo e o avulso pago e não consumido, para
  reembolso MANUAL pela Stripe. Bônus não tem valor de restituição. Nada aqui confisca saldo.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import Database, now
from .states import ProductionStatus

log = logging.getLogger("studio.compliance")

ACCESS_LOG_DAYS = 183        # 6 meses (Marco Civil da Internet, art. 15)
RETENTION_DAYS = 60          # mídia de produções
NOTICE_DAYS = 7              # aviso antes de apagar
TRUE = {"1", "true", "yes", "sim", "on"}
# Só quem está sendo produzido AGORA nunca perde a mídia. Rascunho parado, vídeo para aprovar, pausado, concluído,
# falho ou cancelado entram na regra (aviso 7 dias antes e, 60 dias depois, apagamento), senão fotos enviadas e nunca
# usadas ficariam para sempre.
IN_PROGRESS = {ProductionStatus.PRODUCING.value, ProductionStatus.EDITING.value}


def retention_enabled() -> bool:
    return (os.environ.get("STUDIO_RETENTION_ENABLED") or "false").strip().lower() in TRUE


def _parse(ts: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


# ------------------------------------------------------------------ aceites
def record_acceptance(db: Database, uid: str, version: str, *, ip: str = "", user_agent: str = "", via: str = "signup") -> None:
    """Grava o aceite no histórico imutável e espelha em users.terms_* (compatibilidade)."""
    stamp = now()
    db.conn.execute("INSERT INTO terms_acceptances(user_id, version, accepted_at, ip, user_agent, via) VALUES (?,?,?,?,?,?)",
                    (uid, version, stamp, (ip or "")[:64] or None, (user_agent or "")[:300] or None, via))
    db.conn.execute("UPDATE users SET terms_accepted_at=?, terms_version=? WHERE id=?", (stamp, version, uid))


def accepted_version(db: Database, uid: str) -> str | None:
    row = db.conn.execute("SELECT version FROM terms_acceptances WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
    return row["version"] if row else None


def needs_acceptance(db: Database, uid: str, current: str, *, admin: bool = False) -> bool:
    """Quem já tem conta precisa aceitar a versão vigente. Administradores da plataforma (equipe) ficam de fora."""
    if admin:
        return False
    return accepted_version(db, uid) != current


# ------------------------------------------------------------------ registro de acesso
def record_access(db: Database, uid: str, kind: str, *, ip: str = "", user_agent: str = "") -> None:
    db.conn.execute("INSERT INTO access_log(user_id, kind, ip, user_agent, at) VALUES (?,?,?,?,?)",
                    (uid, kind, (ip or "")[:64] or None, (user_agent or "")[:300] or None, now()))


def purge_access_log(db: Database, *, days: int = ACCESS_LOG_DAYS, at: datetime | None = None) -> int:
    cutoff = _iso((at or _utc()) - timedelta(days=days))
    return db.conn.execute("DELETE FROM access_log WHERE at < ?", (cutoff,)).rowcount


# ------------------------------------------------------------------ lápides
def _tomb_file(data_dir: Path) -> Path:
    return data_dir / "deletions.jsonl"


def tombstone(db: Database, data_dir: Path, kind: str, ref: str) -> None:
    """Registra uma exclusão intencional no banco E num arquivo append-only fora do banco (que uma restauração do
    Litestream não desfaz). Guarda só o tipo e o id, nunca dado pessoal."""
    stamp = now()
    db.conn.execute("INSERT OR IGNORE INTO deletion_tombstones(kind, ref, deleted_at) VALUES (?,?,?)", (kind, ref, stamp))
    try:
        with _tomb_file(data_dir).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": kind, "ref": ref, "at": stamp}, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("não consegui gravar a lápide em arquivo", extra={"event": "tombstone_file_failed"})


def load_tombstones(db: Database, data_dir: Path) -> list[tuple[str, str]]:
    seen: dict[tuple[str, str], None] = {}
    for r in db.conn.execute("SELECT kind, ref FROM deletion_tombstones ORDER BY id"):
        seen[(r["kind"], r["ref"])] = None
    f = _tomb_file(data_dir)
    if f.is_file():
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                d = json.loads(line)
                seen[(str(d["kind"]), str(d["ref"]))] = None
            except (ValueError, KeyError, TypeError):
                continue
    return list(seen)


def reapply_deletions(db: Database, data_dir: Path) -> dict:
    """Depois de restaurar um backup: apaga de novo contas e mídia que já tinham sido excluídas de propósito.
    Idempotente. Contas administradoras nunca são apagadas por aqui."""
    from . import privacy
    out = {"users": 0, "production_media": 0}
    for kind, ref in load_tombstones(db, data_dir):
        if kind == "user":
            u = db.conn.execute("SELECT id, is_platform_admin FROM users WHERE id=?", (ref,)).fetchone()
            if u and not u["is_platform_admin"]:
                privacy.delete_account(db, data_dir, ref, record=False)
                out["users"] += 1
        elif kind == "production_media":
            if purge_production_media(db, data_dir, ref, record=False):
                out["production_media"] += 1
    return out


# ------------------------------------------------------------------ retenção de mídia
def media_expires_at(prod) -> str | None:
    """Data prevista de expiração da mídia (para a tela de produção); None se já foi apagada."""
    if prod["media_purged_at"] if "media_purged_at" in prod.keys() else None:
        return None
    base = _parse(prod["updated_at"]) or _parse(prod["created_at"])
    return _iso(base + timedelta(days=RETENTION_DAYS)) if base else None


def _owner(db: Database, wid: str | None):
    if not wid:
        return None
    return db.conn.execute("SELECT u.id, u.email, u.name FROM workspaces w JOIN users u ON u.id=w.owner_id WHERE w.id=?",
                           (wid,)).fetchone()


def purge_production_media(db: Database, data_dir: Path, pid: str, *, record: bool = True) -> bool:
    """Apaga os arquivos da produção (e as referências enviadas dentro do STUDIO_DATA_DIR). Mantém a linha no banco."""
    from .privacy import _rm
    row = db.conn.execute("SELECT product_json FROM productions WHERE id=?", (pid,)).fetchone()
    if row is None:
        return False
    try:
        refs = json.loads(row["product_json"]).get("references", [])
    except (ValueError, TypeError, AttributeError):
        refs = []
    for r in refs:
        if isinstance(r, dict) and r.get("path"):
            _rm(data_dir, Path(r["path"]))
    root = data_dir / "productions" / pid
    if root.is_dir():
        for child in root.iterdir():
            _rm(data_dir, child)
    db.conn.execute("UPDATE productions SET media_purged_at=COALESCE(media_purged_at, ?) WHERE id=?", (now(), pid))
    if record:
        tombstone(db, data_dir, "production_media", pid)
    return True


def run_retention(db: Database, data_dir: Path, *, dry_run: bool = True, send=None, link: str = "",
                  at: datetime | None = None) -> dict:
    """Uma passada da retenção. `send(to, subject, text, html) -> bool` envia o aviso (None = só relata).

    Regras: (1) com 53 dias ou mais e sem aviso, avisa o dono (um e-mail por dono, marca cada produção); (2) só apaga
    com 60 dias ou mais, com o aviso já enviado há 7 dias ou mais, e fora de produção em andamento. `dry_run` não
    envia, não apaga e não grava nada: só devolve o que faria."""
    t = at or _utc()
    notice_age, purge_age, notice_gap = (timedelta(days=RETENTION_DAYS - NOTICE_DAYS), timedelta(days=RETENTION_DAYS),
                                         timedelta(days=NOTICE_DAYS))
    rows = db.conn.execute("SELECT id, status, workspace_id, created_at, updated_at, retention_notice_at FROM productions"
                           " WHERE media_purged_at IS NULL").fetchall()
    notify: dict[str, list[str]] = {}
    purge: list[str] = []
    skipped_in_progress = 0
    for r in rows:
        base = _parse(r["updated_at"]) or _parse(r["created_at"])
        if base is None:
            continue
        age = t - base
        if r["status"] in IN_PROGRESS:
            skipped_in_progress += 1
            continue
        if not r["retention_notice_at"]:
            if age >= notice_age:
                notify.setdefault(r["workspace_id"] or "", []).append(r["id"])
            continue
        sent = _parse(r["retention_notice_at"])
        if age >= purge_age and sent and t - sent >= notice_gap:
            purge.append(r["id"])
    report = {"dry_run": dry_run, "would_notify": sum(len(v) for v in notify.values()), "would_purge": list(purge),
              "notified": 0, "purged": 0, "skipped_in_progress": skipped_in_progress, "access_log_purged": 0}
    if dry_run:
        return report
    if send is not None:
        for wid, pids in notify.items():
            owner = _owner(db, wid)
            if owner is None:
                continue
            subject, text, html = retention_email(owner["name"], len(pids), link)
            if send(owner["email"], subject, text, html):   # só marca depois de enviado: falhou, tenta na próxima passada
                db.conn.executemany("UPDATE productions SET retention_notice_at=? WHERE id=?", [(_iso(t), p) for p in pids])
                report["notified"] += len(pids)
    for pid in purge:
        if purge_production_media(db, data_dir, pid):
            report["purged"] += 1
    report["access_log_purged"] = purge_access_log(db, at=t)
    return report


def retention_email(name: str | None, count: int, link: str) -> tuple[str, str, str | None]:
    from . import mail_templates as mt
    greet = mt._greeting(name)
    plural = "produção" if count == 1 else "produções"
    subject = "Kiroo: seus arquivos serão apagados em 7 dias"
    text = (f"{greet}\n\nO Kiroo guarda fotos, vídeos e áudios por 60 dias. {count} {plural} sua(s) chega(m) a esse prazo "
            f"e os arquivos serão apagados em 7 dias. Baixe o que quiser guardar na lista de produções:\n\n{link}\n\n"
            "O extrato de créditos continua disponível.\n\n— Equipe Kiroo\n")
    if not link.startswith("https://"):
        return subject, text, None
    href = mt._esc(link)
    body = (f'<p style="margin:0;font-family:{mt.FONT};font-size:16px;line-height:1.5;"><a href="{href}" target="_blank"'
            f' style="color:{mt.INK};font-weight:700;">Abrir minhas produções</a></p>')
    page = mt._layout(preheader="Baixe seus vídeos antes que os arquivos sejam apagados.",
                      title="Seus arquivos serão apagados em 7 dias", greeting=greet,
                      intro=f"O Kiroo guarda fotos, vídeos e áudios por 60 dias. {count} {plural} sua(s) chega(m) a esse prazo.",
                      body_html=body, outro="O extrato de créditos continua disponível depois da limpeza.")
    return subject, text, page


# ------------------------------------------------------------------ suspensão e encerramento
def suspend_workspace(db: Database, wid: str, *, on: bool = True) -> None:
    """Suspensão temporária: bloqueia o uso, mas NÃO mexe no saldo (nenhum lote é baixado)."""
    db.conn.execute("UPDATE workspaces SET suspended_at=? WHERE id=?", (now() if on else None, wid))


def close_workspace(db: Database, wid: str, *, reason: str, by: str | None = None, note: str = "") -> dict:
    """Encerramento definitivo por iniciativa do Kiroo, sem culpa do usuário: registra o motivo e quanto do avulso pago
    ainda não foi consumido, para reembolso MANUAL pela Stripe. Não reembolsa, não baixa lote, não confisca.
    Bônus e plano não geram valor de restituição."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("informe o motivo do encerramento")
    topup = db.conn.execute("SELECT COALESCE(SUM(remaining_cc),0) FROM credit_lots WHERE workspace_id=? AND origin='topup'"
                            " AND closed_at IS NULL", (wid,)).fetchone()[0]
    promo = db.conn.execute("SELECT COALESCE(SUM(remaining_cc),0) FROM credit_lots WHERE workspace_id=? AND origin='bonus'"
                            " AND closed_at IS NULL", (wid,)).fetchone()[0]
    stamp = now()
    db.conn.execute("UPDATE workspaces SET closed_at=? WHERE id=? AND closed_at IS NULL", (stamp, wid))
    cur = db.conn.execute("INSERT INTO account_closures(workspace_id, reason, closed_at, closed_by, topup_refundable_cc,"
                          " promo_forfeited_cc, note) VALUES (?,?,?,?,?,?,?)",
                          (wid, reason[:500], stamp, by, int(topup), int(promo), note[:500]))
    return {"id": cur.lastrowid, "workspace_id": wid, "topup_refundable_cc": int(topup), "promo_cc": int(promo)}


# ------------------------------------------------------------------ tarefa agendada
def app_link() -> str:
    base = (os.environ.get("STUDIO_APP_URL") or "").strip().rstrip("/")
    return base + "/" if base else ""


def run_retention_job(db_path: Path, data_dir: Path, *, dry_run: bool) -> dict:
    """Abre o banco, roda uma passada e fecha. Com STUDIO_RETENTION_ENABLED desligado só o dry-run funciona."""
    from . import mailer
    if not dry_run and not retention_enabled():
        raise RuntimeError("retenção desligada: defina STUDIO_RETENTION_ENABLED=true (ou use --dry-run para só relatar)")
    db = Database(db_path)
    try:
        return run_retention(db, data_dir, dry_run=dry_run, send=mailer.send, link=app_link())
    finally:
        db.close()
