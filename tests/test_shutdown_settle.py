"""Janela de assentamento (settle) do desligamento e orçamento de tempo até o SIGKILL (studio.shutdown)."""

from __future__ import annotations

import json
import logging
import threading
import time
from types import SimpleNamespace

import pytest

from studio import shutdown as sd
from studio.logs import JsonFormatter
from studio.runtime import ServerConfig
from studio.web import server as srv


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class FakeAbort:
    """`wait(t)` avança o relógio falso em `t` (ou só até `fire_at`, se o "segundo sinal" chega antes)."""

    def __init__(self, clock: FakeClock, fire_at: float | None = None):
        self.clock, self.fire_at, self.waits = clock, fire_at, []

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        if self.fire_at is not None and self.fire_at < timeout:
            self.clock.t += self.fire_at
            return True
        self.clock.t += timeout
        return False


def _events(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", None)]


# ------------------------------------------------------------------ settle
def test_settle_waits_the_full_window_on_a_fake_clock_and_logs_start_and_end(caplog):
    caplog.set_level(logging.INFO, logger="studio")
    clock = FakeClock()
    abort = FakeAbort(clock)
    out = sd.settle(3.0, abort, clock=clock)
    assert abort.waits == [3.0]
    assert out == {"settle_s": 3.0, "elapsed_s": 3.0, "interrupted": False}
    ev = _events(caplog)
    assert [r.event for r in ev] == ["settle_start", "settle_end"]
    assert ev[0].settle_s == 3.0 and ev[1].settle_s == 3.0
    assert ev[1].duration_ms == 3000.0 and ev[1].interrupted is False


def test_settle_zero_disables_the_window(caplog):
    caplog.set_level(logging.INFO, logger="studio")
    abort = FakeAbort(FakeClock())
    out = sd.settle(0.0, abort)
    assert abort.waits == []   # não espera nada
    assert out == {"settle_s": 0.0, "elapsed_s": 0.0, "interrupted": False}
    assert [r.event for r in _events(caplog)] == ["settle_skipped"]


def test_settle_interrupted_by_second_signal_reports_partial_duration(caplog):
    caplog.set_level(logging.INFO, logger="studio")
    clock = FakeClock()
    out = sd.settle(5.0, FakeAbort(clock, fire_at=1.25), clock=clock)
    assert out["interrupted"] is True and out["elapsed_s"] == 1.25
    end = _events(caplog)[-1]
    assert end.event == "settle_end" and end.interrupted is True and end.duration_ms == 1250.0


def test_settle_keyboard_interrupt_during_wait_ends_it():
    class CtrlC:
        def wait(self, timeout):
            raise KeyboardInterrupt

    assert sd.settle(3.0, CtrlC(), clock=FakeClock())["interrupted"] is True


def test_second_signal_aborts_a_real_settle_without_hanging():
    drained = threading.Event()
    ctl = sd.SignalController(drained.set)
    ctl.on_signal()                      # 1º sinal: drenagem em outra thread
    assert drained.wait(2) and ctl.draining.is_set()
    result: dict = {}
    t = threading.Thread(target=lambda: result.update(sd.settle(10.0, ctl.abort)))
    t0 = time.monotonic()
    t.start()
    time.sleep(0.2)
    ctl.on_signal()                      # 2º sinal: encerra a janela
    t.join(3)
    assert not t.is_alive(), "settle travou depois do segundo sinal"
    assert result["interrupted"] is True and time.monotonic() - t0 < 3
    assert ctl.signals == 2


def test_signal_handler_never_sets_the_event_inline():
    """O handler roda na thread principal, possivelmente DENTRO de abort.wait(): o set() vai para outra thread."""
    spawned: list[str] = []
    ctl = sd.SignalController(lambda: None, spawn=lambda fn, name: spawned.append(name))
    ctl.on_signal()
    ctl.on_signal()
    ctl.on_signal()
    assert spawned == ["drain", "settle-abort", "settle-abort"]   # drenagem uma vez só
    assert not ctl.abort.is_set()


def test_signal_during_settle_in_the_main_thread_does_not_deadlock():
    """Simula o sinal chegando enquanto a thread principal está em abort.wait(): o handler é chamado de outra
    thread aqui, mas o caminho (spawn + set) é o mesmo."""
    ctl = sd.SignalController(lambda: None)
    ctl.draining.set()                                  # drenagem já feita
    threading.Timer(0.1, ctl.on_signal).start()
    t0 = time.monotonic()
    out = sd.settle(10.0, ctl.abort)
    assert out["interrupted"] is True and time.monotonic() - t0 < 3


# ------------------------------------------------------------------ valores de STUDIO_SHUTDOWN_SETTLE_S
@pytest.mark.parametrize("raw,expected", [(None, 3.0), ("", 3.0), ("  ", 3.0), ("0", 0.0), ("15", 15.0), ("2.5", 2.5)])
def test_parse_settle_accepts_0_to_15(raw, expected):
    assert sd.parse_settle(raw) == expected


@pytest.mark.parametrize("raw", ["16", "15.01", "-1", "-0.1", "abc", "3s", "nan", "inf"])
def test_parse_settle_rejects_invalid(raw):
    with pytest.raises(ValueError, match="STUDIO_SHUTDOWN_SETTLE_S"):
        sd.parse_settle(raw)


def test_server_config_reads_settle_and_platform_deadline():
    c = ServerConfig.from_env({})
    assert (c.shutdown_grace_s, c.shutdown_settle_s, c.stop_grace_s) == (25.0, 3.0, 40.0)
    c = ServerConfig.from_env({"STUDIO_SHUTDOWN_SETTLE_S": "0", "STUDIO_STOP_GRACE_S": "60"})
    assert (c.shutdown_settle_s, c.stop_grace_s) == (0.0, 60.0)
    for bad in ({"STUDIO_SHUTDOWN_SETTLE_S": "20"}, {"STUDIO_STOP_GRACE_S": "0"}, {"STUDIO_SHUTDOWN_GRACE_S": "-1"},
                {"STUDIO_SHUTDOWN_GRACE_S": "x"}):
        with pytest.raises(ValueError):
            ServerConfig.from_env(bad)


# ------------------------------------------------------------------ orçamento de tempo
def test_budget_defaults_fit_the_compose_40s():
    b = sd.budget(25, 3, 40)
    assert (b.grace_s, b.http_close_s, b.settle_s, b.litestream_close_s) == (25, sd.HTTP_CLOSE_S, 3, sd.LITESTREAM_CLOSE_MARGIN_S)
    assert b.total_s == 35 and b.ok
    assert sd.minimum_platform_s(25, 3) == 35
    assert sd.minimum_platform_s(25, 0) == 32
    assert sd.minimum_platform_s(25, 15) == 47
    assert sd.budget_error(25, 3, 40) is None
    assert ServerConfig.from_env({}).shutdown_budget_error() is None


def test_budget_boundary_is_inclusive():
    assert sd.budget_error(30, 3, 40) is None          # 30 + 2 + 3 + 5 = 40
    msg = sd.budget_error(31, 3, 40)                    # 41 > 40
    assert msg and "41" in msg and "STUDIO_STOP_GRACE_S" in msg and "stop_grace_period" in msg


def test_budget_refuses_large_settle_or_short_platform():
    assert ServerConfig.from_env({"STUDIO_SHUTDOWN_SETTLE_S": "15"}).shutdown_budget_error()   # 47 > 40
    assert ServerConfig.from_env({"STUDIO_STOP_GRACE_S": "34"}).shutdown_budget_error()        # 35 > 34
    assert ServerConfig.from_env({"STUDIO_SHUTDOWN_SETTLE_S": "15", "STUDIO_STOP_GRACE_S": "47"}).shutdown_budget_error() is None


@pytest.mark.parametrize("env,match", [({"STUDIO_SHUTDOWN_SETTLE_S": "99"}, "STUDIO_SHUTDOWN_SETTLE_S"),
                                       ({"STUDIO_SHUTDOWN_GRACE_S": "36"}, "não cabe no prazo da plataforma")])
def test_serve_refuses_to_start_with_bad_shutdown_config(monkeypatch, env, match):
    for k in ("STUDIO_ENV", "STUDIO_SHUTDOWN_SETTLE_S", "STUDIO_SHUTDOWN_GRACE_S", "STUDIO_STOP_GRACE_S"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(SystemExit, match=match):
        srv.serve(port=0, open_browser=False)


# ------------------------------------------------------------------ fim da drenagem
def test_inflight_waits_for_the_last_request():
    inf = sd.Inflight()
    inf.__enter__()
    assert inf.count == 1
    assert inf.wait_idle(0.05) == 1                     # ainda em andamento
    threading.Timer(0.1, inf.__exit__, args=(None, None, None)).start()
    assert inf.wait_idle(2) == 0


def test_finish_shutdown_drains_then_settles(caplog):
    caplog.set_level(logging.INFO, logger="studio")
    clock = FakeClock()
    stopped = threading.Thread(target=lambda: None)
    stopped.start()
    stopped.join()
    app = SimpleNamespace(inflight=sd.Inflight(), lock=threading.Lock(), runs={},
                          cfg=SimpleNamespace(shutdown_settle_s=3.0))
    out = srv._finish_shutdown(app, stopped, FakeAbort(clock), clock=clock)
    assert out["settle_s"] == 3.0 and out["elapsed_s"] == 3.0
    ev = _events(caplog)
    assert [r.event for r in ev] == ["drained", "settle_start", "settle_end"]
    assert ev[0].levelno == logging.INFO and "checkpoint periodico parado" in ev[0].getMessage()


def test_finish_shutdown_warns_when_something_is_still_running(caplog):
    caplog.set_level(logging.INFO, logger="studio")
    busy = threading.Event()
    run = threading.Thread(target=busy.wait, daemon=True)
    run.start()
    app = SimpleNamespace(inflight=sd.Inflight(), lock=threading.Lock(), runs={"p1": run},
                          cfg=SimpleNamespace(shutdown_settle_s=0.0))
    try:
        srv._finish_shutdown(app, None, FakeAbort(FakeClock()))
    finally:
        busy.set()
    drained = next(r for r in _events(caplog) if r.event == "drained")
    assert drained.levelno == logging.WARNING and "producoes ainda em chamada=1" in drained.getMessage()


def test_json_log_carries_settle_fields():
    rec = logging.LogRecord("studio.shutdown", logging.INFO, __file__, 1, "settle: fim", None, None)
    rec.event, rec.settle_s, rec.duration_ms, rec.interrupted = "settle_end", 3.0, 3001.2, False
    out = json.loads(JsonFormatter().format(rec))
    assert (out["event"], out["settle_s"], out["duration_ms"], out["interrupted"]) == ("settle_end", 3.0, 3001.2, False)
