"""Fim do desligamento: janela de assentamento (settle) e orçamento de tempo até o SIGKILL da plataforma.

Por que existe (Litestream v0.3.13 com `-exec`): o Litestream fica vivo esperando o servidor (processo filho) sair e
só então chama `DB.Close()`, que cancela o contexto do banco. Enquanto ele espera, o monitor do banco (1 s) e o da
réplica (sync-interval 1 s) continuam rodando com contexto válido. Se o servidor sai logo depois da drenagem, o
`Close` pega um envio em voo (`monitor error ... RequestCanceled`) ou faz o checkpoint pendente já com o contexto
cancelado (`checkpoint: ... release read lock: context canceled`, saída 1). A janela de assentamento mantém o
processo vivo, sem escrever nada, por `STUDIO_SHUTDOWN_SETTLE_S` segundos depois da drenagem, para o Litestream
fazer o último sync e o checkpoint pendente antes do `Close`. Detalhes e trechos do código: docs/RUNBOOK.md.

Orçamento (precisa caber no tempo que a plataforma dá entre o SIGTERM e o SIGKILL, `STUDIO_STOP_GRACE_S`):
    STUDIO_SHUTDOWN_GRACE_S + HTTP_CLOSE_S + STUDIO_SHUTDOWN_SETTLE_S + LITESTREAM_CLOSE_MARGIN_S <= STUDIO_STOP_GRACE_S
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger("studio.shutdown")

SETTLE_DEFAULT_S = 3.0
SETTLE_MAX_S = 15.0
STOP_GRACE_DEFAULT_S = 40.0          # stop_grace_period do docker-compose.yml
HTTP_CLOSE_S = 2.0                   # requisições em andamento + thread do checkpoint periódico, depois do HTTP fechado
LITESTREAM_CLOSE_MARGIN_S = 5.0      # DB.Close do Litestream: Sync final do banco + Sync final da réplica (envio ao R2)


def parse_seconds(name: str, value: str | None, default: float, lo: float, hi: float | None = None) -> float:
    """Número de segundos de uma variável de ambiente; vazio = padrão. Fora de [lo, hi] ou não numérico: ValueError."""
    raw = (value or "").strip()
    if not raw:
        return float(default)
    try:
        v = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} deve ser um número de segundos (recebido {raw!r})") from exc
    if v != v or v < lo or (hi is not None and v > hi):   # v != v: NaN
        faixa = f"entre {lo:g} e {hi:g}" if hi is not None else f">= {lo:g}"
        raise ValueError(f"{name} deve estar {faixa} (recebido {raw!r})")
    return v


def parse_settle(value: str | None) -> float:
    """STUDIO_SHUTDOWN_SETTLE_S: padrão 3; aceita de 0 a 15; 0 desativa a janela."""
    return parse_seconds("STUDIO_SHUTDOWN_SETTLE_S", value, SETTLE_DEFAULT_S, 0.0, SETTLE_MAX_S)


@dataclass(frozen=True)
class Budget:
    grace_s: float
    http_close_s: float
    settle_s: float
    litestream_close_s: float
    platform_s: float

    @property
    def total_s(self) -> float:
        return self.grace_s + self.http_close_s + self.settle_s + self.litestream_close_s

    @property
    def ok(self) -> bool:
        return self.total_s <= self.platform_s

    def describe(self) -> str:
        return (f"STUDIO_SHUTDOWN_GRACE_S {self.grace_s:g} + fechamento do HTTP {self.http_close_s:g} + "
                f"STUDIO_SHUTDOWN_SETTLE_S {self.settle_s:g} + fechamento do Litestream {self.litestream_close_s:g} "
                f"= {self.total_s:g} s; a plataforma dá {self.platform_s:g} s (STUDIO_STOP_GRACE_S)")


def budget(grace_s: float, settle_s: float, platform_s: float) -> Budget:
    return Budget(grace_s, HTTP_CLOSE_S, settle_s, LITESTREAM_CLOSE_MARGIN_S, platform_s)


def budget_error(grace_s: float, settle_s: float, platform_s: float) -> str | None:
    """Mensagem de recusa quando o desligamento não cabe no prazo da plataforma; None se cabe."""
    b = budget(grace_s, settle_s, platform_s)
    if b.ok:
        return None
    return (f"o desligamento não cabe no prazo da plataforma: {b.describe()}. Reduza STUDIO_SHUTDOWN_GRACE_S ou "
            f"STUDIO_SHUTDOWN_SETTLE_S, ou aumente o prazo da plataforma (stop_grace_period / terminationGracePeriodSeconds) "
            f"e STUDIO_STOP_GRACE_S para pelo menos {b.total_s:g} s.")


def minimum_platform_s(grace_s: float, settle_s: float) -> float:
    """Menor prazo (SIGTERM -> SIGKILL) que a plataforma precisa dar ao processo."""
    return budget(grace_s, settle_s, 0.0).total_s


# ------------------------------------------------------------------ requisições em andamento
class Inflight:
    """Conta as requisições HTTP em andamento, para a drenagem esperar a última terminar (inclusive o commit)."""

    def __init__(self) -> None:
        self._n = 0
        self._cond = threading.Condition()

    def __enter__(self):
        with self._cond:
            self._n += 1
        return self

    def __exit__(self, *exc) -> None:
        with self._cond:
            self._n -= 1
            if self._n <= 0:
                self._cond.notify_all()

    @property
    def count(self) -> int:
        with self._cond:
            return self._n

    def wait_idle(self, timeout: float) -> int:
        """Espera até `timeout` s não haver requisição em andamento. Devolve quantas sobraram."""
        with self._cond:
            self._cond.wait_for(lambda: self._n <= 0, max(timeout, 0.0))
            return self._n


# ------------------------------------------------------------------ janela de assentamento
def settle(seconds: float, abort, *, clock: Callable[[], float] = time.monotonic) -> dict:
    """Mantém o processo vivo por `seconds` sem escrever nada, para o Litestream (que espera este processo sair)
    fazer o último sync e o checkpoint pendente com contexto válido. `abort` (threading.Event ou equivalente com
    `wait(timeout) -> bool`) encerra a janela antes: segundo sinal. 0 desativa. Registra `settle_start`/`settle_end`."""
    if seconds <= 0:
        log.info("settle desativado (STUDIO_SHUTDOWN_SETTLE_S=0)", extra={"event": "settle_skipped", "settle_s": 0})
        return {"settle_s": 0.0, "elapsed_s": 0.0, "interrupted": False}
    t0 = clock()
    log.info("settle: inicio (%gs para o Litestream sincronizar antes de o servidor sair)", seconds,
             extra={"event": "settle_start", "settle_s": seconds})
    try:
        interrupted = bool(abort.wait(seconds))
    except KeyboardInterrupt:   # Ctrl+C de novo: sai já
        interrupted = True
    elapsed = max(clock() - t0, 0.0)
    log.info("settle: fim (%.3fs%s)", elapsed, ", interrompido por segundo sinal" if interrupted else "",
             extra={"event": "settle_end", "settle_s": seconds, "duration_ms": round(elapsed * 1000, 1),
                    "interrupted": interrupted})
    return {"settle_s": float(seconds), "elapsed_s": elapsed, "interrupted": interrupted}


class SignalController:
    """Primeiro sinal: começa a drenagem (em outra thread). Sinais seguintes: encerram a janela de assentamento.

    O handler roda na thread principal, que pode estar DENTRO de `abort.wait()`: setar o Event dali poderia travar
    no lock interno dele. Por isso o `set()` vai para uma thread curta."""

    def __init__(self, start_drain: Callable[[], None], abort=None, *, spawn: Callable[[Callable[[], None], str], None] | None = None):
        self.start_drain = start_drain
        self.abort = abort if abort is not None else threading.Event()
        self.draining = threading.Event()
        self.signals = 0
        self._spawn = spawn or (lambda fn, name: threading.Thread(target=fn, daemon=True, name=name).start())

    def on_signal(self, signum=None, frame=None) -> None:
        self.signals += 1
        if not self.draining.is_set():
            self.draining.set()
            self._spawn(self.start_drain, "drain")
            return
        log.warning("segundo sinal: encerrando o desligamento sem esperar o settle", extra={"event": "settle_abort"})
        self._spawn(self.abort.set, "settle-abort")
