"""Limite de requisições em memória (instância única) por IP e por usuário em /api/*.

Janela deslizante: cada chave guarda os instantes das últimas requisições. Estourou => 429 com Retry-After (segundos
até a requisição mais antiga sair da janela). Só funciona com UM processo (é o caso: há trava de instância única);
com mais de uma réplica, cada uma teria a própria contagem.

Configuração ("N/S" = N requisições a cada S segundos; 0 desliga aquela regra):
  STUDIO_RATE_LIMIT=0          desliga tudo (não use em staging/produção)
  STUDIO_RATE_API_IP=600/60    /api/* por IP (vários usuários atrás do mesmo NAT)
  STUDIO_RATE_API_USER=300/60  /api/* por usuário (o jogo consulta /api/state a cada 1,5 s)
  STUDIO_RATE_AUTH=20/300      /api/auth/* por IP (entrar, cadastro, esqueci a senha, código)
  STUDIO_RATE_CHAT=12/60       conversa com os agentes, por usuário
  STUDIO_RATE_UPLOAD=10/60     envio de arquivos (referências, trilhas, referência de treino), por usuário
  STUDIO_RATE_CREATE=6/300     criação de produção (inclui demo), por usuário
  STUDIO_RATE_ADMIN=60/60      aba Administrador (/api/admin/*, leitura e escrita), por usuário
"""

from __future__ import annotations

import math
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, fields

# Os testes desligam o limite por padrão (conftest) e ligam explicitamente onde é o assunto.
DEFAULT_ON = True
MAX_KEYS = 50_000   # teto de memória: acima disso as chaves mais antigas saem


@dataclass(frozen=True)
class Rule:
    limit: int
    window_s: float

    @classmethod
    def parse(cls, name: str, raw: str) -> "Rule":
        m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+(?:\.\d+)?)\s*", raw or "")
        if not m or float(m.group(2)) <= 0:
            raise ValueError(f"{name} deve ser N/S, por exemplo 10/60 (recebido {raw!r})")
        return cls(int(m.group(1)), float(m.group(2)))


@dataclass(frozen=True)
class RateLimitConfig:
    enabled: bool = True
    api_ip: Rule = Rule(600, 60)
    api_user: Rule = Rule(300, 60)
    auth: Rule = Rule(20, 300)
    chat: Rule = Rule(12, 60)
    upload: Rule = Rule(10, 60)
    create: Rule = Rule(6, 300)
    admin: Rule = Rule(60, 60)

    @classmethod
    def from_env(cls, env=None) -> "RateLimitConfig":
        e = os.environ if env is None else env
        raw = (e.get("STUDIO_RATE_LIMIT") or "").strip().lower()
        enabled = DEFAULT_ON if not raw else raw not in {"0", "false", "no", "nao", "não", "off"}
        values = {}
        for f in fields(cls):
            if f.name == "enabled":
                continue
            name = f"STUDIO_RATE_{f.name.upper()}"
            if e.get(name):
                values[f.name] = Rule.parse(name, e[name])
        return cls(enabled=enabled, **values)


class RateLimiter:
    def __init__(self, config: RateLimitConfig | None = None, clock=time.monotonic):
        self.config = config or RateLimitConfig.from_env()
        self.clock = clock
        self._hits: dict[tuple[str, str], deque] = {}
        self._lock = threading.Lock()

    def hit(self, bucket: str, key: str) -> int | None:
        """Conta uma requisição. Devolve None se passou, ou os segundos de espera (Retry-After) se estourou."""
        if not self.config.enabled:
            return None
        rule: Rule = getattr(self.config, bucket)
        if rule.limit <= 0:
            return None
        now = self.clock()
        k = (bucket, key)
        with self._lock:
            q = self._hits.get(k)
            if q is None:
                if len(self._hits) >= MAX_KEYS:
                    self._evict(now)
                q = self._hits[k] = deque()
            while q and q[0] <= now - rule.window_s:
                q.popleft()
            if len(q) >= rule.limit:
                return max(1, math.ceil(q[0] + rule.window_s - now))
            q.append(now)
            return None

    def _evict(self, now: float) -> None:
        longest = max(getattr(self.config, f.name).window_s for f in fields(self.config) if f.name != "enabled")
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - longest]:
            del self._hits[k]
        while len(self._hits) >= MAX_KEYS:
            self._hits.pop(next(iter(self._hits)))


def classify(method: str, path: str, payload_has_file: bool = False) -> str | None:
    """Regra específica da rota autenticada (além do limite geral de /api/*)."""
    if path == "/api/admin" or path.startswith("/api/admin/"):
        return "admin"
    if method != "POST":
        return None
    if path == "/api/chat":
        return "chat"
    if path in ("/api/productions", "/api/demo"):
        return "create"
    if path == "/api/music/upload" or re.fullmatch(r"/api/productions/prod_[0-9a-f]{10}/references", path):
        return "upload"
    if re.fullmatch(r"/api/training/[a-z_]+/ref", path) and payload_has_file:
        return "upload"
    return None
