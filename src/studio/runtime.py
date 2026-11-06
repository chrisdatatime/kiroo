"""Configuração de execução do servidor (rede, proxy, cadastro, desligamento) e trava de instância única.

Tudo vem de variáveis de ambiente `STUDIO_*`; ver docs/RUNBOOK.md. Os padrões são os mais fechados:
escuta só em 127.0.0.1, cadastro fechado, nenhum cabeçalho de proxy é confiável.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path

SIGNUP_MODES = ("closed", "invite", "open")
TRUST_PROXY_MODES = ("none", "cloudflare", "forwarded")
LOCK_NAME = "studio.lock"


class InstanceLockError(RuntimeError):
    pass


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _choice(name: str, value: str | None, allowed: tuple[str, ...], default: str) -> str:
    v = (value or default).strip().lower()
    if v not in allowed:
        raise ValueError(f"{name} deve ser um de: {', '.join(allowed)} (recebido {v!r})")
    return v


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    signup: str = "closed"
    invite_codes: tuple[str, ...] = field(default=(), repr=False)
    trust_proxy: str = "none"
    public_host: str | None = None
    allowed_hosts: tuple[str, ...] = ()
    secure_cookie: bool = False
    bootstrap_admin_email: str | None = None
    shutdown_grace_s: float = 25.0
    resume_max_attempts: int = 3

    @classmethod
    def from_env(cls, env=None) -> "ServerConfig":
        e = os.environ if env is None else env
        get = e.get
        port = get("STUDIO_PORT") or get("PORT") or "8765"
        try:
            port_n = int(port)
        except ValueError as exc:
            raise ValueError(f"porta inválida: {port!r}") from exc
        return cls(
            host=(get("STUDIO_HOST") or "127.0.0.1").strip(),
            port=port_n,
            signup=_choice("STUDIO_SIGNUP", get("STUDIO_SIGNUP"), SIGNUP_MODES, "closed"),
            invite_codes=tuple(_csv(get("STUDIO_INVITE_CODES"))),
            trust_proxy=_choice("STUDIO_TRUST_PROXY", get("STUDIO_TRUST_PROXY"), TRUST_PROXY_MODES, "none"),
            public_host=(get("STUDIO_PUBLIC_HOST") or "").strip().lower() or None,
            allowed_hosts=tuple(h.lower() for h in _csv(get("STUDIO_ALLOWED_HOSTS"))),
            secure_cookie=get("STUDIO_SECURE_COOKIE") == "1",
            bootstrap_admin_email=(get("STUDIO_BOOTSTRAP_ADMIN_EMAIL") or "").strip().lower() or None,
            shutdown_grace_s=float(get("STUDIO_SHUTDOWN_GRACE_S") or 25),
            resume_max_attempts=int(get("STUDIO_RESUME_MAX_ATTEMPTS") or 3),
        )


# ------------------------------------------------------------------ IP do cliente
def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(headers: dict, mode: str, peer: str = "") -> str:
    """IP do cliente. Os cabeçalhos do proxy só valem quando o operador os declarou confiáveis (`mode`).

    `headers` já vem com as chaves no formato `Title-Case`. Valor inválido cai no IP do socket (`peer`).
    cloudflare: CF-Connecting-IP (a Cloudflare sobrescreve). forwarded: primeiro item de X-Forwarded-For
    (o proxy precisa SUBSTITUIR o cabeçalho que veio do cliente, não acrescentar).
    """
    raw = ""
    if mode == "cloudflare":
        raw = headers.get("Cf-Connecting-Ip", "")
    elif mode == "forwarded":
        raw = headers.get("X-Forwarded-For", "").split(",")[0]
    return (_valid_ip(raw) if raw else None) or _valid_ip(peer) or "local"


# ------------------------------------------------------------ instância única
_held_locks: list = []


def acquire_instance_lock(data_dir: Path):
    """Trava `STUDIO_DATA_DIR/studio.lock` por toda a vida do processo. O SQLite e o livro de créditos
    só são seguros com um único processo; um segundo servidor sobre a mesma pasta recusa subir."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / LOCK_NAME
    fh = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        other = ""
        try:
            fh.seek(0)
            other = fh.read(32).decode("ascii", "ignore").strip()
        except OSError:
            pass
        fh.close()
        raise InstanceLockError(
            f"Outro processo do Kiroo já está usando {data_dir}" + (f" (PID {other})" if other.isdigit() else "")
            + ". Só uma instância pode usar esta pasta de dados: pare a outra ou aponte STUDIO_DATA_DIR para outra pasta."
        ) from exc
    try:
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()).encode("ascii"))
        fh.flush()
    except OSError:
        pass
    _held_locks.append(fh)
    return fh


def release_instance_lock(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        fh.close()
    except OSError:
        pass
    if fh in _held_locks:
        _held_locks.remove(fh)
