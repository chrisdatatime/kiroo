"""Servidor da interface (stdlib) com contas e workspaces (Fase B).

Proteções:
- Host permitido (contra DNS rebinding); escuta em 127.0.0.1 por padrão.
- Sessão por cookie HttpOnly + SameSite=Lax; toda ação POST exige o token CSRF da sessão (cabeçalho).
- Cadastro/login exigem cabeçalho próprio do cliente (força preflight em outro site) e têm limite de tentativas.
- Cada produção, mídia, gasto e teto pertence a um workspace; acesso fora dele responde 404.
- Contas novas ficam em DEMO até o administrador liberar o modo real (custos saem da conta Google do operador).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .. import agent_config, creative_options
from ..accounts import Accounts, AuthError
from ..config import load_settings
from ..credits import Ledger
from ..db import Database
from ..factory import build
from ..models import ProductInput
from ..orchestrator import OrchestratorError
from ..profiles import KINDS, available_versions, load_profile
from ..profiles import snapshot as snapshot_profiles
from ..providers.simulated import SimulationScript
from ..spend import spend_report
from ..storage import ProductionStorage, StorageError
from .uploads import UploadError, build_product, parse_creative, save_uploads
from .view import snapshot

log = logging.getLogger("studio")
STATIC = Path(__file__).parent / "static"
PID_RE = re.compile(r"^prod_[0-9a-f]{10}$")
MEDIA_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".txt", ".md", ".json"}
ACTIONS = {"run", "approve", "reject", "final", "pause", "resume", "cancel", "budget", "references", "validate",
           "direction", "go_ahead", "autonomy", "edit", "music"}
GAME_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"   # build do jogo (npm run build)
MAX_BODY = 150 * 1024 * 1024  # uploads em base64
MAX_AUTH_BODY = 64 * 1024  # rotas sem sessão não recebem envio grande
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"}
FORM_DEFAULTS = {"name": "x", "variant": "x", "affiliate_link": "https://shopee.com.br/x"}
COOKIE = "studio_session"
CLIENT_HEADER = "X-Studio-Client"   # obrigatório em cadastro/login (não é enviável por formulário de outro site)


@dataclass
class Response:
    status: int
    content_type: str = "application/json; charset=utf-8"
    body: bytes = b""
    file: Path | None = None
    headers: dict = field(default_factory=dict)


def _json(status: int, data, headers: dict | None = None) -> Response:
    return Response(status, body=json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"), headers=headers or {})


def _cookie(headers: dict) -> str | None:
    raw = headers.get("Cookie") or headers.get("cookie") or ""
    for part in raw.split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE and v:
            return v
    return None


class App:
    def __init__(self, port: int = 8765, *, settings_loader=load_settings, sim_pacing: bool = True,
                 allowed_hosts: set[str] | None = None, secure_cookie: bool | None = None,
                 public_host: str | None = None):
        self.port = port
        self.load_settings = settings_loader
        self.sim_pacing = sim_pacing
        extra = {h.strip() for h in (os.environ.get("STUDIO_ALLOWED_HOSTS") or "").split(",") if h.strip()}
        self.allowed_hosts = allowed_hosts or ({f"127.0.0.1:{port}", f"localhost:{port}"} | extra)
        # Endereço público (túnel): o cadastro fecha (só convite pela CLI) e o cookie desse endereço vira Secure.
        self.public_host = public_host or os.environ.get("STUDIO_PUBLIC_HOST") or None
        if self.public_host:
            self.allowed_hosts = self.allowed_hosts | {self.public_host}
        self.secure_cookie = secure_cookie if secure_cookie is not None else (os.environ.get("STUDIO_SECURE_COOKIE") == "1")
        self.runs: dict[str, threading.Thread] = {}
        self.errors: dict[str, str] = {}
        self.lock = threading.Lock()

    # ------------------------------------------------------------ contexto
    def settings(self):
        return self.load_settings()

    def _db(self):
        s = self.settings()
        db = Database(s.db_path)
        return s, db, Accounts(db)

    def ws_settings(self, s, ws):
        """Configuração efetiva do workspace: modo, teto do mês e pasta de referências próprias."""
        if ws is None:
            return s
        owner_admin = False
        assets = s.data_dir / "workspaces" / ws["id"] / "assets"
        try:
            db = Database(s.db_path)
            row = db.conn.execute("SELECT is_platform_admin FROM users WHERE id=?", (ws["owner_id"],)).fetchone()
            owner_admin = bool(row and row[0])
            db.close()
        except Exception:  # noqa: BLE001
            pass
        real = ws["mode"] == "real" and bool(ws["allow_real"]) and bool(s.gemini_api_key)
        return dataclasses.replace(s, mode="real" if real else "simulated", allow_paid_calls=real,
                                   monthly_cap_usd=ws["monthly_cap_usd"],
                                   assets_dir=s.assets_dir if owner_admin else assets)

    def _workspace_of_production(self, pid: str):
        s, db, acc = self._db()
        try:
            row = db.production(pid)
            wid = row["workspace_id"] if "workspace_id" in row.keys() else None
            return s, (acc.workspace(wid) if wid else None), row["mode"]
        finally:
            db.close()

    def orch_for(self, pid: str):
        s, ws, mode = self._workspace_of_production(pid)
        s = self.ws_settings(s, ws)
        if mode == "simulated":
            s = dataclasses.replace(s, mode="simulated", poll_interval_s=0.8 if self.sim_pacing else 0.0)
            pacing = SimulationScript(video_polls_before_done=1 if self.sim_pacing else 0)
            return build(s, sim_script=pacing, sleep=time.sleep if self.sim_pacing else (lambda _: None))
        if s.mode != "real" or not s.allow_paid_calls:
            raise OrchestratorError("Modo DEMO ligado neste estúdio: produções reais ficam paradas até desligar o DEMO.")
        return build(s)

    def is_running(self, pid: str) -> bool:
        t = self.runs.get(pid)
        return bool(t and t.is_alive())

    def start_run(self, pid: str) -> bool:
        with self.lock:
            if self.is_running(pid):
                return False
            self.errors.pop(pid, None)
            t = threading.Thread(target=self._run, args=(pid,), daemon=True, name=f"run-{pid}")
            self.runs[pid] = t
            t.start()
            return True

    def _run(self, pid: str) -> None:
        orch = None
        try:
            orch = self.orch_for(pid)
            orch.run(pid)
        except Exception as exc:  # noqa: BLE001 — mostrado na interface
            self.errors[pid] = f"{type(exc).__name__}: {exc}"[:500]
        finally:
            if orch is not None:
                orch.db.close()

    def _is_public(self, headers: dict) -> bool:
        return bool(self.public_host) and headers.get("Host") == self.public_host

    def _client_ip(self, headers: dict) -> str:
        """IP real só vem do túnel, que sobrescreve este cabeçalho. X-Forwarded-For seria falsificável pelo cliente."""
        if not self._is_public(headers):
            return "local"
        return next((v for k, v in headers.items() if k.lower() == "cf-connecting-ip"), "") or "publico"

    def _set_cookie(self, token: str, max_age: int, *, secure: bool = False) -> dict:
        flags = f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"
        if self.secure_cookie or secure:
            flags += "; Secure"
        return {"Set-Cookie": flags}

    # ----------------------------------------------------------------- rotas
    def handle(self, method: str, raw_path: str, headers: dict, body: bytes) -> Response:
        if headers.get("Host", "") not in self.allowed_hosts:
            return _json(403, {"error": "host não permitido"})
        url = urlparse(raw_path)
        path = url.path
        try:
            # --- públicas: o jogo (que mostra a tela de entrar) e seus arquivos
            if method == "GET" and path in ("/", "/index.html") and (GAME_DIST / "index.html").is_file():
                return Response(200, "text/html; charset=utf-8", (GAME_DIST / "index.html").read_bytes())
            if method == "GET" and path.startswith("/assets/"):
                f = (GAME_DIST / path.lstrip("/")).resolve()
                if GAME_DIST.resolve() not in f.parents or not f.is_file():
                    return _json(404, {"error": "não encontrado"})
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                return Response(200, "text/javascript; charset=utf-8" if f.suffix == ".js" else ctype, file=f)
            if method == "POST" and path.startswith("/api/auth/"):
                return self._auth(path, headers, json.loads(body or b"{}"))

            # --- daqui em diante: só com sessão
            token = _cookie(headers)
            s, db, acc = self._db()
            try:
                sess = acc.session(token)
                ws = acc.workspace(sess["workspace_id"]) if sess else None
                workspaces = acc.workspaces_of(sess["user_id"]) if sess else []
            finally:
                db.close()
            if not sess:
                if method == "GET" and path in ("/painel", "/painel/", "/"):
                    return Response(302, "text/plain", b"", headers={"Location": "/"}) if path != "/" else _json(401, {"error": "entre na sua conta"})
                return _json(401, {"error": "entre na sua conta"})
            ctx = {"sess": sess, "ws": ws, "wid": ws["id"], "admin": bool(sess["is_platform_admin"]),
                   "s": self.ws_settings(s, ws), "workspaces": workspaces}

            if method == "GET":
                return self._get(path, url, ctx)
            if method == "POST":
                if headers.get("X-Studio-Token") != sess["csrf"]:
                    return _json(403, {"error": "token ausente ou inválido"})
                return self._post(path, json.loads(body or b"{}"), ctx, token)
            return _json(405, {"error": "método não permitido"})
        except AuthError as exc:
            return _json(400, {"error": str(exc)})
        except (OrchestratorError, ValueError, KeyError, StorageError, UploadError) as exc:
            return _json(400, {"error": str(exc)})  # TrainingError e MusicError são ValueError

    # --- autenticação
    def _auth(self, path: str, headers: dict, p: dict) -> Response:
        if headers.get(CLIENT_HEADER) != "game":
            return _json(403, {"error": "cliente não permitido"})
        ip = self._client_ip(headers)
        secure = self._is_public(headers)
        s, db, acc = self._db()
        try:
            if path == "/api/auth/signup":
                if self.public_host:
                    return _json(403, {"error": "Cadastro só por convite: peça sua conta ao administrador."})
                first = db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
                uid, wid = acc.create_user(p.get("email", ""), p.get("password", ""), p.get("name", ""), admin=first,
                                           workspace_name=p.get("workspace") or None)
                if first:  # primeira conta = administrador: recebe as produções existentes e o modo/teto atuais
                    acc.assign_orphans(wid)
                    acc.set_workspace(wid, allow_real=1, mode=s.mode, monthly_cap_usd=s.monthly_cap_usd, credits_exempt=1)
                token, info = acc.create_session(uid, wid)
                return _json(200, {"ok": True, "admin": first}, self._set_cookie(token, 30 * 86400, secure=secure))
            if path == "/api/auth/login":
                token, info = acc.login(p.get("email", ""), p.get("password", ""), ip)
                return _json(200, {"ok": True}, self._set_cookie(token, 30 * 86400, secure=secure))
            if path == "/api/auth/logout":
                acc.logout(_cookie(headers))
                return _json(200, {"ok": True}, self._set_cookie("", 0, secure=secure))
            if path == "/api/auth/forgot":
                tok = acc.start_reset(p.get("email", ""))
                if tok:  # ainda sem provedor de e-mail: o link vai para o log do servidor (só o operador vê)
                    log.warning("Link de redefinição de senha (válido 30 min): /?reset=%s", tok)
                return _json(200, {"ok": True, "message": "Se houver conta com este e-mail, o link de redefinição foi gerado. "
                                                          "Envio por e-mail ainda não está configurado: peça o link ao administrador."})
            if path == "/api/auth/reset":
                acc.finish_reset(p.get("token", ""), p.get("password", ""))
                return _json(200, {"ok": True})
            return _json(404, {"error": "não encontrado"})
        finally:
            db.close()

    # --- leitura
    def _get(self, path: str, url, ctx) -> Response:
        s, wid = ctx["s"], ctx["wid"]
        if path.startswith("/api/training") or path.startswith("/api/music"):
            from .agents_api import get_agents
            return get_agents(self, path, ctx)
        if path in ("/painel", "/painel/") or (path in ("/", "/index.html") and not (GAME_DIST / "index.html").is_file()):
            if not ctx["admin"]:
                return _json(403, {"error": "painel restrito ao administrador"})
            html = (STATIC / "index.html").read_text(encoding="utf-8").replace("__STUDIO_TOKEN__", ctx["sess"]["csrf"])
            return Response(200, "text/html; charset=utf-8", html.encode("utf-8"))
        if path in ("/api/me", "/api/credits"):
            ws = ctx["ws"]
            db = Database(s.db_path)
            try:
                led = Ledger(db)
                credits = led.summary(ws["id"])
                if path == "/api/credits":  # extrato e consumo por produção/etapa (Fase C)
                    return _json(200, {**credits, "statement": led.statement(ws["id"]), "usage": led.usage(ws["id"])})
            finally:
                db.close()
            return _json(200, {"csrf": ctx["sess"]["csrf"], "admin": ctx["admin"],
                               "user": {"email": ctx["sess"]["email"], "name": ctx["sess"]["name"]},
                               "workspace": {"id": ws["id"], "name": ws["name"], "mode": s.mode, "allow_real": bool(ws["allow_real"]),
                                             "credits": credits},
                               "workspaces": [{"id": w["id"], "name": w["name"], "role": w["role"]} for w in ctx["workspaces"]]})
        if path == "/api/state":
            q = parse_qs(url.query)
            pid = q.get("pid", [None])[0] or None
            if pid and not PID_RE.match(pid):
                return _json(400, {"error": "id inválido"})
            since = int(q.get("since", ["0"])[0] or 0)
            db = Database(s.db_path)
            try:
                if pid and not Accounts(db).owns(wid, pid):
                    pid = None
                data = snapshot(s, db, pid, since=since, workspace_id=wid)
                sel = data["selected"]
                if sel:
                    data = snapshot(s, db, sel, since=since, running=self.is_running(sel), error=self.errors.get(sel),
                                    workspace_id=wid)
                data["credits"] = Ledger(db).summary(wid)
            finally:
                db.close()
            return _json(200, data)
        if path.startswith("/media/"):
            return self._media(path, ctx)
        if path == "/api/creative/options":
            q = parse_qs(url.query)
            has_bia = (s.assets_dir / "bia" / "PERFIL BIA.jpg").is_file()
            return _json(200, {**creative_options.catalogue(),
                               **creative_options.ideas(q.get("name", [""])[0], q.get("category", [""])[0], has_bia)})
        if path == "/api/spend":
            db = Database(s.db_path)
            try:
                return _json(200, spend_report(db, s.monthly_cap_usd, workspace_id=wid))
            finally:
                db.close()
        if path == "/api/profiles":
            out = {}
            for kind in KINDS:
                out[kind] = []
                base = s.profiles_dir / kind
                for d in sorted(x for x in base.iterdir() if x.is_dir()) if base.exists() else []:
                    data = load_profile(s.profiles_dir, kind, d.name)
                    out[kind].append({"id": d.name, "versions": available_versions(s.profiles_dir, kind, d.name),
                                      "description": data.get("description_pt", "")})
            return _json(200, out)
        return _json(404, {"error": "não encontrado"})

    # --- escrita
    def _post(self, path: str, payload: dict, ctx, token: str) -> Response:
        s, wid = ctx["s"], ctx["wid"]
        if path == "/api/config":
            if not ctx["admin"]:
                return _json(403, {"error": "configuração técnica restrita ao administrador"})
            base = self.settings()
            current = {k: getattr(base, k) for k in agent_config.field_options()}
            agent_config.save(base.data_dir, settings=payload.get("settings"), agents=payload.get("agents"), current=current)
            return _json(200, {"ok": True})
        if path == "/api/runtime":
            return self._runtime(payload, ctx)
        if path == "/api/workspace/switch":
            s0, db, acc = self._db()
            try:
                acc.switch_workspace(token, str(payload.get("workspace_id")))
            finally:
                db.close()
            return _json(200, {"ok": True})
        if path.startswith("/api/training/") or path.startswith("/api/music"):
            from .agents_api import post_agents
            return post_agents(self, path, payload, ctx)
        if path == "/api/productions":
            return self._create(payload, ctx)
        if path == "/api/creative/preview":
            return _json(200, self._preview(payload, s))
        if path == "/api/demo":
            sim = dataclasses.replace(s, mode="simulated")
            orch = build(sim)
            try:
                from ..demo import create_demo_production
                pid = create_demo_production(orch, sim, budget_usd=float(payload.get("budget", 5.0)))
                orch.db.update_production(pid, workspace_id=wid)
            finally:
                orch.db.close()
            self.start_run(pid)
            return _json(200, {"ok": True, "pid": pid})
        m = re.fullmatch(r"/api/productions/(prod_[0-9a-f]{10})/(\w+)", path)
        if m and m.group(2) in ACTIONS:
            db = Database(s.db_path)
            try:
                owned = Accounts(db).owns(wid, m.group(1))
            finally:
                db.close()
            if not owned:
                return _json(404, {"error": "produção não encontrada"})
            return self._action(m.group(1), m.group(2), payload, s)
        return _json(404, {"error": "não encontrado"})

    def _runtime(self, payload: dict, ctx) -> Response:
        ws, base = ctx["ws"], self.settings()
        fields = {}
        if payload.get("monthly_cap_usd") is not None:
            cap = float(payload["monthly_cap_usd"])
            if not 0 <= cap <= 10000:
                raise ValueError("teto mensal deve estar entre 0 e 10000 US$")
            fields["monthly_cap_usd"] = cap
        mode = payload.get("mode")
        if mode is not None:
            if mode == "real":
                if not ws["allow_real"]:
                    return _json(403, {"error": "Este estúdio está em DEMO até a cobrança por créditos ser liberada."})
                if not base.gemini_api_key:
                    raise ValueError("defina GEMINI_API_KEY no .env antes de desligar o DEMO")
                if fields.get("monthly_cap_usd", ws["monthly_cap_usd"]) <= 0:
                    raise ValueError("defina um teto mensal de gastos maior que zero antes de desligar o DEMO")
            fields["mode"] = mode
        s0, db, acc = self._db()
        try:
            acc.set_workspace(ws["id"], **fields)
        finally:
            db.close()
        return _json(200, {"ok": True})

    def _preview(self, payload: dict, s) -> dict:
        """Monta as instruções de geração a partir das escolhas. Determinístico, sem chamadas pagas."""
        from ..agents.creative import build_draft
        from ..claims import find_unsupported_claims
        from ..models import ProductSheet
        choices = parse_creative(payload.get("creative"))
        product = build_product({**FORM_DEFAULTS, **{k: v for k, v in payload.items() if v}}, [], strict=False)
        resolved = creative_options.resolve(choices, product.name, product.category)
        snap = snapshot_profiles(s.profiles_dir, creative_options.profile_ids(resolved))
        sheet = ProductSheet.model_construct(product=product.model_copy(update={"creative": choices}), issues=[],
                                             unknown_fields=[], presenter_assets={}, validated_at=None)
        draft = build_draft(sheet, snap)
        warnings = []
        for label, text in (("detalhe", choices.details_text), ("ambiente", choices.environment_custom)):
            bad = find_unsupported_claims(text, sheet)
            if bad:
                warnings.append(f"O {label} digitado parece descrever uma característica do produto ({', '.join(bad)}). "
                                "Use só se estiver nas informações comprovadas; a legenda não vai citar isso.")
        return {
            "summary": creative_options.summary_pt(resolved), "resolved": resolved.model_dump(),
            "direction": creative_options.compose_direction(resolved),
            "auto_direction": creative_options.compose_direction(resolved.model_copy(update={"manual_direction": None})),
            "profiles": {k: f"{v['id']}@{v['version']}" for k, v in snap.items()},
            "scenes": [{"index": sc.index, "title": sc.title, "image_prompt": sc.image_prompt,
                        "animation_prompt": sc.animation_prompt} for sc in draft.scenes],
            "warnings": warnings,
        }

    def _create(self, payload: dict, ctx) -> Response:
        s = ctx["s"]
        autonomy = str(payload.get("autonomy") or ("manual" if payload.get("flow") == "game" else "classico"))
        if payload.get("creative"):
            choices = creative_options.resolve(parse_creative(payload["creative"]), str(payload.get("name", "")),
                                               payload.get("category"))
            ids = creative_options.profile_ids(choices)
            payload = {**payload, "format": ids["format"], "art": ids["art_direction"], "presenter": "bia",
                       "creative": choices.model_dump()}
        files = save_uploads(s.data_dir, payload.get("files") or [])
        product = build_product(payload, files)
        orch = build(s)
        try:
            pid = orch.create_production(product, format_id=payload.get("format") or "maos_3cenas_15s",
                                         art_direction=payload.get("art") or "cozinha_sp_alto_padrao",
                                         presenter=payload.get("presenter") or "bia",
                                         budget_usd=float(payload.get("budget") or 0),
                                         go_ahead=("none" if autonomy == "manual" else "all") if payload.get("flow") == "game" else "all",
                                         autonomy=autonomy, workspace_id=ctx["wid"])
        finally:
            orch.db.close()
        if payload.get("start", True):
            self.start_run(pid)
        return _json(200, {"ok": True, "pid": pid, "mode": s.mode})

    def _media(self, path: str, ctx) -> Response:
        parts = path.split("/", 3)
        if len(parts) < 4 or not PID_RE.match(parts[2]):
            return _json(404, {"error": "não encontrado"})
        s = ctx["s"]
        db = Database(s.db_path)
        try:
            owned = Accounts(db).owns(ctx["wid"], parts[2])
        finally:
            db.close()
        if not owned or not (s.data_dir / "productions" / parts[2]).is_dir():
            return _json(404, {"error": "não encontrado"})
        f = ProductionStorage(s.data_dir, parts[2]).path(unquote(parts[3]))
        if f.suffix.lower() not in MEDIA_EXTS or not f.is_file():
            return _json(404, {"error": "não encontrado"})
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or f.suffix in (".md", ".json"):
            ctype = ("text/markdown" if f.suffix == ".md" else ctype) + "; charset=utf-8"
        return Response(200, ctype, file=f)

    def _action(self, pid: str, action: str, payload: dict, s) -> Response:
        if action == "run":
            self.orch_for(pid).db.close()  # valida se a produção pode rodar no modo atual
            return _json(200, {"ok": True, "started": self.start_run(pid)})
        if action in {"validate", "direction", "go_ahead", "autonomy", "edit", "music"}:
            if self.is_running(pid):
                return _json(409, {"error": "a produção está em execução; aguarde"})
            orch = self.orch_for(pid)
            try:
                if action == "validate":
                    return _json(200, {"ok": orch.validate(pid)})
                if action == "direction":
                    product = ProductInput.model_validate_json(orch.db.production(pid)["product_json"])
                    choices = creative_options.resolve(parse_creative(payload.get("creative")), product.name, product.category)
                    orch.update_product(pid, product.model_copy(update={"creative": choices, "video_context": choices.details_text}))
                if action == "go_ahead":
                    orch.set_go_ahead(pid, str(payload.get("stage")))
                if action == "autonomy":
                    orch.set_autonomy(pid, str(payload.get("mode")))
                if action == "music":
                    orch.set_music(pid, payload)
                    continue_after = PS(orch.db.production(pid)["status"]) == PS.EDITING
                if action == "edit":  # estilo/trilha da montagem; com vídeo pronto, remonta sem custo de geração
                    orch.set_edit(pid, str(payload.get("style")), str(payload.get("music") or "auto"))
            finally:
                orch.db.close()
            self.start_run(pid)
            return _json(200, {"ok": True})
        if action == "references":
            if self.is_running(pid):
                return _json(409, {"error": "a produção está em execução; aguarde"})
            files = save_uploads(s.data_dir, payload.get("files") or [])
            orch = self.orch_for(pid)
            try:
                product = ProductInput.model_validate_json(orch.db.production(pid)["product_json"])
                kept = [] if payload.get("replace") else [r for r in product.references if Path(r.path).is_file()]
                update = {"references": kept + files}
                if payload.get("visual_attributes") is not None:
                    update["visual_attributes"] = build_product(
                        {**FORM_DEFAULTS, "visual_attributes": payload["visual_attributes"]}, []).visual_attributes
                if payload.get("video_context") is not None:
                    update["video_context"] = str(payload["video_context"])[:2000]
                    if product.creative is not None:
                        update["creative"] = product.creative.model_copy(update={"details_text": update["video_context"][:600]}).model_dump()
                orch.update_product(pid, ProductInput.model_validate({**product.model_dump(), **update}))
            finally:
                orch.db.close()
            self.start_run(pid)
            return _json(200, {"ok": True, "added": len(files)})
        if self.is_running(pid) and action in {"approve", "reject", "final", "budget"}:
            return _json(409, {"error": "a produção está em execução; aguarde terminar a etapa atual"})
        orch = self.orch_for(pid)
        try:
            continue_after = True
            if action == "approve":
                orch.approve(pid, int(payload["scene"]), payload["stage"], payload.get("note", ""))
            elif action == "reject":
                orch.reject(pid, int(payload["scene"]), payload["stage"], payload.get("note", ""), redo_image=bool(payload.get("redo_image")))
            elif action == "final":
                approve = payload.get("decision") == "approve"
                orch.final_decision(pid, approve, payload.get("note", ""))
                continue_after = not approve
            elif action == "pause":
                orch.pause(pid); continue_after = False
            elif action == "resume":
                orch.resume(pid)
            elif action == "cancel":
                orch.cancel(pid); continue_after = False
            elif action == "budget":
                orch.set_budget(pid, float(payload["value"])); continue_after = False
        finally:
            orch.db.close()
        if continue_after:
            self.start_run(pid)
        return _json(200, {"ok": True})


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "StudioUI/1"

        def log_message(self, fmt, *args):  # silencioso no terminal
            pass

        def _send(self, resp: Response) -> None:
            if resp.file is None:
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.content_type)
                self.send_header("Content-Length", str(len(resp.body)))
                self.send_header("Cache-Control", "no-store")
                for k, v in {**SECURITY_HEADERS, **resp.headers}.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.body)
                return
            size = resp.file.stat().st_size
            start, end = 0, size - 1
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(size - int(m.group(2)), 0)
                end = min(end, size - 1)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", resp.content_type)
            self.send_header("Accept-Ranges", "bytes")
            for k, v in SECURITY_HEADERS.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            with open(resp.file, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(1 << 16, remaining))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        return
                    remaining -= len(chunk)

        def do_GET(self):
            self._send(app.handle("GET", self.path, dict(self.headers), b""))

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if self.path.startswith("/api/auth/") and length > MAX_AUTH_BODY:
                self._send(_json(413, {"error": "envio grande demais"}))
                return
            if length > MAX_BODY:
                self._send(_json(413, {"error": "envio grande demais (máx. 150 MB por vez)"}))
                return
            self._send(app.handle("POST", self.path, dict(self.headers), self.rfile.read(length)))

    return Handler


class StudioHTTPServer(ThreadingHTTPServer):
    # No Windows, reutilizar o endereço deixa dois servidores na mesma porta, e o antigo continua respondendo.
    allow_reuse_address = os.name != "nt"


def serve(port: int = 8765, open_browser: bool = True, public_host: str | None = None) -> None:
    app = App(port, public_host=public_host)
    try:
        httpd = StudioHTTPServer(("127.0.0.1", port), make_handler(app))
    except OSError as exc:
        raise SystemExit(f"A porta {port} já está em uso: pare o outro servidor do estúdio e tente de novo.") from exc
    url = f"http://127.0.0.1:{port}/"
    print(f"Pivoo em {url}  (Ctrl+C para sair)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def _find_cloudflared() -> str | None:
    found = shutil.which("cloudflared")
    if found:
        return found
    candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/cloudflared.exe",
                  Path(os.environ.get("ProgramFiles(x86)", "")) / "cloudflared/cloudflared.exe",
                  Path(os.environ.get("ProgramFiles", "")) / "cloudflared/cloudflared.exe"]
    return next((str(c) for c in candidates if c.is_file()), None)


def publish(port: int = 8765, timeout_s: float = 60.0) -> None:
    """Coloca o estúdio na internet por um túnel rápido da Cloudflare. O servidor continua escutando só em 127.0.0.1."""
    exe = _find_cloudflared()
    if not exe:
        raise OrchestratorError("cloudflared não encontrado: winget install Cloudflare.cloudflared")
    tunnel = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
    found = threading.Event()
    hosts: list[str] = []

    def read_log():  # continua lendo até o fim, senão o túnel trava com o buffer cheio
        for line in tunnel.stderr:
            m = re.search(r"https://([a-z0-9-]+\.trycloudflare\.com)", line)
            if m and not hosts:
                hosts.append(m.group(1))
                found.set()

    threading.Thread(target=read_log, daemon=True).start()
    try:
        if not found.wait(timeout_s):
            raise OrchestratorError("o túnel não informou o endereço público a tempo")
        print(f"Endereço público: https://{hosts[0]}  (muda a cada vez que este comando reinicia)", flush=True)
        print("Cadastro fechado: crie contas com  studio admin create-user --email ... --name ...", flush=True)
        serve(port, open_browser=False, public_host=hosts[0])
    finally:
        tunnel.terminate()
