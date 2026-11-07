"""Direitos do titular (LGPD): exportar e apagar a própria conta e os dados dela.

Exportar: um JSON com a conta (sem hash de senha nem tokens), workspaces próprios, produções (ficha, roteiro, eventos,
tentativas sem caminhos internos), créditos, treinamento, trilhas, conversas (só contagem e custo: o texto não é
guardado) e a lista de arquivos de mídia (baixáveis por /media enquanto a conta existir).

Apagar: remove usuário, sessões, códigos, workspaces de que é dono, produções, cenas, tentativas, revisões, eventos,
treinamento, trilhas, conversas e os arquivos no disco (produções, uploads referenciados, trilhas, treinamento e
referências do workspace). O livro de créditos fica, desvinculado da pessoa (o workspace some e as notas são
substituídas), por possível obrigação fiscal/contábil — PARA REVISÃO JURÍDICA. Cópias de backup (Litestream/R2)
expiram pela retenção do backup.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .db import Database

USER_FIELDS = ("id", "email", "name", "created_at", "email_verified_at", "is_platform_admin", "onboarding_done_at",
               "terms_accepted_at", "terms_version")


class PrivacyError(ValueError):
    pass


def _rows(db: Database, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in db.conn.execute(sql, args).fetchall()]


def _owned_workspaces(db: Database, uid: str) -> list[str]:
    return [r["id"] for r in db.conn.execute("SELECT id FROM workspaces WHERE owner_id=?", (uid,))]


def _productions(db: Database, wids: list[str]) -> list[str]:
    if not wids:
        return []
    marks = ",".join("?" * len(wids))
    return [r["id"] for r in db.conn.execute(f"SELECT id FROM productions WHERE workspace_id IN ({marks})", wids)]


def _json_or_raw(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def export_account(db: Database, data_dir: Path, uid: str) -> dict:
    u = db.conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        raise PrivacyError("conta não encontrada")
    user = {k: u[k] for k in USER_FIELDS if k in u.keys()}
    user["login_google"] = bool(u["google_sub"])
    wids = _owned_workspaces(db, uid)
    out = {"exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "format": "kiroo-export-1",
           "user": user, "memberships": _rows(db, "SELECT workspace_id, role FROM memberships WHERE user_id=?", (uid,)),
           "workspaces": []}
    for wid in wids:
        ws = dict(db.conn.execute("SELECT * FROM workspaces WHERE id=?", (wid,)).fetchone())
        prods = []
        for pid in _productions(db, [wid]):
            p = dict(db.production(pid))
            for k in ("product_json", "sheet_json", "script_json", "profiles_json", "training_json", "music_json"):
                if k in p:
                    p[k] = _json_or_raw(p[k])
            p["scenes"] = _rows(db, "SELECT * FROM scenes WHERE production_id=?", (pid,))
            p["attempts"] = _rows(db, "SELECT id, scene_idx, kind, model, status, simulated, estimated_cost_usd, "
                                      "confirmed_cost_usd, created_at, output_path FROM attempts WHERE production_id=?", (pid,))
            p["reviews"] = _rows(db, "SELECT stage, scene_idx, reviewer, decision, created_at FROM reviews WHERE production_id=?", (pid,))
            p["events"] = _rows(db, "SELECT ts, type, scene_idx, message FROM events WHERE production_id=? ORDER BY id", (pid,))
            root = data_dir / "productions" / pid
            p["media_files"] = sorted(f.relative_to(root).as_posix() for f in root.rglob("*") if f.is_file()) if root.is_dir() else []
            prods.append(p)
        out["workspaces"].append({
            **ws, "productions": prods,
            "credits": _rows(db, "SELECT kind, amount_cc, usd, production_id, stage, note, created_at FROM credit_entries "
                                 "WHERE workspace_id=? ORDER BY created_at", (wid,)),
            "training": {"state": _rows(db, "SELECT agent_id, draft_json, active_version, updated_at FROM training_state WHERE workspace_id=?", (wid,)),
                         "versions": _rows(db, "SELECT agent_id, version, config_json, note, created_at FROM training_versions WHERE workspace_id=?", (wid,)),
                         "tests": _rows(db, "SELECT agent_id, task, executed, simulated, cost_usd, created_at FROM training_tests WHERE workspace_id=?", (wid,))},
            "music": _rows(db, "SELECT id, title, duration_s, mood, genre, origin, usage_terms, authorized_at, created_at "
                               "FROM music_tracks WHERE workspace_id=?", (wid,)),
        })
    out["chat"] = _rows(db, "SELECT agent, source, at, input_tokens, output_tokens, cost_usd FROM chat_log WHERE user_id=? ORDER BY at", (uid,))
    return out


def _inside(base: Path, p: Path) -> bool:
    try:
        p.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _rm(base: Path, p: Path) -> None:
    """Apaga só dentro de STUDIO_DATA_DIR (nunca segue um caminho gravado para fora dele)."""
    if not _inside(base, p) or p.resolve() == base.resolve():
        return
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    elif p.exists():
        p.unlink(missing_ok=True)


def delete_account(db: Database, data_dir: Path, uid: str, *, allow_admin: bool = False) -> dict:
    """Apaga a conta. Recusa administrador da plataforma (só a CLI, com allow_admin) e workspace com outros membros."""
    u = db.conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        raise PrivacyError("conta não encontrada")
    if u["is_platform_admin"] and not allow_admin:
        raise PrivacyError("conta de administrador não pode ser apagada por aqui")
    wids = _owned_workspaces(db, uid)
    for wid in wids:
        others = db.conn.execute("SELECT COUNT(*) FROM memberships WHERE workspace_id=? AND user_id<>?", (wid, uid)).fetchone()[0]
        if others:
            raise PrivacyError("há outras pessoas neste estúdio: transfira ou remova antes de apagar a conta")
    pids = _productions(db, wids)
    files: list[Path] = []
    for pid in pids:   # uploads referenciados pela ficha (cópias recebidas pela interface; originais da CLI ficam)
        try:
            refs = json.loads(db.production(pid)["product_json"]).get("references", [])
        except (KeyError, ValueError, TypeError):
            refs = []
        files += [Path(r["path"]) for r in refs if isinstance(r, dict) and r.get("path")]
        files.append(data_dir / "productions" / pid)
    for wid in wids:
        files += [data_dir / "workspaces" / wid, data_dir / "music" / wid, data_dir / "training" / wid]

    db.conn.execute("BEGIN IMMEDIATE")
    try:
        c = db.conn
        if pids:
            marks = ",".join("?" * len(pids))
            for table in ("run_state", "events", "reviews", "attempts", "scenes"):
                c.execute(f"DELETE FROM {table} WHERE production_id IN ({marks})", pids)
            c.execute(f"DELETE FROM productions WHERE id IN ({marks})", pids)
        for wid in wids:
            for table in ("music_tracks", "music_favorites", "training_state", "training_versions", "training_tests"):
                c.execute(f"DELETE FROM {table} WHERE workspace_id=?", (wid,))
            # livro de créditos: fica sem vínculo com a pessoa (PARA REVISÃO JURÍDICA: prazo de guarda)
            c.execute("UPDATE credit_entries SET note='conta apagada', created_by=NULL WHERE workspace_id=?", (wid,))
        c.execute("DELETE FROM chat_log WHERE user_id=?", (uid,))
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        c.execute("DELETE FROM email_codes WHERE user_id=?", (uid,))
        c.execute("DELETE FROM password_resets WHERE user_id=?", (uid,))
        c.execute("DELETE FROM login_attempts WHERE key=?", (f"e:{u['email']}",))
        c.execute("UPDATE invites SET used_by=NULL, email=NULL WHERE used_by=? OR email=?", (uid, u["email"]))
        c.execute("DELETE FROM memberships WHERE user_id=?", (uid,))
        for wid in wids:
            c.execute("DELETE FROM memberships WHERE workspace_id=?", (wid,))
            c.execute("DELETE FROM workspaces WHERE id=?", (wid,))
        c.execute("DELETE FROM users WHERE id=?", (uid,))
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    for f in files:   # depois do COMMIT: se o disco falhar, a conta já não existe e o arquivo fica órfão (sem dono)
        _rm(data_dir, f)
    return {"productions": len(pids), "workspaces": len(wids)}
