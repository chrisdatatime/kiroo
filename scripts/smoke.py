"""Roteiro de fumaça contra um Kiroo já no ar (staging). Só HTTP, nada de banco nem de arquivo local.

    python scripts/smoke.py https://staging.kiroo.app

Faz, nesta ordem: /healthz e /readyz, página inicial, cadastro SEM convite (tem de dar 403), cria dois
usuários de teste, entra, abre o mundo, cria uma produção simulada e espera terminar, baixa o MP4 por
/media com Range, confirma que o OUTRO usuário leva 404 nessa mídia e confere cabeçalhos de segurança e
de cache. Cada item sai como PASS, FAIL ou NAO_VERIFICADO (quando o teste não pôde ser feito).

Os usuários de teste vêm de um convite de uso único. Como criar o convite exige a CLI dentro do
contêiner, informe COMO rodar comando lá com --exec:

    # Railway (CLI do Railway instalado e projeto ligado)
    python scripts/smoke.py https://staging.kiroo.app --exec "railway run --"
    # Docker local
    python scripts/smoke.py http://127.0.0.1:8765 --exec "docker exec -i kiroo-kiroo-1"

Sem --exec, os passos que dependem de conta ficam NAO_VERIFICADO, a menos que você passe contas que já
existam:

    python scripts/smoke.py https://staging.kiroo.app --email a@x --password ... --email2 b@x --password2 ...

Nada é impresso que possa virar credencial: senhas geradas aqui não vão para a saída, e o código do
convite aparece no máximo como "convite obtido". As contas criadas ficam no banco (são de teste, em DEMO
e sem crédito); apague com `studio admin delete-user` quando quiser.

Códigos de saída: 0 = nenhum FAIL; 1 = houve FAIL; 2 = uso inválido.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import secrets
import shlex
import ssl
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib
from urllib.parse import urlsplit

PASS, FAIL, SKIP = "PASS", "FAIL", "NAO_VERIFICADO"
# Cabeçalhos que o servidor manda em toda resposta (src/studio/web/server.py: SECURITY_HEADERS).
SEGURANCA = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
resultados: list[tuple[str, str, str]] = []


def png_ficticio(largura: int = 90, altura: int = 160, cor=(180, 120, 90)) -> str:
    """PNG de cor sólida, montado aqui mesmo (sem Pillow), como "foto do produto" de referência.

    A esteira precisa de ao menos uma referência para sair de `awaiting_references`. Devolve data URL.
    """
    linha = bytes([0]) + bytes(cor) * largura            # filtro 0 + pixels RGB
    def pedaco(tipo: bytes, dado: bytes) -> bytes:
        return struct.pack(">I", len(dado)) + tipo + dado + struct.pack(">I", zlib.crc32(tipo + dado) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n"
           + pedaco(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0))
           + pedaco(b"IDAT", zlib.compress(linha * altura, 9))
           + pedaco(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


def item(nome: str, estado: str, detalhe: str = "") -> str:
    resultados.append((nome, estado, detalhe))
    print(f"[{estado:14}] {nome}" + (f" — {detalhe}" if detalhe else ""), flush=True)
    return estado


class Cliente:
    """Cliente HTTP com cookie de sessão e token CSRF, como o navegador do jogo."""

    def __init__(self, base: str, inseguro: bool = False):
        self.base = base.rstrip("/")
        self.cookie = ""
        self.csrf = ""
        self.ctx = ssl._create_unverified_context() if inseguro else None

    def pedir(self, metodo: str, caminho: str, corpo=None, cabecalhos=None, timeout=30):
        """Devolve (status, cabeçalhos, bytes). Erro de HTTP não levanta: 4xx/5xx também são resposta."""
        url = self.base + caminho
        h = {"X-Studio-Client": "game", "Accept": "*/*", "User-Agent": "kiroo-smoke/1"}
        if corpo is not None:
            h["Content-Type"] = "application/json"
        if self.cookie:
            h["Cookie"] = self.cookie
        if self.csrf:
            h["X-Studio-Token"] = self.csrf
        h.update(cabecalhos or {})
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(url, data=dados, headers=h, method=metodo)
        try:
            r = urllib.request.urlopen(req, timeout=timeout, context=self.ctx)
        except urllib.error.HTTPError as e:
            r = e
        except (urllib.error.URLError, OSError, ssl.SSLError) as e:
            raise ConnectionError(f"{metodo} {caminho}: {type(e).__name__}") from None
        with r:
            dado = r.read()
            cab = {k.title(): v for k, v in r.headers.items()}
            sc = r.getcode()
            posto = r.headers.get("Set-Cookie")
        if posto:
            self.cookie = posto.split(";")[0]
        return sc, cab, dado

    def json(self, metodo, caminho, corpo=None, **kw):
        sc, cab, dado = self.pedir(metodo, caminho, corpo, **kw)
        try:
            return sc, cab, json.loads(dado or b"{}")
        except ValueError:
            return sc, cab, {"_bruto": dado[:200].decode("utf-8", "replace")}

    def pegar_csrf(self) -> bool:
        sc, _, corpo = self.json("GET", "/api/me")
        self.csrf = (corpo or {}).get("csrf", "") if sc == 200 else ""
        return bool(self.csrf)

    def entrar(self, email: str, senha: str) -> tuple[bool, str]:
        sc, _, corpo = self.json("POST", "/api/auth/login", {"email": email, "password": senha})
        if sc != 200:
            return False, f"login devolveu {sc} {str(corpo)[:80]}"
        if not self.pegar_csrf():
            return False, "entrou mas /api/me não deu csrf"
        return True, ""


# ----------------------------------------------------------------- CLI dentro do contêiner

def rodar_cli(exec_prefix: str, args: list[str], timeout=120, python="python") -> tuple[int, str]:
    cmd = shlex.split(exec_prefix) + shlex.split(python) + ["-m", "studio", *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, f"{type(e).__name__}"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def criar_convite(exec_prefix: str, python: str) -> str | None:
    """`studio admin create-invite`. Devolve o código (que NÃO imprimimos) ou None."""
    rc, saida = rodar_cli(exec_prefix, ["admin", "create-invite", "--days", "1", "--note", "smoke"], python=python)
    if rc != 0:
        return None
    m = re.search(r"convite:\s*(\S+)", saida)
    return m.group(1) if m else None


def cadastrar(cli: Cliente, email: str, senha: str, convite: str) -> tuple[bool, str]:
    sc, _, corpo = cli.json("POST", "/api/auth/signup",
                            {"email": email, "password": senha, "invite": convite, "consent": True,
                             "name": "Smoke", "workspace": "smoke"})
    if sc != 200:
        return False, f"cadastro devolveu {sc} {str(corpo)[:100]}"
    return cli.pegar_csrf(), "" if cli.csrf else "cadastrou mas /api/me não deu csrf"


# ----------------------------------------------------------------- os itens

def checar_saude(cli: Cliente) -> None:
    for caminho, nome in (("/healthz", "/healthz responde 200"), ("/readyz", "/readyz responde 200")):
        try:
            sc, _, corpo = cli.json("GET", caminho)
        except ConnectionError as e:
            item(nome, FAIL, str(e))
            continue
        if sc != 200:
            item(nome, FAIL, f"status {sc} {str(corpo)[:80]}")
            continue
        avisos = corpo.get("warnings") or []
        item(nome, PASS, f"status={corpo.get('status', '?')}" + (f" avisos={avisos}" if avisos else ""))
        if caminho == "/readyz":
            if "backup_not_configured" in avisos:
                item("/readyz sem aviso de backup", FAIL, "backup_not_configured: faltam BACKUP_R2_*")
            else:
                item("/readyz sem aviso de backup", PASS)


def checar_inicial(cli: Cliente) -> dict:
    try:
        sc, cab, dado = cli.pedir("GET", "/")
    except ConnectionError as e:
        item("página inicial carrega", FAIL, str(e))
        return {}
    ok = sc == 200 and cab.get("Content-Type", "").startswith("text/html") and b"<div id=" in dado
    detalhe = f"status {sc}, {len(dado)} bytes, tipo {cab.get('Content-Type', '?')}"
    if sc in (401, 403) and "json" in cab.get("Content-Type", ""):
        # "/" só é público quando existe frontend/dist/index.html na imagem; sem ele a rota cai no fluxo com sessão
        detalhe += " — a imagem parece não ter o frontend construído (frontend/dist/index.html)"
    item("página inicial carrega", PASS if ok else FAIL, detalhe)
    return cab


def checar_cadastro_sem_convite(cli: Cliente) -> None:
    """Com STUDIO_SIGNUP=invite, cadastrar sem código tem de ser recusado com 403."""
    sc, _, corpo = Cliente(cli.base, cli.ctx is not None).json(
        "POST", "/api/auth/signup",
        {"email": f"sem-convite-{secrets.token_hex(4)}@kiroo.test", "password": secrets.token_urlsafe(16),
         "consent": True})
    modo = None
    try:
        modo = cli.json("GET", "/api/config")[2].get("signup")
    except ConnectionError:
        pass
    if modo == "open":
        item("cadastro sem convite recusado (403)", FAIL, "STUDIO_SIGNUP=open: staging deve ser invite")
    elif sc == 403:
        item("cadastro sem convite recusado (403)", PASS, f"modo={modo}, erro: {str(corpo.get('error'))[:60]}")
    else:
        item("cadastro sem convite recusado (403)", FAIL, f"esperado 403, veio {sc} {str(corpo)[:80]}")


def preparar_contas(cli_a: Cliente, cli_b: Cliente, args) -> tuple[bool, bool]:
    """Devolve (tem_a, tem_b). Usa --exec (convite + cadastro) ou contas já existentes."""
    if args.email and args.password:
        ok, erro = cli_a.entrar(args.email, args.password)
        item("usuário de teste disponível", PASS if ok else FAIL, "conta informada em --email" if ok else erro)
        tem_a = ok
        if args.email2 and args.password2:
            ok2, erro2 = cli_b.entrar(args.email2, args.password2)
            item("segundo usuário disponível", PASS if ok2 else FAIL, "conta informada em --email2" if ok2 else erro2)
            return tem_a, ok2
        item("segundo usuário disponível", SKIP, "sem --email2/--password2")
        return tem_a, False

    if not args.exec_prefix:
        item("usuário de teste criado pela CLI no contêiner", SKIP,
             "sem --exec e sem --email/--password: não há como criar conta")
        item("segundo usuário disponível", SKIP, "depende do item acima")
        return False, False

    rc, saida = rodar_cli(args.exec_prefix, ["--help"], timeout=60, python=args.python)
    if rc != 0:
        item("usuário de teste criado pela CLI no contêiner", FAIL,
             f"--exec não executou a CLI (código {rc}): {saida.strip()[:120]}")
        item("segundo usuário disponível", SKIP, "depende do item acima")
        return False, False

    criados = []
    for rotulo, c in (("principal", cli_a), ("segundo", cli_b)):
        convite = criar_convite(args.exec_prefix, args.python)
        if not convite:
            criados.append((rotulo, False, "create-invite não devolveu código"))
            continue
        email = f"smoke-{rotulo}-{secrets.token_hex(5)}@kiroo.test"
        senha = secrets.token_urlsafe(18)
        ok, erro = cadastrar(c, email, senha, convite)
        criados.append((rotulo, ok, erro or f"conta {email} criada por convite"))
    item("usuário de teste criado pela CLI no contêiner", PASS if criados[0][1] else FAIL, criados[0][2])
    item("segundo usuário disponível", PASS if criados[1][1] else FAIL, criados[1][2])
    return criados[0][1], criados[1][1]


def checar_login(cli: Cliente, tem_a: bool) -> None:
    if not tem_a:
        item("sessão válida (login + csrf)", SKIP, "sem conta de teste")
        return
    sc, _, corpo = cli.json("GET", "/api/me")
    ok = sc == 200 and bool(corpo.get("csrf")) and bool(corpo.get("email") or corpo.get("workspace"))
    item("sessão válida (login + csrf)", PASS if ok else FAIL, f"status {sc}")


def checar_mundo(cli: Cliente, tem_a: bool) -> None:
    if not tem_a:
        item("mundo abre (/api/state)", SKIP, "sem conta de teste")
        return
    sc, _, corpo = cli.json("GET", "/api/state")
    if sc != 200:
        item("mundo abre (/api/state)", FAIL, f"status {sc} {str(corpo)[:80]}")
        return
    tem = [k for k in ("credits", "productions", "selected", "agents") if k in corpo]
    item("mundo abre (/api/state)", PASS if "credits" in corpo else FAIL, f"campos presentes: {tem}")


def criar_producao(cli: Cliente, tem_a: bool, timeout: int) -> str | None:
    if not tem_a:
        item("produção simulada criada", SKIP, "sem conta de teste")
        item("produção simulada terminou", SKIP, "sem conta de teste")
        return None
    corpo = {"name": "Copo de fumaça", "variant": "azul", "budget": 5, "autonomy": "automatico",
             "affiliate_link": "https://s.shopee.com.br/7VHTuA2W1j", "start": True,
             "files": [{"name": "frente.png", "data": png_ficticio(), "role": "front"}]}
    sc, _, resp = cli.json("POST", "/api/productions", corpo, timeout=60)
    pid = resp.get("pid") if sc == 200 else None
    if not pid:
        item("produção simulada criada", FAIL, f"status {sc} {str(resp)[:120]}")
        item("produção simulada terminou", SKIP, "não foi criada")
        return None
    item("produção simulada criada", PASS, f"{pid} (modo {resp.get('mode')})")

    # Espera a esteira chegar à revisão final; "automatico" para ali de propósito.
    def esperar(parar_em: tuple[str, ...]) -> str:
        fim = time.time() + timeout
        atual = "?"
        while time.time() < fim:
            _, _, st = cli.json("GET", f"/api/state?pid={pid}")
            atual = (st.get("production") or {}).get("status") or st.get("status") or "?"
            if atual in parar_em or (st.get("delivery") or {}).get("final.mp4"):
                return atual
            time.sleep(3)
        return atual

    alvos = ("awaiting_final_review", "awaiting_references", "completed", "failed", "cancelled")
    estado = esperar(alvos)
    if estado == "awaiting_references":
        # a esteira quer referência: manda a mesma imagem pelo caminho dedicado e segue
        sc, _, _ = cli.json("POST", f"/api/productions/{pid}/references",
                            {"files": [{"name": "frente.png", "data": png_ficticio(), "role": "front"}]}, timeout=60)
        if sc != 200:
            item("produção simulada terminou", FAIL, f"envio de referência devolveu {sc}")
            return pid
        estado = esperar(alvos)
    if estado == "awaiting_final_review":
        sc, _, _ = cli.json("POST", f"/api/productions/{pid}/final", {"decision": "approve"}, timeout=60)
        if sc != 200:
            item("produção simulada terminou", FAIL, f"aprovação final devolveu {sc}")
            return pid
        estado = esperar(("completed", "failed", "cancelled"))
    if estado in ("failed", "cancelled"):
        item("produção simulada terminou", FAIL, f"status final {estado}")
    elif estado == "?":
        item("produção simulada terminou", FAIL, f"não terminou em {timeout}s")
    else:
        item("produção simulada terminou", PASS, f"status {estado}")
    return pid


def checar_media(cli_a: Cliente, cli_b: Cliente, pid: str | None, tem_b: bool) -> None:
    nomes = ("MP4 baixa por /media com Range (206)", "mídia de outro usuário dá 404",
             "mídia com Cache-Control private, no-store")
    if not pid:
        for n in nomes:
            item(n, SKIP, "sem produção")
        return
    caminho = f"/media/{pid}/delivery/final.mp4"
    try:
        sc, cab, dado = cli_a.pedir("GET", caminho, cabecalhos={"Range": "bytes=0-1023"}, timeout=120)
    except ConnectionError as e:
        for n in nomes:
            item(n, FAIL, str(e))
        return
    if sc == 404:
        for n in nomes[:1] + nomes[2:]:
            item(n, FAIL, "final.mp4 não existe (a montagem não gerou o vídeo?)")
        item(nomes[1], SKIP, "sem mídia para comparar")
        return
    faixa = cab.get("Content-Range", "")
    ok = sc == 206 and len(dado) == 1024 and re.match(r"bytes 0-1023/\d+", faixa) \
        and cab.get("Accept-Ranges") == "bytes"
    item(nomes[0], PASS if ok else FAIL, f"status {sc}, {len(dado)} bytes, Content-Range: {faixa or '-'}")

    if tem_b:
        sc2, _, _ = cli_b.pedir("GET", caminho, timeout=60)
        item(nomes[1], PASS if sc2 == 404 else FAIL,
             f"status {sc2}" + ("" if sc2 == 404 else " — VAZAMENTO ENTRE CONTAS"))
    else:
        item(nomes[1], SKIP, "sem segundo usuário")

    cc = (cab.get("Cache-Control") or "").lower()
    ok_cc = "no-store" in cc and "private" in cc
    item(nomes[2], PASS if ok_cc else FAIL, f"Cache-Control: {cab.get('Cache-Control', '-')}")


def checar_cabecalhos(cli: Cliente, cab_inicial: dict) -> None:
    if not cab_inicial:
        item("cabeçalhos de segurança na página inicial", SKIP, "página inicial não carregou")
        item("HSTS presente (HTTPS)", SKIP, "página inicial não carregou")
        item("CSP presente", SKIP, "página inicial não carregou")
        item("página inicial com Cache-Control no-cache", SKIP, "página inicial não carregou")
        return
    faltando = [k for k, v in SEGURANCA.items() if cab_inicial.get(k) != v]
    sem_pp = "Permissions-Policy" not in cab_inicial
    item("cabeçalhos de segurança na página inicial", PASS if not faltando and not sem_pp else FAIL,
         "todos presentes" if not faltando and not sem_pp
         else f"errados/ausentes: {faltando}{' + Permissions-Policy' if sem_pp else ''}")

    csp = cab_inicial.get("Content-Security-Policy", "")
    ok_csp = "default-src" in csp and "'unsafe-eval'" not in csp
    item("CSP presente", PASS if ok_csp else FAIL,
         f"{csp[:70]}..." if csp else "ausente")

    https = urlsplit(cli.base).scheme == "https"
    hsts = cab_inicial.get("Strict-Transport-Security", "")
    if not https:
        item("HSTS presente (HTTPS)", SKIP, "URL em http: HSTS só sai com STUDIO_SECURE_COOKIE=1 e HTTPS")
    else:
        item("HSTS presente (HTTPS)", PASS if "max-age=" in hsts else FAIL, hsts or "ausente (STUDIO_SECURE_COOKIE=1?)")

    cc = (cab_inicial.get("Cache-Control") or "").lower()
    item("página inicial com Cache-Control no-cache", PASS if "no-cache" in cc or "no-store" in cc else FAIL,
         f"Cache-Control: {cab_inicial.get('Cache-Control', '-')}")


def checar_cache_api(cli: Cliente) -> None:
    try:
        sc, cab, _ = cli.pedir("GET", "/api/config")
    except ConnectionError as e:
        item("resposta de /api/ não é cacheável", FAIL, str(e))
        return
    cc = (cab.get("Cache-Control") or "").lower()
    item("resposta de /api/ não é cacheável", PASS if "no-store" in cc else FAIL,
         f"status {sc}, Cache-Control: {cab.get('Cache-Control', '-')}")
    cf = cab.get("Cf-Cache-Status")
    if cf is None:
        item("Cloudflare não guarda /api/ (cf-cache-status)", SKIP, "sem cabeçalho da Cloudflare nesta resposta")
    else:
        item("Cloudflare não guarda /api/ (cf-cache-status)",
             PASS if cf.upper() in ("BYPASS", "DYNAMIC") else FAIL, f"cf-cache-status: {cf}")


# ----------------------------------------------------------------- principal

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url", help="base do serviço, ex.: https://staging.kiroo.app")
    ap.add_argument("--exec", dest="exec_prefix", default="",
                    help='como rodar comando no contêiner, ex.: "railway run --" ou "docker exec -i kiroo-kiroo-1"')
    ap.add_argument("--python", default="python", help="interpretador dentro do contêiner (padrão: python)")
    ap.add_argument("--email"), ap.add_argument("--password")
    ap.add_argument("--email2"), ap.add_argument("--password2")
    ap.add_argument("--timeout", type=int, default=420, help="espera máxima da produção, em segundos")
    ap.add_argument("--inseguro", action="store_true", help="não validar o certificado TLS (só para teste local)")
    args = ap.parse_args(argv)
    if not re.match(r"^https?://", args.url):
        print("erro: a URL precisa começar com http:// ou https://", file=sys.stderr)
        return 2
    if urlsplit(args.url).scheme == "http" and not re.match(r"^http://(127\.0\.0\.1|localhost)", args.url):
        print("aviso: URL em http fora de localhost; cookie de sessão e HSTS não serão testados de verdade",
              file=sys.stderr)

    print(f"Kiroo — fumaça em {args.url}\n")
    cli_a = Cliente(args.url, args.inseguro)
    cli_b = Cliente(args.url, args.inseguro)

    checar_saude(cli_a)
    cab_inicial = checar_inicial(cli_a)
    checar_cabecalhos(cli_a, cab_inicial)
    checar_cache_api(cli_a)
    checar_cadastro_sem_convite(cli_a)
    tem_a, tem_b = preparar_contas(cli_a, cli_b, args)
    checar_login(cli_a, tem_a)
    checar_mundo(cli_a, tem_a)
    pid = criar_producao(cli_a, tem_a, args.timeout)
    checar_media(cli_a, cli_b, pid, tem_b)

    falhas = [n for n, e, _ in resultados if e == FAIL]
    pulados = [n for n, e, _ in resultados if e == SKIP]
    print(f"\n{sum(1 for _, e, _ in resultados if e == PASS)}/{len(resultados)} PASS, "
          f"{len(falhas)} FAIL, {len(pulados)} NAO_VERIFICADO")
    for n in falhas:
        print(f"  FAIL: {n}")
    for n in pulados:
        print(f"  NAO_VERIFICADO: {n}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
