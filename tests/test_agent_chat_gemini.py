"""Conversa com os agentes pelo Gemini: servidor HTTP falso local (nada de rede real, nada de chave real)."""

import json
import logging
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from studio.agent_chat import FALLBACK, AgentChat, ChatConfig, build_request, default_caller, gemini_payload

SECRET = "AIzaSyFAKE-chat-secret-123456789"
CTX = {"mission": "Copo com alça", "stage": "img_gerando", "status": "work", "needs": []}
OK_BODY = {"candidates": [{"content": {"parts": [{"text": "Tô montando a cena 1 aqui."}]}, "finishReason": "STOP"}],
           "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 40, "thoughtsTokenCount": 10,
                             "cachedContentTokenCount": 200}}


class FakeGemini:
    """Servidor local que imita generateContent. `script` = lista de (status, corpo|None, atraso) consumida em ordem."""

    def __init__(self):
        self.requests: list[dict] = []
        self.script: list[tuple[int, dict | None, float]] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(body)})
                status, payload, delay = outer.script.pop(0) if outer.script else (200, OK_BODY, 0)
                if delay:
                    time.sleep(delay)
                data = json.dumps(payload if payload is not None else {"error": {"message": f"leaked {SECRET}"}}).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass

            def log_message(self, *a):  # silencioso
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def gem(monkeypatch):
    g = FakeGemini()
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    yield g
    g.close()


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    yield c
    c.close()


def chat_for(gem, **cfg):
    base = dict(cooldown_s=0, timeout_s=2.0, gemini_base_url=gem.url)
    base.update(cfg)
    return AgentChat(config=ChatConfig(**base), clock=time.time)


_n = [0]


def say(chat, conn, text="qual luz você vai usar na cena?", user=None, agent="iris"):
    _n[0] += 1
    return chat.reply(conn, user_id=user or f"u{_n[0]}", workspace_id="w1", agent=agent, text=f"{text} {_n[0]}", ctx=CTX)


def row(conn):
    return conn.execute("SELECT source, provider, input_tokens, output_tokens, cache_read_tokens, cost_usd FROM chat_log "
                        "ORDER BY id DESC LIMIT 1").fetchone()


def test_success_request_shape_cost_and_provider(conn, gem):
    r = say(chat_for(gem), conn)
    assert r["ok"] and r["source"] == "llm" and r["reply"] == "Tô montando a cena 1 aqui."
    req = gem.requests[0]
    assert req["path"] == "/v1beta/models/gemini-3.8-flash:generateContent"   # mesmo modelo de texto do projeto
    assert {k.lower(): v for k, v in req["headers"].items()}["x-goog-api-key"] == SECRET and SECRET not in req["path"]   # chave só no cabeçalho
    body = req["body"]
    assert body["generationConfig"]["maxOutputTokens"] == 150 and "Você é Iris" in body["systemInstruction"]["parts"][0]["text"]
    assert body["contents"][-1]["role"] == "user" and "<mensagem_do_usuario>" in body["contents"][-1]["parts"][0]["text"]
    src, prov, inp, out, cache, cost = row(conn)
    assert (src, prov, inp, out, cache) == ("llm", "gemini", 800, 50, 200)   # 1000 de entrada, 200 em cache
    assert cost == pytest.approx((800 * 0.75 + 200 * 0.75 * 0.1 + 50 * 3.75) / 1e6)   # tabela de pricing.LLM_PRICES


def test_history_roles_map_to_gemini(gem):
    req = build_request(ChatConfig(), "iris", CTX, [("oi tudo", "olá"), ("e a luz", "suave")], "e agora")
    roles = [c["role"] for c in gemini_payload(req)["contents"]]
    assert roles == ["user", "model", "user", "model", "user"]
    assert "cache_control" not in json.dumps(req) and "thinking" not in req


def test_price_from_env_overrides_table(conn, gem, monkeypatch):
    monkeypatch.setenv("STUDIO_CHAT_PRICE_IN", "1")
    monkeypatch.setenv("STUDIO_CHAT_PRICE_OUT", "2")
    say(chat_for(gem), conn)   # sem config explícita de preço: vem do env via from_env
    cfg = ChatConfig.from_env()
    assert cfg.prices() == (1.0, 2.0)
    chat = AgentChat(config=ChatConfig(**{**cfg.__dict__, "cooldown_s": 0, "gemini_base_url": gem.url}))
    say(chat, conn)
    assert row(conn)[5] == pytest.approx((800 * 1 + 200 * 0.1 + 50 * 2) / 1e6)


def test_unknown_model_without_price_fails_closed(conn, gem):
    r = say(chat_for(gem, model="gemini-desconhecido"), conn)
    assert r["source"] == "sem_ia" and r["reply"] == FALLBACK["paused"] and gem.requests == []
    assert ChatConfig(model="gemini-desconhecido", price_in_per_mtok=1, price_out_per_mtok=2).prices() == (1, 2)


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_errors_give_friendly_reply_without_leaks(conn, gem, caplog, status):
    gem.script = [(status, None, 0)]
    with caplog.at_level(logging.DEBUG):
        r = say(chat_for(gem), conn)
    assert r["ok"] and r["source"] == "falha" and r["reply"] == FALLBACK["error"]
    assert len(gem.requests) == 1, "nunca re-tenta"
    blob = json.dumps(r) + caplog.text + repr(row(conn))
    assert SECRET not in blob and "leaked" not in blob and "AIza" not in blob
    assert row(conn)[:2] == ("falha", "gemini")


def test_timeout_is_short_and_friendly(conn, gem):
    gem.script = [(200, OK_BODY, 1.5)]
    t0 = time.time()
    r = say(chat_for(gem, timeout_s=0.3), conn)
    assert time.time() - t0 < 1.2 and r["source"] == "falha" and r["reply"] == FALLBACK["error"]


@pytest.mark.parametrize("body", [
    {"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 500}},
    {"candidates": [{"finishReason": "SAFETY"}], "usageMetadata": {"promptTokenCount": 500}},
    {"promptFeedback": {"blockReason": "SAFETY"}, "usageMetadata": {"promptTokenCount": 500}},
    {},
], ids=["vazia", "finish_safety", "prompt_bloqueado", "sem_candidatos"])
def test_empty_or_safety_blocked_gets_friendly_reply(conn, gem, body):
    gem.script = [(200, body, 0)]
    r = say(chat_for(gem), conn)
    assert r["reply"] == FALLBACK["error"] and r["source"] == "llm"
    assert row(conn)[1] == "gemini"


def test_bad_json_and_non_https_base_are_refused(conn, gem, monkeypatch):
    srv_bad = say(chat_for(gem, gemini_base_url="http://example.com"), conn)   # http fora do loopback: chave não sai
    assert srv_bad["source"] == "falha" and gem.requests == []
    gem.script = [(200, ["nao", "objeto"], 0)]
    assert say(chat_for(gem), conn)["reply"] == FALLBACK["error"]


def test_limits_still_apply(conn, gem):
    chat = chat_for(gem, per_day=2, per_hour=8)
    assert say(chat, conn, user="x")["source"] == "llm"
    assert say(chat, conn, user="x")["source"] == "llm"
    r = say(chat, conn, user="x")
    assert r["reason"] == "quota_day" and r["reply"] == FALLBACK["quota_day"] and len(gem.requests) == 2
    c2 = chat_for(gem, cooldown_s=60)
    say(c2, conn, user="y")
    assert say(c2, conn, user="y")["reason"] == "cooldown" and len(gem.requests) == 3
    long = chat.reply(conn, user_id="z", workspace_id="w1", agent="iris", text="a" * 400, ctx=CTX)
    assert long["reason"] == "long"


def test_global_token_cap_and_zero_cap(conn, gem):
    chat = chat_for(gem, global_daily_tokens=850)   # uma chamada gasta 850 (800 + 50)
    assert say(chat, conn)["source"] == "llm"
    assert say(chat, conn)["source"] == "sem_ia" and len(gem.requests) == 1
    zero = chat_for(gem, global_daily_tokens=0)
    assert say(zero, conn)["source"] == "sem_ia" and len(gem.requests) == 1


def test_workspace_zero_cap_blocks(gem, settings):
    from studio.accounts import Accounts
    from studio.db import Database
    db = Database(settings.db_path)
    _, wid = Accounts(db).create_user("chat-teto@example.com", "senha-forte-123")   # conta nova: teto 0
    chat = chat_for(gem)
    ask = lambda: chat.reply(db.conn, user_id=f"uz{time.perf_counter_ns()}", workspace_id=wid, agent="iris",
                             text="qual a paleta da cena?", ctx=CTX)
    assert ask()["source"] == "sem_ia" and gem.requests == []
    Accounts(db).set_workspace(wid, monthly_cap_usd=1)
    assert ask()["source"] == "llm" and len(gem.requests) == 1


def test_kill_switch_and_disabled_use_ready_answer_only(conn, gem, monkeypatch):
    assert say(chat_for(gem, enabled=False), conn)["reply"] == FALLBACK["off"]
    monkeypatch.setenv("STUDIO_KILL_SWITCH", "1")
    assert say(chat_for(gem), conn)["source"] == "sem_ia" and gem.requests == []


def test_no_key_means_ready_answer(conn, gem, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    r = say(chat_for(gem), conn)
    assert r["source"] == "sem_ia" and r["reply"] == FALLBACK["off"] and r["ai"] is False


def test_provider_selection_and_anthropic_kept(monkeypatch):
    assert ChatConfig.from_env().resolved_provider == "gemini"
    monkeypatch.setenv("STUDIO_CHAT_PROVIDER", "anthropic")
    cfg = ChatConfig.from_env()
    assert cfg.resolved_provider == "anthropic" and cfg.resolved_model == "claude-haiku-5-5" and cfg.prices() == (0.10, 0.50)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert default_caller(cfg) is None
    monkeypatch.setenv("STUDIO_CHAT_PROVIDER", "lixo")
    assert ChatConfig.from_env().resolved_provider == "gemini"
    monkeypatch.setenv("STUDIO_CHAT_PROVIDER", "gemini")
    monkeypatch.setenv("STUDIO_CHAT_MODEL", "gemini-3.5-flash-lite")
    assert ChatConfig.from_env().prices() == (0.30, 2.50)


def test_metrics_report_provider_gemini(gem, settings):
    from studio.db import Database
    from studio.metrics import internal_metrics
    db = Database(settings.db_path)
    say(chat_for(gem), db.conn)
    chat_rows = [r for r in internal_metrics(db, 30)["outside_productions"] if r["key"].startswith("chat")]
    assert chat_rows and chat_rows[0]["provider"] == "gemini" and chat_rows[0]["calls"] == 1 and chat_rows[0]["usd"] > 0
