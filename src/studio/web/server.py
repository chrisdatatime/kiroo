"""Servidor da interface (stdlib) com contas e workspaces (Fase B).

Proteções:
- Host permitido (contra DNS rebinding); escuta em 127.0.0.1 por padrão.
- Sessão por cookie HttpOnly + SameSite=Lax; toda ação POST exige o token CSRF da sessão (cabeçalho).
- Cadastro/login exigem cabeçalho próprio do cliente (força preflight em outro site) e têm limite de tentativas.
- Cada produção, mídia, gasto e teto pertence a um workspace; acesso fora dele responde 404.
- Contas novas ficam em DEMO até o administrador liberar o modo real (custos saem da conta Google do operador).
"""

from __future__ import annotations

import base64
import dataclasses
import gzip
import hashlib
import hmac
import json
import secrets
import signal
import sys
import urllib.error
import urllib.request
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
import webbrowser
import zlib
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from .. import agent_config, creative_options, fal_contract, mailer, paid_gate, payments
from ..agent_chat import AgentChat
from ..accounts import (LOGIN_WINDOW_MIN, RESET_MINUTES, TERMS_VERSION, VERIFY_MINUTES, Accounts, AuthError, GoogleAuthError,
                        verify_password)
from ..config import load_settings
from ..credits import InsufficientCredits as InsufficientCreditsError, Ledger
from ..db import Database, checkpoint
from ..factory import build
from ..logs import REQUEST_INFO, redact
from ..models import ProductInput
from ..budget import AdjustmentNeedsAuthorization
from ..orchestrator import OrchestratorError
from ..profiles import KINDS, available_versions, load_profile
from ..profiles import snapshot as snapshot_profiles
from ..providers.simulated import SimulationScript
from ..ratelimit import RateLimitConfig, RateLimiter, classify as rate_bucket
from ..shutdown import HTTP_CLOSE_S, Inflight, SignalController, minimum_platform_s, settle
from ..runtime import backup_blocks_ready, backup_start_error, backup_warning, InstanceLockError, ServerConfig, acquire_instance_lock, client_ip, release_instance_lock
from .. import turnstile
from ..spend import spend_report
from ..states import TERMINAL, ProductionStatus as PS
from ..storage import ProductionStorage, StorageError
from .uploads import UploadError, build_product, parse_creative, save_uploads
from .view import snapshot

log = logging.getLogger("studio")
STATIC = Path(__file__).parent / "static"
PID_RE = re.compile(r"^prod_[0-9a-f]{10}$")
MEDIA_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".txt", ".md", ".json"}
LEGAL_PAGES = {"/termos": "termos.html", "/privacidade": "privacidade.html"}
ACTIONS = {"run", "approve", "reject", "final", "pause", "resume", "cancel", "budget", "references", "validate",
           "direction", "go_ahead", "autonomy", "edit", "music", "retry", "confirm", "choose", "anchor"}
GAME_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"   # build do jogo (npm run build)
# Arquivos da raiz do dist (vêm de frontend/public; ver frontend/scripts/brand-assets.mjs). Lista fechada, nada de listar pasta.
BRAND_FILES = {"favicon.ico": "image/x-icon", "favicon.svg": "image/svg+xml", "apple-touch-icon.png": "image/png",
               "icon-192.png": "image/png", "icon-512.png": "image/png", "icon-maskable-512.png": "image/png",
               "og-image.png": "image/png", "manifest.webmanifest": "application/manifest+json"}
MAX_BODY = 150 * 1024 * 1024  # uploads em base64
MAX_AUTH_BODY = 64 * 1024  # rotas sem sessão não recebem envio grande
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"}
# CSP do app (React + Phaser, tudo servido pela própria origem). Phaser decodifica texturas/áudio de blob:/data:.
# Sem 'unsafe-eval' e sem scripts inline. O painel legado (/painel) tem um <script> inline e usa CSP própria.
CHALLENGES = "https://challenges.cloudflare.com"   # Turnstile (captcha): este é o ÚNICO lugar que o libera na CSP


def _csp(script: str) -> str:
    return (f"default-src 'self'; script-src {script} {CHALLENGES}; frame-src {CHALLENGES}; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "media-src 'self' blob:; font-src 'self' data:; connect-src 'self' data: blob:; worker-src 'self' blob:; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


CSP_APP = _csp("'self'")
CSP_PANEL = _csp("'self' 'unsafe-inline'")
HSTS = "max-age=31536000"
HASHED_ASSET = re.compile(r".+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$")   # nome com hash do Vite: index-BO_rcp--.js
COMPRESSIBLE = {"text/html", "text/css", "text/javascript", "application/javascript", "application/json", "image/svg+xml",
                "application/manifest+json", "text/plain"}
GZIP_MIN, GZIP_MAX = 512, 8 * 1024 * 1024
_gzip_cache: dict = {}
_gzip_lock = threading.Lock()


def security_headers(secure: bool, panel: bool = False) -> dict:
    h = {**SECURITY_HEADERS, "Content-Security-Policy": CSP_PANEL if panel else CSP_APP}
    if secure:
        h["Strict-Transport-Security"] = HSTS   # só quando o site é servido por HTTPS (STUDIO_SECURE_COOKIE=1)
    return h


def _gzipped(key, produce) -> bytes:
    """Compressão com cache em memória (arquivos com hash não mudam; a chave inclui tamanho e mtime)."""
    with _gzip_lock:
        hit = _gzip_cache.get(key)
    if hit is not None:
        return hit
    data = gzip.compress(produce(), compresslevel=6, mtime=0)
    with _gzip_lock:
        if len(_gzip_cache) >= 128:
            _gzip_cache.pop(next(iter(_gzip_cache)))
        _gzip_cache[key] = data
    return data
FORM_DEFAULTS = {"name": "x", "variant": "x", "affiliate_link": "https://shopee.com.br/x"}
COOKIE = "studio_session"
CLIENT_HEADER = "X-Studio-Client"   # obrigatório em cadastro/login (não é enviável por formulário de outro site)
OAUTH_COOKIE = "studio_oauth"       # estado do login com Google (anti-CSRF do OAuth), vive 10 min
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


GOOGLE_FLOW_S = 600                 # um login com Google precisa terminar em 10 min
GOOGLE_FLOW_MAX = 5000              # teto de logins em andamento na memória (o mais antigo sai)


class GoogleFlows:
    """Logins com Google em andamento, na memória do processo (há uma instância só; reiniciar só obriga a clicar de novo).

    A chave é o SHA-256 do `state` (que vai também num cookie HttpOnly do navegador que começou). Cada entrada guarda o
    `code_verifier` do PKCE e, no cadastro, o convite e o aceite dos Termos. `take` remove: o state vale uma vez só."""

    def __init__(self, ttl_s: int = GOOGLE_FLOW_S, cap: int = GOOGLE_FLOW_MAX, clock=time.monotonic):
        self.ttl, self.cap, self.clock = ttl_s, cap, clock
        self._d: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(state: str) -> str:
        return hashlib.sha256(state.encode()).hexdigest()

    def put(self, state: str, data: dict) -> None:
        t = self.clock()
        with self._lock:
            for k in [k for k, (exp, _) in self._d.items() if exp <= t]:
                del self._d[k]
            while len(self._d) >= self.cap:
                self._d.pop(next(iter(self._d)))
            self._d[self._key(state)] = (t + self.ttl, data)

    def take(self, state: str) -> dict | None:
        with self._lock:
            hit = self._d.pop(self._key(state), None)
        if not hit or hit[0] <= self.clock():
            return None
        return hit[1]

    def __len__(self) -> int:
        return len(self._d)


def _pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge S256), RFC 7636."""
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _google_http(url: str, data: dict | None = None, headers: dict | None = None) -> dict:
    """POST (form) quando há data, senão GET. Respostas do Google são JSON."""
    body = urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 (URLs fixas do Google)
        return json.loads(r.read().decode("utf-8"))


@dataclass
class Response:
    status: int
    content_type: str = "application/json; charset=utf-8"
    body: bytes = b""
    file: Path | None = None
    headers: dict = field(default_factory=dict)
    compress: bool = False   # estático de texto: o handler comprime em gzip se o navegador aceitar


def _json(status: int, data, headers: dict | None = None) -> Response:
    return Response(status, body=json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"), headers=headers or {})


def _no_balance_for_adjustment(cost_cc: int, balance_cc: int) -> Response:
    """402 com a conta à vista quando falta saldo para um ajuste extra. Nada foi cobrado nem mudou: o vídeo, as cenas e
    as aprovações continuam como estão e a entrega não depende deste ajuste."""
    from ..credits import fmt
    missing = max(cost_cc - balance_cc, 0)
    return _json(402, {"error": "Saldo insuficiente para um novo ajuste", "insufficient_credits": True,
                       "kind": "adjustment", "balance_cc": balance_cc, "balance": fmt(balance_cc), "cost_cc": cost_cc,
                       "cost": fmt(cost_cc), "missing_cc": missing, "missing": fmt(missing),
                       "keep_label": "Manter meu vídeo como está", "add_label": "Adicionar créditos",
                       "topup": payments.topup_options(missing)})


def _cookie(headers: dict, name: str = COOKIE) -> str | None:
    raw = headers.get("Cookie") or headers.get("cookie") or ""
    for part in raw.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name and v:
            return v
    return None


SEND_FAILED_MSG = ("Não foi possível enviar o e-mail agora. Seu código foi gerado: peça ao administrador para "
                   "confirmar seu e-mail ou tente reenviar daqui a pouco.")

CAPTCHA_PATHS = ("/api/auth/signup", "/api/auth/login", "/api/auth/forgot", "/api/auth/resend")
CAPTCHA_BAD_MSG = "Não foi possível confirmar a verificação de segurança. Tente de novo."
CAPTCHA_DOWN_MSG = "A verificação de segurança está indisponível agora. Tente de novo em instantes."


class App:
    def __init__(self, port: int = 8765, *, settings_loader=load_settings, sim_pacing: bool = True,
                 allowed_hosts: set[str] | None = None, secure_cookie: bool | None = None,
                 public_host: str | None = None, signup: str | None = None, trust_proxy: str | None = None,
                 config: ServerConfig | None = None, rate_limits: RateLimitConfig | None = None):
        cfg = config or ServerConfig.from_env()
        self.cfg = cfg
        self.port = port
        self.load_settings = settings_loader
        self.sim_pacing = sim_pacing
        self.allowed_hosts = {h.lower() for h in (allowed_hosts or ({f"127.0.0.1:{port}", f"localhost:{port}"} | set(cfg.allowed_hosts)))}
        # Endereço público (ex.: app.kiroo.app): o cookie dele vira Secure e os links de e-mail usam https.
        self.public_host = (public_host or cfg.public_host or "").lower() or None
        if self.public_host:
            self.allowed_hosts = self.allowed_hosts | {self.public_host}
        self.secure_cookie = secure_cookie if secure_cookie is not None else cfg.secure_cookie
        self.signup = signup or cfg.signup           # closed | invite | open (padrão closed; não depende do host)
        if self.signup not in ("closed", "invite", "open"):
            raise ValueError("signup deve ser closed, invite ou open")
        self.trust_proxy = trust_proxy or cfg.trust_proxy   # none | cloudflare | forwarded
        self.stopping = threading.Event()   # SIGTERM: sem jobs novos; os laços de produção param entre etapas
        self.runs: dict[str, threading.Thread] = {}
        self.inflight = Inflight()          # requisições HTTP em andamento (a drenagem espera a última terminar)
        self.errors: dict[str, str] = {}
        self.lock = threading.Lock()
        self.chat = AgentChat()  # conversa com os agentes (Fase 6); testes trocam o caller por um mock
        self.limiter = RateLimiter(rate_limits)   # memória do processo: vale porque há uma instância só
        # Login com Google: só aparece com as duas variáveis definidas. Testes trocam google_http por um mock.
        try:  # carrega o .env antes de ler as variáveis do Google e do SMTP
            self.load_settings()
        except Exception:  # noqa: BLE001
            pass
        self.google_client_id = os.environ.get("STUDIO_GOOGLE_CLIENT_ID") or None
        self.google_client_secret = os.environ.get("STUDIO_GOOGLE_CLIENT_SECRET") or None
        self.google_http = _google_http
        # Turnstile: liga só com as duas chaves. Testes trocam turnstile_url (servidor falso em 127.0.0.1).
        self.turnstile_site, self.turnstile_secret = turnstile.keys()
        self.turnstile_on = bool(self.turnstile_site and self.turnstile_secret)
        self.turnstile_broken = turnstile.fail_closed()
        self.turnstile_url = turnstile.SITEVERIFY_URL
        self.google_flows = GoogleFlows()
        # endereços fixos do Google; só os testes trocam (servidor falso em 127.0.0.1). Não vêm do ambiente.
        self.google_auth_url, self.google_token_url, self.google_userinfo_url = GOOGLE_AUTH, GOOGLE_TOKEN, GOOGLE_USERINFO
        self.send_mail = mailer.send

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
        cap = paid_gate.effective_cap(ws["monthly_cap_usd"])   # o menor entre o teto da conta e o da plataforma
        real = (ws["mode"] == "real" and bool(ws["allow_real"]) and bool(s.gemini_api_key or s.fal_api_key)
                and cap > 0)   # teto 0 = DEMO
        return dataclasses.replace(s, mode="real" if real else "simulated", allow_paid_calls=real,
                                   monthly_cap_usd=cap,
                                   assets_dir=s.assets_dir if owner_admin else assets,
                                   reference_dir=s.reference_dir if owner_admin else None)

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
            from ..providers.simulated_fal import FalSimScript
            return build(s, sim_script=pacing, sleep=time.sleep if self.sim_pacing else (lambda _: None),
                         sim_fal_script=FalSimScript(polls_before_done=2 if self.sim_pacing else 0))
        if s.mode != "real" or not s.allow_paid_calls:
            raise OrchestratorError("Modo DEMO ligado neste estúdio: produções reais ficam paradas até desligar o DEMO.")
        return build(s)

    def is_running(self, pid: str) -> bool:
        t = self.runs.get(pid)
        return bool(t and t.is_alive())

    def start_run(self, pid: str, *, resume_attempts: int | None = None) -> bool:
        with self.lock:
            if self.stopping.is_set() or self.is_running(pid):
                return False
            self.errors.pop(pid, None)
            self._mark_run(pid, "running", resume_attempts=resume_attempts,
                           note="retomada automática após reinício" if resume_attempts else "")
            t = threading.Thread(target=self._run, args=(pid,), daemon=True, name=f"run-{pid}")
            self.runs[pid] = t
            t.start()
            return True

    def _mark_run(self, pid: str, state: str, *, resume_attempts: int | None = None, reset_attempts: bool = False,
                  note: str = "") -> None:
        """Registra no banco o estado do processo da produção (para retomar após reinício). Nunca derruba quem chama."""
        try:
            db = Database(self.settings().db_path)
            try:
                db.set_run_state(pid, state, resume_attempts=resume_attempts, reset_attempts=reset_attempts)
                if state in ("interrupted", "abandoned") or (state == "running" and resume_attempts):
                    db.add_event(pid, {"interrupted": "interrupted", "abandoned": "resume_abandoned", "running": "resumed"}[state],
                                 note)
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("não foi possível registrar o estado de execução (%s)", type(exc).__name__, extra={"pid": pid})

    def _run(self, pid: str) -> None:
        orch = None
        interrupted = False
        try:
            orch = self.orch_for(pid)
            orch.stop_event = self.stopping
            orch.run(pid)
            interrupted = orch.stopped
        except Exception as exc:  # noqa: BLE001 — mostrado na interface
            self.errors[pid] = redact(f"{type(exc).__name__}: {exc}")[:500]
        finally:
            if orch is not None:
                orch.db.close()
            if interrupted:
                self._mark_run(pid, "interrupted", note="servidor desligando: a produção será retomada na próxima subida")
            else:
                self._mark_run(pid, "idle", reset_attempts=True)

    def shutdown(self, grace_s: float | None = None) -> list[str]:
        """Para de aceitar jobs, espera até `grace_s` os laços terminarem a etapa e marca o resto como interrompido."""
        grace = self.cfg.shutdown_grace_s if grace_s is None else grace_s
        self.stopping.set()
        deadline = time.monotonic() + max(grace, 0)
        with self.lock:
            threads = dict(self.runs)
        for t in threads.values():
            if t.is_alive():
                t.join(max(deadline - time.monotonic(), 0))
        left = [pid for pid, t in threads.items() if t.is_alive()]
        for pid in left:   # ainda no meio de uma chamada: o estado salvo permite retomar sem refazer o que já foi pago
            self._mark_run(pid, "interrupted", note="desligamento: a etapa em andamento será retomada na próxima subida")
        if left:
            log.warning("desligamento: %d produção(ões) ainda em andamento marcadas como interrompidas", len(left))
        return left

    def resume_pending(self) -> list[str]:
        """Ao subir: retoma produções `running` (o processo morreu) ou `interrupted` (desligamento), até o limite de tentativas.
        A retomada reabre o laço do orquestrador: tentativas e operações remotas salvas são reaproveitadas (nada pago é
        refeito) e reservas órfãs de créditos seguem sendo liberadas pelo livro-razão em 15 min."""
        started: list[str] = []
        s, db, _ = self._db()
        try:
            rows = db.run_states("running", "interrupted")
            for r in rows:
                pid = r["production_id"]
                try:
                    status = PS(db.production(pid)["status"])
                except KeyError:
                    db.set_run_state(pid, "idle")
                    continue
                if self.is_running(pid):
                    continue
                if status in TERMINAL or status in {PS.PAUSED, PS.AWAITING_FINAL_REVIEW}:
                    db.set_run_state(pid, "idle", reset_attempts=True)
                    continue
                if r["resume_attempts"] >= self.cfg.resume_max_attempts:
                    db.set_run_state(pid, "abandoned")
                    db.add_event(pid, "resume_abandoned", f"{r['resume_attempts']} tentativas de retomada automática sem sucesso")
                    db.set_production_status(pid, PS.PAUSED, "retomada automática esgotada: retome manualmente")
                    continue
                if self.start_run(pid, resume_attempts=r["resume_attempts"] + 1):
                    started.append(pid)
        finally:
            db.close()
        return started

    def bootstrap_admin(self) -> str | None:
        """Cria o administrador de STUDIO_BOOTSTRAP_ADMIN_EMAIL se ainda não existir. Sem senha: manda o link de definir senha."""
        email = self.cfg.bootstrap_admin_email
        if not email:
            return None
        s, db, acc = self._db()
        try:
            if acc.user_by_email(email):
                return "exists"
            uid, wid = acc.create_user(email, None, "", admin=True, verified=True, no_password=True)
            acc.assign_orphans(wid)
            acc.set_workspace(wid, allow_real=1, credits_exempt=1)
            token = acc.start_reset(email)
        finally:
            db.close()
        sent = self.send_mail(email, *mailer.admin_setup_email(f"{self.base_url()}/?reset={token}", RESET_MINUTES))
        if not sent:
            log.warning("administrador criado por STUDIO_BOOTSTRAP_ADMIN_EMAIL, mas o link de senha não foi enviado "
                        "(SMTP ausente). Gere um com: studio admin reset-link --email <e-mail>")
        return "created"

    def base_url(self) -> str:
        return f"https://{self.public_host}" if self.public_host else f"http://127.0.0.1:{self.port}"

    def _is_public(self, headers: dict) -> bool:
        return bool(self.public_host) and headers.get("Host", "").lower() == self.public_host

    def _client_ip(self, headers: dict, peer: str = "") -> str:
        """IP real do cliente. Cabeçalhos de proxy só são lidos quando STUDIO_TRUST_PROXY os declara confiáveis."""
        h = {k.title(): v for k, v in headers.items()}
        return client_ip(h, self.trust_proxy, peer or h.get("_Peer", ""))

    def _set_cookie(self, token: str, max_age: int, *, secure: bool = False) -> dict:
        flags = f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"
        if self.secure_cookie or secure:
            flags += "; Secure"
        return {"Set-Cookie": flags}

    def _origin(self, headers: dict) -> str:
        """Endereço de quem chamou (links em e-mails sem host público). Host já foi conferido na lista."""
        scheme = "https" if (self._is_public(headers) or self.secure_cookie) else "http"
        return f"{scheme}://{headers.get('Host', '')}"

    def google_redirect_uri(self) -> str:
        """URI de retorno do Google, FIXA: https://$STUDIO_PUBLIC_HOST/api/auth/google/callback (sem host público,
        o endereço local). Nunca vem do cabeçalho Host. É exatamente esta que se cadastra no Google Cloud."""
        return self.base_url() + "/api/auth/google/callback"

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    def _send_verification(self, acc: Accounts, uid: str, email: str) -> bool:
        code = acc.start_verification(uid)
        return self.send_mail(email, *mailer.verification_email(code, VERIFY_MINUTES))

    # --- login com Google (OAuth 2.0, código no servidor; o segredo nunca vai ao navegador)
    def _google(self, path: str, url, headers: dict) -> Response:
        """start: cria state (uso único, guardado no servidor e num cookie) + PKCE e manda para o Google.
        callback: confere o state contra o cookie, troca o código (com o code_verifier) e entra/cria conta.
        Nada de código, token ou segredo vai para log, erro ou resposta: os erros voltam como /?entrar&erro=<código>."""
        secure = bool(self.public_host) or self.secure_cookie
        cookie_tail = "; Path=/api/auth/google; HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")
        clear_state = f"{OAUTH_COOKIE}={cookie_tail}; Max-Age=0"

        def back(err: str | None = None, cookies: list | None = None) -> Response:
            loc = "/" if not err else "/?" + urlencode({"entrar": "", "erro": err})
            return Response(302, "text/plain", b"", headers={"Location": loc, "Set-Cookie": [clear_state, *(cookies or [])],
                                                             "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

        if not self.google_enabled:
            return back("google_off")
        q = parse_qs(url.query)
        if path == "/api/auth/google/start":
            if self.public_host and headers.get("Host", "").lower() != self.public_host:
                # o cookie do state precisa nascer no mesmo host que recebe o retorno do Google
                return Response(302, "text/plain", b"", headers={
                    "Location": f"https://{self.public_host}/api/auth/google/start" + (f"?{url.query}" if url.query else "")})
            intent = q.get("intent", ["login"])[0]
            flow = {"verifier": None, "invite": None, "terms": None}
            if intent == "signup":
                if self.signup == "closed":
                    return back("convite")
                if q.get("consent", [""])[0] != "1":
                    return back("google_consent")
                flow["terms"] = TERMS_VERSION
                if self.signup == "invite":
                    invite = re.sub(r"[^A-Za-z0-9-]", "", q.get("invite", [""])[0])[:64]
                    if not invite:
                        return back("convite")
                    flow["invite"] = invite
            state = secrets.token_urlsafe(32)
            verifier, challenge = _pkce_pair()
            flow["verifier"] = verifier
            self.google_flows.put(state, flow)
            gq = urlencode({"client_id": self.google_client_id, "redirect_uri": self.google_redirect_uri(),
                            "response_type": "code", "scope": "openid email profile", "state": state,
                            "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"})
            return Response(302, "text/plain", b"", headers={"Location": f"{self.google_auth_url}?{gq}", "Cache-Control": "no-store",
                                                             "Set-Cookie": f"{OAUTH_COOKIE}={state}{cookie_tail}; Max-Age={GOOGLE_FLOW_S}"})
        if path != "/api/auth/google/callback":
            return _json(404, {"error": "não encontrado"})
        state, code = q.get("state", [""])[0], q.get("code", [""])[0]
        expected = _cookie(headers, OAUTH_COOKIE) or ""
        if not expected or not state or not hmac.compare_digest(state.encode(), expected.encode()):
            return back("google_state")   # state de outro navegador não consome o login de quem começou
        flow = self.google_flows.take(state)   # consumido aqui, mesmo se algo abaixo falhar: vale uma vez só
        if q.get("error"):
            return back("google_cancel")
        if not flow or not code:
            return back("google_state")
        try:
            tok = self.google_http(self.google_token_url, {"code": code, "client_id": self.google_client_id,
                                                  "client_secret": self.google_client_secret,
                                                  "redirect_uri": self.google_redirect_uri(),
                                                  "grant_type": "authorization_code", "code_verifier": flow["verifier"]})
            info = self.google_http(self.google_userinfo_url, None, {"Authorization": f"Bearer {tok['access_token']}"})
        except (urllib.error.URLError, OSError, KeyError, TypeError, ValueError) as exc:
            log.warning("Login com Google falhou (%s)", type(exc).__name__)   # a mensagem pode ecoar o código/segredo
            return back("google_failed")
        if not isinstance(info, dict) or not info.get("sub") or not info.get("email"):
            return back("google_failed")
        key = f"s:{self._client_ip(headers)}"
        s, db, acc = self._db()
        try:
            if flow["invite"] and acc.throttled(key):
                return back("google_throttled")
            try:
                uid, _created = acc.google_user(str(info["sub"]), str(info["email"]), str(info.get("name") or ""),
                                               info.get("email_verified") is True, signup=self.signup,
                                               invite=flow["invite"], terms_version=flow["terms"])
            except GoogleAuthError as exc:
                if exc.code == "convite_invalido":
                    acc.record_fail(key)
                return back(exc.code)
            except AuthError:
                return back("google_failed")
            wid = acc.workspaces_of(uid)[0]["id"]
            token, _ = acc.create_session(uid, wid)
        finally:
            db.close()
        return back(None, [self._set_cookie(token, 30 * 86400, secure=secure)["Set-Cookie"]])

    # ----------------------------------------------------------------- rotas
    def health(self, path: str) -> Response:
        """/healthz: o processo está vivo (não toca no banco). /readyz: abre o SQLite e confere escrita em STUDIO_DATA_DIR.
        Sem autenticação e sem dado sensível: só ok/falha por verificação."""
        if path == "/healthz":
            return _json(200, {"status": "ok"})
        checks = {"db": False, "data_dir": False, "accepting": not self.stopping.is_set()}
        try:
            s = self.settings()
            probe = s.data_dir / f".readyz-{os.getpid()}-{threading.get_ident()}"
            s.data_dir.mkdir(parents=True, exist_ok=True)
            probe.write_bytes(b"ok")
            probe.unlink()
            checks["data_dir"] = True
            db = Database(s.db_path)
            try:
                db.conn.execute("BEGIN IMMEDIATE")   # exige poder escrever no banco
                db.conn.execute("ROLLBACK")
                db.conn.execute("SELECT 1").fetchone()
                checks["db"] = True
            finally:
                db.close()
        except Exception:  # noqa: BLE001 — o detalhe vai para o log, não para quem consulta
            log.error("readyz falhou", exc_info=True)
        ok = all(checks.values())
        try:
            if backup_blocks_ready():      # production sem backup e com STUDIO_ALLOW_NO_BACKUP=1
                ok = False
        except ValueError:
            ok = False
        body = {"status": "ready" if ok else "unavailable", "checks": checks}
        try:
            warn = backup_warning()
        except ValueError:
            warn = "STUDIO_ENV inválido"
        if warn:   # aviso alto, sem derrubar o serviço: o servidor serve, mas os dados estão sem cópia
            body["warnings"] = ["backup_not_configured"]
        return _json(200 if ok else 503, body)

    def handle(self, method: str, raw_path: str, headers: dict, body: bytes, peer: str = "") -> Response:
        headers = {k.title(): v for k, v in headers.items() if k.title() != "_Peer"}   # chaves canônicas; _Peer não vem do cliente
        if peer:
            headers["_Peer"] = peer
        url = urlparse(raw_path)
        path = url.path
        if method == "GET" and path in ("/healthz", "/readyz"):   # antes da lista de hosts: sondas de contêiner/balanceador
            return self.health(path)
        if headers.get("Host", "").lower() not in self.allowed_hosts:
            return _json(403, {"error": "host não permitido"})
        if path.startswith("/api/"):   # limite por IP antes de abrir o banco
            ip = self._client_ip(headers)
            limited = self._limited("api_ip", ip)
            if not limited and path.startswith("/api/auth/") and (method == "POST" or path.startswith("/api/auth/google/")):
                limited = self._limited("auth", ip)
            if limited:
                return limited
        try:
            # --- públicas: o jogo (que mostra a tela de entrar) e seus arquivos
            if method == "GET" and path in ("/", "/index.html") and (GAME_DIST / "index.html").is_file():
                return Response(200, "text/html; charset=utf-8", (GAME_DIST / "index.html").read_bytes(),
                                headers={"Cache-Control": "no-cache"}, compress=True)
            if method == "GET" and path.startswith("/assets/"):
                f = (GAME_DIST / path.lstrip("/")).resolve()
                if GAME_DIST.resolve() not in f.parents or not f.is_file():
                    return _json(404, {"error": "não encontrado"})
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                ctype = "text/javascript; charset=utf-8" if f.suffix == ".js" else ctype
                cache = "public, max-age=31536000, immutable" if HASHED_ASSET.match(f.name) else "no-cache"
                return Response(200, ctype, file=f, headers={"Cache-Control": cache},
                                compress=ctype.split(";")[0] in COMPRESSIBLE)
            if method == "GET" and path.lstrip("/") in BRAND_FILES and (GAME_DIST / path.lstrip("/")).is_file():
                f = GAME_DIST / path.lstrip("/")  # ícones, manifest e og-image da marca (frontend/public, gerados por script)
                return Response(200, BRAND_FILES[f.name], file=f, headers={"Cache-Control": "public, max-age=86400"},
                                compress=BRAND_FILES[f.name].split(";")[0] in COMPRESSIBLE)
            if method == "POST" and path.startswith("/api/auth/"):
                return self._auth(path, headers, json.loads(body or b"{}"))
            if method == "GET" and path in ("/api/config", "/api/auth/config"):  # o que a tela de acesso pode oferecer
                return _json(200, {"signup": self.signup, "google": self.google_enabled,
                                   "turnstile": self.turnstile_site if self.turnstile_on and not self.turnstile_broken else None,
                                   "email": mailer.configured(),
                                   "terms_version": TERMS_VERSION})
            if method == "GET" and path in LEGAL_PAGES:   # rascunhos públicos (PARA REVISÃO JURÍDICA)
                return Response(200, "text/html; charset=utf-8", (STATIC / LEGAL_PAGES[path]).read_bytes(),
                                headers={"Cache-Control": "no-cache"}, compress=True)
            if method == "GET" and path.startswith("/api/auth/google/"):
                return self._google(path, url, headers)

            # --- daqui em diante: só com sessão
            token = _cookie(headers)
            s, db, acc = self._db()
            try:
                sess = acc.session(token)
                ws = acc.workspace(sess["workspace_id"]) if sess else None
                workspaces = acc.workspaces_of(sess["user_id"]) if sess else []
            finally:
                db.close()
            info = REQUEST_INFO.get()
            if info is not None and ws is not None:
                info["workspace_id"] = ws["id"]
            from . import admin_api
            if admin_api.is_admin_path(path) and not (sess and sess["is_platform_admin"]):
                return admin_api.not_found()   # aba Administrador: para quem não é admin (ou não entrou), não existe
            if not sess:
                if method == "GET" and path in ("/painel", "/painel/", "/"):
                    return Response(302, "text/plain", b"", headers={"Location": "/"}) if path != "/" else _json(401, {"error": "entre na sua conta"})
                return _json(401, {"error": "entre na sua conta"})
            payload = None
            if path.startswith("/api/"):   # limite por usuário: geral e, nas rotas caras, o específico
                payload = json.loads(body or b"{}") if method == "POST" else None
                has_file = isinstance(payload, dict) and bool(payload.get("file"))
                limited = self._limited("api_user", sess["user_id"])
                bucket = rate_bucket(method, path, has_file)
                if not limited and bucket:
                    limited = self._limited(bucket, sess["user_id"])
                if limited:
                    return limited
            ctx = {"sess": sess, "ws": ws, "wid": ws["id"], "admin": bool(sess["is_platform_admin"]),
                   "s": self.ws_settings(s, ws), "workspaces": workspaces}

            if admin_api.is_admin_path(path):   # CSRF + Origin, reautenticação e no-store ficam em admin_api
                return admin_api.handle(self, method, path, url, headers, payload, ctx, token)
            if method == "GET":
                return self._get(path, url, ctx)
            if method == "POST":
                if headers.get("X-Studio-Token") != sess["csrf"]:
                    return _json(403, {"error": "token ausente ou inválido"})
                return self._post(path, payload if payload is not None else json.loads(body or b"{}"), ctx, token)
            return _json(405, {"error": "método não permitido"})
        except AuthError as exc:
            return _json(400, {"error": redact(exc)})
        except (OrchestratorError, ValueError, KeyError, StorageError, UploadError) as exc:
            return _json(400, {"error": redact(exc)})  # TrainingError e MusicError são ValueError

    def _limited(self, bucket: str, key: str) -> Response | None:
        wait = self.limiter.hit(bucket, key)
        if wait is None:
            return None
        return _json(429, {"error": f"Muitas requisições em pouco tempo. Tente de novo em {wait} s.", "retry_after": wait},
                     {"Retry-After": str(wait)})

    # --- autenticação
    def _captcha(self, p: dict, ip: str) -> Response | None:
        """Turnstile nas rotas públicas. None = pode seguir. Código estável, sem detalhes; token e segredo nunca vão a log."""
        if self.turnstile_broken:   # staging/produção com meia configuração: falha fechada
            return _json(503, {"error": CAPTCHA_DOWN_MSG, "code": "captcha_indisponivel"})
        if not self.turnstile_on:
            return None
        res = turnstile.verify(self.turnstile_secret, p.get("captcha"), ip, url=self.turnstile_url)
        if res == turnstile.OK:
            return None
        if res == turnstile.UNAVAILABLE:
            return _json(503, {"error": CAPTCHA_DOWN_MSG, "code": "captcha_indisponivel"})
        return _json(400, {"error": CAPTCHA_BAD_MSG, "code": "captcha_invalido"})

    def _auth(self, path: str, headers: dict, p: dict) -> Response:
        if headers.get(CLIENT_HEADER) != "game":
            return _json(403, {"error": "cliente não permitido"})
        ip = self._client_ip(headers)
        secure = self._is_public(headers)
        if path in CAPTCHA_PATHS and (blocked := self._captcha(p, ip)):   # antes do banco: sem usuário, convite ou sessão
            return blocked
        s, db, acc = self._db()
        try:
            if path == "/api/auth/signup":
                if self.signup == "closed":   # independe do host público: fechado é fechado
                    return _json(403, {"error": "Cadastro só por convite: peça sua conta ao administrador."})
                if p.get("consent") is not True:   # consentimento explícito, registrado com a versão dos textos
                    return _json(400, {"error": "Para criar a conta, aceite os Termos de Uso e a Política de Privacidade."})
                invite_id = None
                if self.signup == "invite":
                    key = f"s:{ip}"
                    if acc.throttled(key):
                        return _json(429, {"error": f"muitas tentativas; espere {LOGIN_WINDOW_MIN} minutos"},
                                     {"Retry-After": str(LOGIN_WINDOW_MIN * 60)})
                    # código de uso único gerado por `studio admin create-invite` (só o hash fica no banco)
                    invite_id = acc.claim_invite(str(p.get("invite") or ""), str(p.get("email") or ""))
                    if not invite_id:
                        acc.record_fail(key)
                        return _json(403, {"error": "código de convite inválido, já usado ou expirado"})
                try:
                    uid, wid = acc.create_user(p.get("email", ""), p.get("password", ""), p.get("name", ""), admin=False,
                                               workspace_name=p.get("workspace") or None, terms_version=TERMS_VERSION)
                except Exception:
                    if invite_id:
                        acc.finish_invite(invite_id, None)   # cadastro falhou (e-mail repetido, senha curta): devolve o convite
                    raise
                if invite_id:
                    acc.finish_invite(invite_id, uid)
                token, info = acc.create_session(uid, wid)
                # a conta já entra (modo DEMO); o código de confirmação vai para o e-mail
                sent = self._send_verification(acc, uid, acc.user(uid)["email"])
                return _json(200, {"ok": True, "admin": False, "verify": True, "sent": sent,
                                   **({} if sent else {"message": SEND_FAILED_MSG})},
                             self._set_cookie(token, 30 * 86400, secure=secure))
            if path == "/api/auth/login":
                token, info = acc.login(p.get("email", ""), p.get("password", ""), ip)
                return _json(200, {"ok": True}, self._set_cookie(token, 30 * 86400, secure=secure))
            if path == "/api/auth/logout":
                acc.logout(_cookie(headers))
                return _json(200, {"ok": True}, self._set_cookie("", 0, secure=secure))
            if path == "/api/auth/forgot":
                tok = acc.start_reset(p.get("email", ""))
                if tok:  # sem SMTP: em desenvolvimento o link vai para o log; em staging/produção não vai a lugar nenhum
                    base = self.base_url() if self.public_host else self._origin(headers)
                    self.send_mail(acc.user_by_email(p.get("email", ""))["email"],
                                   *mailer.reset_email(f"{base}/?reset={tok}", RESET_MINUTES))
                if mailer.configured():
                    return _json(200, {"ok": True, "sent": True, "message": "Se houver uma conta com este e-mail, enviamos um link "
                                                                             "para criar uma nova senha. Ele vale por 30 minutos."})
                return _json(200, {"ok": True, "sent": False, "message": "Se houver uma conta com este e-mail, o link foi gerado. "
                                                                          "O envio por e-mail ainda não está ativo: peça o link ao administrador."})
            if path in ("/api/auth/verify", "/api/auth/resend"):  # confirmação de e-mail: exige a sessão recém-criada
                sess = acc.session(_cookie(headers))
                if not sess:
                    return _json(401, {"error": "entre na sua conta"})
                if path == "/api/auth/resend":
                    sent = self._send_verification(acc, sess["user_id"], sess["email"])
                    return _json(200, {"ok": True, "sent": sent, **({} if sent else {"message": SEND_FAILED_MSG})})
                acc.verify_email(sess["user_id"], str(p.get("code", "")))
                return _json(200, {"ok": True})
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
                if path == "/api/credits":  # extrato e consumo por produção/cena/operação (Fase C)
                    return _json(200, {**credits, "statement": led.statement(ws["id"]), "usage": led.usage(ws["id"]),
                                       "topup": payments.topup_options()})
            finally:
                db.close()
            return _json(200, {"csrf": ctx["sess"]["csrf"], "admin": ctx["admin"],
                               "user": {"email": ctx["sess"]["email"], "name": ctx["sess"]["name"],
                                        "email_verified": bool(ctx["sess"]["email_verified_at"]),
                                        "onboarding": {"done_at": ctx["sess"]["onboarding_done_at"],
                                                       "step": int(ctx["sess"]["onboarding_step"] or 0)}},
                               "workspace": {"id": ws["id"], "name": ws["name"], "mode": s.mode, "allow_real": bool(ws["allow_real"]),
                                             "credits": credits},
                               "workspaces": [{"id": w["id"], "name": w["name"], "role": w["role"]} for w in ctx["workspaces"]],
                               "paid_calls": {k: v for k, v in paid_gate.status().items() if k in ("blocked", "message")}})
        if path == "/api/credits/topup":   # "Adicionar créditos": hoje contato manual; ponto de integração do Mercado Pago
            try:
                missing = int(parse_qs(url.query).get("missing_cc", ["0"])[0])
            except ValueError:
                missing = 0
            return _json(200, payments.topup_options(missing))
        if path == "/api/account/export":   # LGPD: cópia dos dados da própria conta
            from ..privacy import export_account
            db = Database(s.db_path)
            try:
                data = export_account(db, self.settings().data_dir, ctx["sess"]["user_id"])
            finally:
                db.close()
            name = f"kiroo-dados-{time.strftime('%Y%m%d')}.json"
            return _json(200, data, {"Content-Disposition": f'attachment; filename="{name}"'})
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
            data["settings"]["video_engine"] = self._engine_for(ctx["ws"], s)   # a interface so mostra o fluxo fal.ai com "fal"
            data["settings"]["fal_styles"] = [{"id": k, "label": fal_contract.STYLE_LABELS[k]} for k in fal_contract.enabled_styles(s)]
            return _json(200, data)
        if path.startswith("/media/"):
            return self._media(path, ctx, url.query)
        if path == "/api/creative/options":
            q = parse_qs(url.query)
            has_bia = (s.reference_root / "bia" / "PERFIL BIA.jpg").is_file()
            return _json(200, {**creative_options.catalogue(),
                               **creative_options.ideas(q.get("name", [""])[0], q.get("category", [""])[0], has_bia)})
        if path in ("/api/chat/quota", "/api/chat/spend"):
            db = Database(s.db_path)
            try:
                if path == "/api/chat/spend":
                    if not ctx["admin"]:
                        return _json(403, {"error": "restrito ao administrador"})
                    return _json(200, {"rows": self.chat.spend(db.conn)})
                return _json(200, self.chat.quota(db.conn, ctx["sess"]["user_id"]))
            finally:
                db.close()
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
        if self.stopping.is_set() and (path.startswith("/api/productions") or path == "/api/demo"):
            return _json(503, {"error": "o servidor está reiniciando; tente de novo em instantes"}, {"Retry-After": "30"})
        if path == "/api/config":
            if not ctx["admin"]:
                return _json(403, {"error": "configuração técnica restrita ao administrador"})
            base = self.settings()
            current = {k: getattr(base, k) for k in agent_config.field_options()}
            agent_config.save(base.data_dir, settings=payload.get("settings"), agents=payload.get("agents"), current=current)
            return _json(200, {"ok": True})
        if path == "/api/runtime":
            return self._runtime(payload, ctx)
        if path == "/api/account/delete":
            return self._delete_account(payload, ctx)
        if path == "/api/onboarding":  # kit de onboarding: {step} salva onde parou; {done: true} conclui/pula
            done = payload.get("done")
            s0, db, acc = self._db()
            try:
                ob = acc.set_onboarding(ctx["sess"]["user_id"], step=payload.get("step"),
                                        done=done if isinstance(done, bool) else None)
            finally:
                db.close()
            return _json(200, {"ok": True, "onboarding": ob})
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
        if path == "/api/chat":
            return self._chat(payload, ctx)
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
            if m.group(2) == "budget" and not ctx["admin"]:
                # Orçamento operacional é freio interno do Kiroo: o cliente não sobe limite nem paga para terminar.
                return _json(403, {"error": "o limite operacional da produção é ajustado só pela equipe do Kiroo"})
            return self._action(m.group(1), m.group(2), payload, s)
        return _json(404, {"error": "não encontrado"})

    def _chat(self, payload: dict, ctx) -> Response:
        """Conversa com um agente. Só texto: nada aqui executa ação, aprova ou mexe em créditos."""
        s, wid = ctx["s"], ctx["wid"]
        db = Database(s.db_path)
        try:
            mission = None
            pid = payload.get("pid")
            # o nome da missão vem do banco (e só se a produção for deste workspace), não do navegador
            if isinstance(pid, str) and PID_RE.match(pid) and Accounts(db).owns(wid, pid):
                try:
                    mission = json.loads(db.production(pid)["product_json"]).get("name")
                except (KeyError, ValueError, TypeError):
                    mission = None
            needs = payload.get("needs")
            res = self.chat.reply(db.conn, user_id=ctx["sess"]["user_id"], workspace_id=wid, agent=str(payload.get("agent")),
                                  text=str(payload.get("text") or "")[:2000],
                                  ctx={"mission": mission, "stage": payload.get("stage"), "status": payload.get("status"),
                                       "needs": needs if isinstance(needs, list) else []})
        finally:
            db.close()
        return _json(200, res)

    def _delete_account(self, payload: dict, ctx) -> Response:
        """LGPD: apaga a própria conta. Exige a senha (ou, conta só do Google, o e-mail) e a palavra APAGAR."""
        from ..privacy import PrivacyError, delete_account
        sess = ctx["sess"]
        if str(payload.get("confirm") or "").strip().upper() != "APAGAR":
            return _json(400, {"error": "Para confirmar, digite APAGAR."})
        s0, db, acc = self._db()
        try:
            u = acc.user(sess["user_id"])
            if u["pw_hash"] != "!":
                if not verify_password(str(payload.get("password") or ""), u["pw_hash"]):
                    return _json(403, {"error": "senha incorreta"})
            elif str(payload.get("email") or "").strip().lower() != u["email"]:
                return _json(403, {"error": "digite o e-mail da conta para confirmar"})
            pids = [r["id"] for r in db.conn.execute("SELECT p.id FROM productions p JOIN workspaces w ON w.id=p.workspace_id "
                                                     "WHERE w.owner_id=?", (u["id"],))]
            if any(self.is_running(pid) for pid in pids):
                return _json(409, {"error": "há uma produção em andamento: pause ou aguarde antes de apagar a conta"})
            try:
                done = delete_account(db, s0.data_dir, u["id"])
            except PrivacyError as exc:
                return _json(403, {"error": str(exc)})
        finally:
            db.close()
        log.info("conta apagada a pedido do titular", extra={"event": "account_deleted"})
        return _json(200, {"ok": True, **done}, self._set_cookie("", 0))

    def _runtime(self, payload: dict, ctx) -> Response:
        ws, base = ctx["ws"], self.settings()
        fields = {}
        if payload.get("monthly_cap_usd") is not None:
            cap = float(payload["monthly_cap_usd"])
            if not 0 <= cap <= 10000:
                raise ValueError("teto mensal deve estar entre 0 e 10000 US$")
            if paid_gate.platform_cap() > 0:   # nunca acima do teto da plataforma
                cap = paid_gate.validate_account_cap(cap)
            fields["monthly_cap_usd"] = cap
        mode = payload.get("mode")
        if mode is not None:
            if mode == "real":
                if paid_gate.blocked_reason():
                    return _json(409, {"error": paid_gate.MESSAGES[paid_gate.blocked_reason()], "paid_calls_blocked": True})
                if not ws["allow_real"]:
                    return _json(403, {"error": "Este estúdio está em DEMO até a cobrança por créditos ser liberada."})
                if not (base.gemini_api_key or base.fal_api_key):
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
        from ..agents import fidelity
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
        advice = None
        if resolved.presentation == "hands_only" and fidelity.looks_complex(product.name, product.category,
                                                                           product.visual_attributes):
            advice = {"suggested": "product_only", "text": fidelity.FORMAT_ADVICE}
            warnings.append(fidelity.FORMAT_ADVICE)
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
            "format_advice": advice,
        }

    @staticmethod
    def _budget_for(payload: dict, s) -> float:
        """Limite da produção: o informado (API/CLI antigas) ou o padrão do servidor (STUDIO_DEFAULT_PRODUCTION_CAP_CREDITS),
        que em modo real nunca passa do teto efetivo do estúdio (menor entre conta e plataforma)."""
        raw = payload.get("budget")
        if raw not in (None, ""):
            return float(raw)
        from .. import billing
        if s.mode != "real":
            return billing.default_production_budget_usd(None)
        # Orçamento OPERACIONAL (freio interno): folga sobre o pré-orçamento, nunca acima do teto efetivo do estúdio.
        from .. import budget as budget_mod
        ops = budget_mod.ops_budget_usd(budget_mod.estimate_production(s)["usd"], billing.policy().usd(
            billing.default_production_cap_credits()))
        return min(ops, max(float(s.monthly_cap_usd or 0), 0.0))

    @staticmethod
    def _no_credits(exc) -> Response:
        """Saldo < pré-orçamento: bloqueia ANTES de começar, com a conta à vista."""
        from ..credits import fmt
        return _json(402, {"error": f"Este vídeo custa cerca de {fmt(exc.needed_cc)} créditos (com os ajustes incluídos) "
                                    f"e o saldo do estúdio é {fmt(exc.balance_cc)}. Nada foi cobrado e a produção não "
                                    "começou: adicione créditos e tente de novo.",
                           "insufficient_credits": True, "needed_cc": exc.needed_cc, "balance_cc": exc.balance_cc})

    @staticmethod
    def _engine_for(ws, s) -> str:
        """Motor das producoes NOVAS: o da conta (workspaces.video_engine) ou, sem ele, o global (STUDIO_VIDEO_ENGINE)."""
        own = ws["video_engine"] if ws is not None and "video_engine" in ws.keys() else None
        return own if own in ("gemini", "fal") else s.video_engine

    def _create_fal(self, payload: dict, ctx) -> Response:
        """Criacao do motor fal.ai: UMA foto, o estilo (Escuro/Claro) e um id do cliente (anti duplo clique)."""
        s = ctx["s"]
        style = payload.get("style") or "light"          # sem seletor por enquanto: o cliente envia sempre o Claro
        if style not in fal_contract.STYLES:
            return _json(400, {"error": "Escolha o estilo: Escuro ou Claro."})
        if style not in fal_contract.enabled_styles(s):
            return _json(400, {"error": "Este estilo ainda nao esta disponivel. Use o estilo Claro."})
        crid = str(payload.get("client_request_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", crid):
            return _json(400, {"error": "pedido sem identificador (client_request_id)"})
        files = payload.get("files") or []
        if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict)                 or not re.search(r"\.(jpe?g|png|webp)$", str(files[0].get("name", "")), re.I):
            return _json(400, {"error": "Envie exatamente uma foto do produto (JPG, PNG ou WEBP)."})
        db = Database(s.db_path)
        try:   # duplo clique: a producao ja existe, nada e recebido, reservado nem cobrado de novo
            row = db.conn.execute("SELECT id FROM productions WHERE workspace_id=? AND client_request_id=?",
                                  (ctx["wid"], crid)).fetchone()
            if row:
                return _json(200, {"ok": True, "pid": row["id"], "mode": s.mode, "duplicate": True})
        finally:
            db.close()
        if s.mode == "real" and paid_gate.blocked_reason():
            return _json(409, {"error": paid_gate.MESSAGES[paid_gate.blocked_reason()], "paid_calls_blocked": True})
        prebudget = s.mode == "real"
        if prebudget:
            from .. import budget as budget_mod
            db = Database(s.db_path)
            try:
                Ledger(db).can_reserve(ctx["wid"], budget_mod.estimate_workflow(s, style)["cc"])
            except InsufficientCreditsError as exc:
                return self._no_credits(exc)
            finally:
                db.close()
        refs = save_uploads(s.data_dir, [{"name": files[0]["name"], "data": files[0].get("data", ""), "role": "front",
                                          "source": "official_listing"}])
        product = build_product({"name": str(payload.get("name") or "").strip()}, refs)
        orch = build(s)
        try:
            from .. import billing, budget as budget_mod, fal_pipeline
            if s.mode != "real":
                budget_usd = billing.default_production_budget_usd(None)
            else:   # orcamento operacional: folga sobre o pre-orcamento, nunca acima do teto efetivo do estudio
                ops = budget_mod.ops_budget_usd(budget_mod.estimate_workflow(s, style)["usd"], billing.policy().usd(
                    billing.default_production_cap_credits()))
                budget_usd = min(ops, max(float(s.monthly_cap_usd or 0), 0.0))
            pid, dup = fal_pipeline.create_production(orch, product, style=style, workspace_id=ctx["wid"],
                                                      client_request_id=crid, budget_usd=budget_usd, prebudget=prebudget)
        except InsufficientCreditsError as exc:
            return self._no_credits(exc)
        finally:
            orch.db.close()
        if not dup:
            self.start_run(pid)
        return _json(200, {"ok": True, "pid": pid, "mode": s.mode, "duplicate": dup})

    def _create(self, payload: dict, ctx) -> Response:
        s = ctx["s"]
        if self._engine_for(ctx["ws"], s) == "fal":
            return self._create_fal(payload, ctx)
        if s.mode == "real" and paid_gate.blocked_reason():   # aviso antes de receber fotos e criar a produção
            return _json(409, {"error": paid_gate.MESSAGES[paid_gate.blocked_reason()], "paid_calls_blocked": True})
        prebudget = s.mode == "real"
        if prebudget:   # pré-orçamento: sem saldo para o vídeo completo, recusa antes de receber fotos
            from .. import budget as budget_mod
            db = Database(s.db_path)
            try:
                Ledger(db).can_reserve(ctx["wid"], budget_mod.estimate_production(s)["cc"])
            except InsufficientCreditsError as exc:
                return self._no_credits(exc)
            finally:
                db.close()
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
                                         budget_usd=self._budget_for(payload, s),
                                         go_ahead=("none" if autonomy == "manual" else "all") if payload.get("flow") == "game" else "all",
                                         autonomy=autonomy, workspace_id=ctx["wid"], prebudget=prebudget,
                                         direction_required=payload.get("flow") == "game")
        except InsufficientCreditsError as exc:
            return self._no_credits(exc)
        finally:
            orch.db.close()
        if payload.get("start", True):
            self.start_run(pid)
        return _json(200, {"ok": True, "pid": pid, "mode": s.mode})

    def _media(self, path: str, ctx, query: str = "") -> Response:
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
        try:   # ../, %2e%2e, barra invertida ou caminho absoluto: resolve() + checagem de pasta => fora = 404
            f = ProductionStorage(s.data_dir, parts[2]).path(unquote(parts[3]))
        except StorageError:
            return _json(404, {"error": "não encontrado"})
        if f.suffix.lower() not in MEDIA_EXTS or not f.is_file():
            return _json(404, {"error": "não encontrado"})
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or f.suffix in (".md", ".json"):
            ctype = ("text/markdown" if f.suffix == ".md" else ctype) + "; charset=utf-8"
        headers = {"Cache-Control": "private, no-store"}
        if parse_qs(query).get("download", [""])[0] == "1":   # download individual (mesma checagem de dono acima)
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", f.name)[:120] or "arquivo"
            headers["Content-Disposition"] = f'attachment; filename="{safe}"'
        return Response(200, ctype, file=f, headers=headers)

    def _action(self, pid: str, action: str, payload: dict, s) -> Response:
        if action != "cancel":   # missão cancelada/falhou: nenhuma ação de avançar (nem por uma tela antiga aberta)
            db = Database(s.db_path)
            try:
                status = db.production(pid)["status"]
            finally:
                db.close()
            if status in (PS.CANCELLED, PS.FAILED):
                what = "cancelada" if status == PS.CANCELLED else "encerrada com falha"
                return _json(409, {"error": f"Esta missão foi {what}: nada mais é gerado nem cobrado nela. "
                                            "Comece uma nova missão.", "ended": status})
        if action == "run":
            self.orch_for(pid).db.close()  # valida se a produção pode rodar no modo atual
            return _json(200, {"ok": True, "started": self.start_run(pid)})
        if action == "confirm":
            # "Confirmar e criar vídeo": só autoriza o custo que o cliente viu (não inicia nada). Quem inicia é a ação
            # seguinte (direction ou run), para a confirmação valer antes de qualquer gasto e sem corrida com a execução.
            orch = self.orch_for(pid)
            try:
                raw = payload.get("total_cc")
                orch.confirm_cost(pid, int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None)
            finally:
                orch.db.close()
            return _json(200, {"ok": True})
        if action == "direction":
            # Sem apresentação explícita, parse_creative cairia no padrão (Somente mãos) e trocaria o formato em silêncio.
            raw = payload.get("creative")
            if not isinstance(raw, dict) or raw.get("presentation") not in creative_options.PRESENTATIONS:
                return _json(400, {"error": "Escolha como apresentar o produto (Somente mãos, Produto em destaque ou "
                                            "Com apresentadora) antes de aprovar a direção."})
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
        if self.is_running(pid) and action in {"approve", "reject", "final", "budget", "retry", "choose", "anchor"}:
            return _json(409, {"error": "a produção está em execução; aguarde terminar a etapa atual"})
        orch = self.orch_for(pid)
        try:
            continue_after = True
            if action == "approve":
                orch.approve(pid, int(payload["scene"]), payload["stage"], payload.get("note", ""))
            elif action == "reject":
                try:
                    orch.reject(pid, int(payload["scene"]), payload["stage"], payload.get("note", ""),
                                redo_image=bool(payload.get("redo_image")), authorize_extra=payload.get("authorize_extra") is True)
                except AdjustmentNeedsAuthorization as exc:   # nada muda até o cliente autorizar, vendo o custo
                    from ..credits import fmt
                    led = Ledger(orch.db)
                    bal = led.balance(orch._wid(pid))
                    short = 0 if led.exempt(orch._wid(pid)) else max(exc.cost_cc - bal, 0)
                    if short:   # sem saldo: nem pede autorização, mostra a conta e as saídas
                        return _no_balance_for_adjustment(exc.cost_cc, bal)
                    return _json(402, {"error": f"Os ajustes incluídos desta cena já foram usados. Um ajuste extra custa "
                                                f"cerca de {fmt(exc.cost_cc)} créditos.", "needs_authorization": True,
                                       "cost_cc": exc.cost_cc, "cost_credits": fmt(exc.cost_cc), "scene": exc.scene,
                                       "stage": exc.stage, "included": exc.included, "used": exc.used})
                except InsufficientCreditsError as exc:   # nada foi gasto nem alterado: o vídeo continua como está
                    return _no_balance_for_adjustment(exc.needed_cc, exc.balance_cc)
            elif action == "choose":   # tentativas esgotadas: aprova uma das versões lado a lado, com um clique
                try:
                    orch.choose_attempt(pid, int(payload["scene"]), str(payload.get("stage") or "image"),
                                        str(payload.get("attempt_id") or ""))
                except OrchestratorError as exc:
                    return _json(409, {"error": str(exc)})
            elif action == "anchor":   # imagem-âncora do produto (ou remover: attempt_id vazio)
                try:
                    orch.set_anchor(pid, str(payload["attempt_id"]) if payload.get("attempt_id") else None)
                except OrchestratorError as exc:
                    return _json(409, {"error": str(exc)})
                continue_after = False
            elif action == "retry":
                stage = payload.get("stage")
                if stage not in {"image", "video"}:
                    return _json(400, {"error": "stage deve ser image ou video"})
                idx = int(payload["scene"])
                if orch.db.scene(pid, idx)["status"] != "blocked":
                    return _json(409, {"error": f"a cena {idx} não está bloqueada"})
                orch.grant_attempts(pid, idx, stage, 1)
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

        def log_message(self, fmt, *args):  # o log de acesso é nosso (JSON, sem query string nem corpo)
            pass

        def _accepts_gzip(self) -> bool:
            return "gzip" in (self.headers.get("Accept-Encoding") or "").lower()

        def _head(self, resp: Response, rid: str, route: str, status: int | None = None) -> None:
            self.send_response(status or resp.status)
            headers = {"Cache-Control": "no-store", "X-Request-Id": rid,
                       **security_headers(app.secure_cookie, panel=route in ("/painel", "/painel/")), **resp.headers}
            for k, v in headers.items():
                for item in (v if isinstance(v, list) else [v]):  # vários Set-Cookie na mesma resposta
                    self.send_header(k, item)

        def _send(self, resp: Response, rid: str = "-", route: str = "") -> None:
            if resp.file is None:
                body = resp.body
                encoded = {}
                if resp.compress:
                    encoded["Vary"] = "Accept-Encoding"
                    if self._accepts_gzip() and len(body) >= GZIP_MIN:
                        body = _gzipped(("b", zlib.crc32(body), len(body)), lambda: resp.body)
                        encoded["Content-Encoding"] = "gzip"
                resp = dataclasses.replace(resp, headers={**resp.headers, **encoded})
                self._head(resp, rid, route)
                self.send_header("Content-Type", resp.content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            st = resp.file.stat()
            size = st.st_size
            ranged = self.headers.get("Range")
            if resp.compress and not ranged and self._accepts_gzip() and GZIP_MIN <= size <= GZIP_MAX:
                data = _gzipped(("f", str(resp.file), st.st_mtime_ns, size), resp.file.read_bytes)
                resp = dataclasses.replace(resp, headers={**resp.headers, "Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
                self._head(resp, rid, route)
                self.send_header("Content-Type", resp.content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            start, end = 0, size - 1
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", ranged or "")
            partial = False
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(size - int(m.group(2)), 0)
                end = min(end, size - 1)
                partial = True
            if resp.compress:
                resp = dataclasses.replace(resp, headers={**resp.headers, "Vary": "Accept-Encoding"})
            self._head(resp, rid, route, 206 if partial else None)
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Type", resp.content_type)
            self.send_header("Accept-Ranges", "bytes")
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

        def _serve(self, method: str) -> None:
            """Uma requisição: id, resposta e uma linha de log JSON (rota sem query, status, duração, workspace)."""
            t0 = time.perf_counter()
            info = {"request_id": secrets.token_hex(6)}
            token = REQUEST_INFO.set(info)
            route = urlparse(self.path).path
            status = 500
            try:
                with app.inflight:
                    try:
                        body = b""
                        if method == "POST":
                            length = int(self.headers.get("Content-Length") or 0)
                            if self.path.startswith("/api/auth/") and length > MAX_AUTH_BODY:
                                resp = _json(413, {"error": "envio grande demais"})
                            elif length > MAX_BODY:
                                resp = _json(413, {"error": "envio grande demais (máx. 150 MB por vez)"})
                            else:
                                body = self.rfile.read(length)
                                resp = None
                        else:
                            resp = None
                        if resp is None:
                            resp = app.handle(method, self.path, dict(self.headers), body, peer=self.client_address[0])
                    except Exception:  # noqa: BLE001 — a resposta não vaza detalhe; o log tem só o tipo da exceção
                        log.error("erro interno", exc_info=True)
                        resp = _json(500, {"error": "erro interno"})
                    status = resp.status
                    self._send(resp, info["request_id"], route)
            finally:
                level = logging.DEBUG if route in ("/healthz", "/readyz") else logging.INFO
                log.log(level, "request", extra={"method": method, "route": route, "status": status,
                                                 "duration_ms": round((time.perf_counter() - t0) * 1000, 1)})
                REQUEST_INFO.reset(token)

        def do_GET(self):
            self._serve("GET")

        def do_POST(self):
            self._serve("POST")

    return Handler


class StudioHTTPServer(ThreadingHTTPServer):
    # No Windows, reutilizar o endereço deixa dois servidores na mesma porta, e o antigo continua respondendo.
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


def _checkpoint_loop(app) -> None:
    """Checkpoint PASSIVE periódico do WAL (STUDIO_WAL_CHECKPOINT_S, padrão 300; 0 desliga)."""
    try:
        every = float(os.environ.get("STUDIO_WAL_CHECKPOINT_S") or 300)
    except ValueError:
        every = 300.0
    while every > 0 and not app.stopping.wait(every):
        try:
            checkpoint(app.settings().db_path)
        except Exception as exc:  # noqa: BLE001 — manutenção nunca derruba o servidor
            log.warning("checkpoint do WAL falhou (%s)", type(exc).__name__)


def _finish_shutdown(app, ckpt: threading.Thread | None, abort, *, clock=time.monotonic) -> dict:
    """Fim da drenagem, com o HTTP já fechado: espera as requisições em andamento e a thread do checkpoint periódico
    (juntas, até HTTP_CLOSE_S) e abre a janela de assentamento (studio.shutdown.settle). Devolve o resultado do settle."""
    until = clock() + HTTP_CLOSE_S
    req_left = app.inflight.wait_idle(HTTP_CLOSE_S)
    if ckpt is not None and ckpt.is_alive():
        ckpt.join(max(until - clock(), 0.0))
    with app.lock:
        runs_alive = sum(1 for t in app.runs.values() if t.is_alive())
    ckpt_alive = bool(ckpt is not None and ckpt.is_alive())
    lvl = logging.WARNING if (req_left or ckpt_alive or runs_alive) else logging.INFO
    log.log(lvl, "drenagem concluida: requisicoes em andamento=%d, checkpoint periodico %s, producoes ainda em chamada=%d",
            req_left, "ATIVO" if ckpt_alive else "parado", runs_alive, extra={"event": "drained"})
    return settle(app.cfg.shutdown_settle_s, abort, clock=clock)


def serve(port: int | None = None, open_browser: bool = True, public_host: str | None = None, *,
          host: str | None = None, trust_proxy: str | None = None) -> None:
    try:
        cfg = ServerConfig.from_env()
        err = backup_start_error() or cfg.shutdown_budget_error()
    except ValueError as exc:
        err = str(exc)
    if err:
        raise SystemExit(f"Kiroo: {err}")
    port = cfg.port if port is None else port
    host = host or cfg.host
    app = App(port, public_host=public_host, trust_proxy=trust_proxy, config=cfg)
    try:
        httpd = StudioHTTPServer((host, port), make_handler(app))
    except OSError as exc:
        raise SystemExit(f"A porta {port} já está em uso: pare o outro servidor do estúdio e tente de novo.") from exc
    try:   # uma instância só por pasta de dados (SQLite e livro de créditos não suportam dois processos)
        lock = acquire_instance_lock(app.settings().data_dir)
    except InstanceLockError as exc:
        httpd.server_close()
        raise SystemExit(str(exc)) from exc

    try:   # schema versionado: migra UMA vez no boot (sob o lock de instância); falha aqui impede o servidor de subir
        Database(app.settings().db_path).close()
        log.info("banco pronto", extra={"event": "db_ready"})
    except Exception as exc:  # noqa: BLE001
        httpd.server_close()
        release_instance_lock(lock)
        raise SystemExit(f"Falha ao preparar o banco ({type(exc).__name__}): {exc}") from exc
    try:
        warn = backup_warning()
    except ValueError as exc:
        warn = str(exc)
    if warn:
        log.critical(warn, extra={"event": "backup_missing"})
    tw = turnstile.startup_warning()
    if tw:
        getattr(log, tw[0])(tw[1], extra={"event": "turnstile_config"})
    ckpt = threading.Thread(target=_checkpoint_loop, args=(app,), name="wal-checkpoint", daemon=True)
    ckpt.start()
    log.info("desligamento: grace %gs + settle %gs; a plataforma precisa dar pelo menos %gs (STUDIO_STOP_GRACE_S=%g)",
             cfg.shutdown_grace_s, cfg.shutdown_settle_s, minimum_platform_s(cfg.shutdown_grace_s, cfg.shutdown_settle_s),
             cfg.stop_grace_s, extra={"event": "shutdown_budget"})

    shown = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    url = f"http://{shown}:{port}/"
    log.info("Kiroo em %s (escutando em %s:%s)", url, host, port, extra={"event": "start"})
    if open_browser:
        print(f"Kiroo em {url}  (Ctrl+C para sair)", flush=True)
        webbrowser.open(url)
    if cfg.invite_codes:
        log.warning("STUDIO_INVITE_CODES é ignorado: convites agora são de uso único, gerados com `studio admin create-invite`.")
    if mailer.protected_env() and not mailer.configured():
        log.warning("E-mail transacional desligado (%s): em staging/produção códigos de confirmação e links de senha NÃO "
                    "são registrados no log. A confirmação de e-mail e o 'esqueci a senha' ficam indisponíveis; use "
                    "`studio admin reset-link` e `studio admin verify-email`.", mailer.config_error())
    try:
        app.bootstrap_admin()
    except Exception as exc:  # noqa: BLE001
        log.error("falha ao criar o administrador inicial (%s)", type(exc).__name__)
    try:
        resumed = app.resume_pending()
        if resumed:
            log.info("retomando %d produção(ões) interrompida(s)", len(resumed), extra={"event": "resume"})
    except Exception as exc:  # noqa: BLE001
        log.error("falha ao retomar produções (%s)", type(exc).__name__)
    try:   # retenção dos artefatos INTERMEDIÁRIOS do motor fal.ai (workflow/attempt_NN); delivery/ nunca é tocada
        from .. import fal_pipeline
        cs = app.settings()
        db0 = Database(cs.db_path)
        try:
            done = fal_pipeline.cleanup_intermediates(cs.data_dir, db0, cs.fal_retention_days)
        finally:
            db0.close()
        if done["removed"]:
            log.info("limpeza de intermediários fal.ai: %d arquivo(s), %d bytes", done["removed"], done["freed_bytes"])
    except Exception as exc:  # noqa: BLE001
        log.error("falha na limpeza de intermediários fal.ai (%s)", type(exc).__name__)

    def drain():   # em outra thread: httpd.shutdown() não pode ser chamado de quem roda serve_forever
        log.info("SIGTERM: parando de aceitar jobs; aguardando até %ss", app.cfg.shutdown_grace_s, extra={"event": "stop"})
        app.shutdown()
        httpd.shutdown()

    # 1º sinal: drenagem; 2º sinal: encerra a janela de assentamento (sai sem esperar o settle).
    ctl = SignalController(drain)
    on_term = ctl.on_signal

    # SIGTERM (Linux/contêiner). No Windows o SIGTERM não chega ao handler (vira TerminateProcess); o desligamento
    # gracioso lá é o CTRL_BREAK_EVENT, que o Python entrega como SIGBREAK.
    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), on_term)
            except (ValueError, OSError):  # fora da thread principal (testes)
                pass
    try:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            ctl.draining.set()
            app.shutdown(3.0)
        finally:
            httpd.server_close()
        # HTTP fechado e produções marcadas: a janela só existe depois de uma drenagem (sinal ou Ctrl+C).
        if ctl.draining.is_set():
            _finish_shutdown(app, ckpt, ctl.abort)
    except KeyboardInterrupt:   # Ctrl+C durante a espera final: sai já
        pass
    finally:
        release_instance_lock(lock)


def _find_cloudflared() -> str | None:
    found = shutil.which("cloudflared")
    if found:
        return found
    candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/cloudflared.exe",
                  Path(os.environ.get("ProgramFiles(x86)", "")) / "cloudflared/cloudflared.exe",
                  Path(os.environ.get("ProgramFiles", "")) / "cloudflared/cloudflared.exe"]
    return next((str(c) for c in candidates if c.is_file()), None)


def publish(port: int | None = None, timeout_s: float = 60.0) -> None:
    """Coloca o estúdio na internet por um túnel rápido da Cloudflare. O servidor continua escutando só em 127.0.0.1."""
    port = ServerConfig.from_env().port if port is None else port
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
        serve(port, open_browser=False, public_host=hosts[0], trust_proxy="cloudflare")
    finally:
        tunnel.terminate()
