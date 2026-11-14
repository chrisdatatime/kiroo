"""Cliente e gerador do motor fal.ai com httpx.MockTransport: nenhuma rede real, nenhum custo."""

from __future__ import annotations

import json

import httpx
import pytest

from studio import fal_contract as fc, paid_gate
from studio.config import PROJECT_ROOT
from studio.providers.base import (OpState, PermanentError, ProviderBillingError, TransientError, WorkflowRequest)
from studio.providers.fal import FalClient, FalWorkflowGenerator, UncertainSubmit, billing_total

from .conftest import fal_host_blocked
from .fal_fixtures import BASE, sample_contract, sample_result

KEY = "fal-FAKE-key-0123456789abcdef"
WF = "workflows/acme/escuro"
META = {"workflow": WF, "style": "dark"}


class Fake:
    """Servidor falso da fal.ai: registra as chamadas e responde conforme o roteiro."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.status = {"status": "COMPLETED"}
        self.result = sample_result()
        self.submit_resp = None
        self.fail: dict = {}
        self.headers: dict = {}
        self.bodies: dict = {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        key = f"{req.method} {req.url.host}{req.url.path}"
        self.calls.append((req.method, str(req.url)))
        self.headers[key] = dict(req.headers)
        self.bodies[key] = req.content
        for pat, resp in self.fail.items():
            if pat in key:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        if req.url.path == "/storage/upload/initiate":
            return httpx.Response(200, json={"file_url": "https://v3.fal.media/files/up/foto.jpg",
                                             "upload_url": "https://v3.fal.media/upload/xyz"})
        if req.method == "PUT" and "/upload/" in req.url.path:
            return httpx.Response(200)
        if req.method == "POST" and req.url.host == "queue.fal.run":
            return httpx.Response(200, json=self.submit_resp or {
                "request_id": "req-1", "status_url": f"https://queue.fal.run/{WF}/requests/req-1/status",
                "response_url": f"https://queue.fal.run/{WF}/requests/req-1",
                "cancel_url": f"https://queue.fal.run/{WF}/requests/req-1/cancel"})
        if req.url.path.endswith("/status"):
            return httpx.Response(200, json=self.status)
        if req.method == "PUT" and req.url.path.endswith("/cancel"):
            return httpx.Response(202, json={"status": "CANCELLATION_REQUESTED"})
        if req.url.host == "api.fal.ai":
            return httpx.Response(200, json={"items": [{"cost_total": 1.25}, {"cost_total": 0.75}]})
        if req.url.host == "v3.fal.media":
            return httpx.Response(200, content=b"bytes-do-arquivo")
        return httpx.Response(200, json=self.result)


@pytest.fixture
def fake():
    return Fake()


@pytest.fixture
def gen(fake):
    client = FalClient(KEY, "bill-FAKE-0123456789", transport=httpx.MockTransport(fake))
    return FalWorkflowGenerator(client, sample_contract(), {"dark": WF, "light": "workflows/acme/claro"},
                                start_timeout_s=120, estimator=lambda style: (2.0, "teste"))


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "foto.jpg"
    p.write_bytes(b"\xff\xd8\xff" + b"0" * 100)
    return p


def req(photo, style="dark"):
    return WorkflowRequest(style=style, image_path=photo)


# ---------------------------------------------------------------- envio
def test_submit_uploads_photo_then_submits_with_contract_input(gen, fake, photo):
    info = gen.submit_full(req(photo))
    assert info.request_id == "req-1" and info.meta["workflow"] == WF
    assert info.meta["status_url"].endswith("/requests/req-1/status")
    assert [m for m, _ in fake.calls] == ["POST", "PUT", "POST"]       # iniciar upload, enviar, executar o workflow
    k = f"POST queue.fal.run/{WF}"
    assert json.loads(fake.bodies[k]) == {"image_url": "https://v3.fal.media/files/up/foto.jpg"}
    h = fake.headers[k]
    assert h["authorization"] == f"Key {KEY}"
    assert h["x-fal-workflow-envelope"] == "true" and h["x-fal-no-retry"] == "1"
    assert h["x-fal-request-start-timeout"] == "120"
    init = fake.headers["POST rest.alpha.fal.ai/storage/upload/initiate"]
    assert "expiration_duration_seconds" in init["x-fal-object-lifecycle-preference"]


def test_chosen_workflow_follows_style(gen, fake, photo):
    gen.submit_full(req(photo, "light"))
    assert any("queue.fal.run/workflows/acme/claro" in u for _, u in fake.calls)


def test_kill_switch_blocks_before_any_network(gen, fake, photo, monkeypatch):
    monkeypatch.setenv("STUDIO_KILL_SWITCH", "1")
    with pytest.raises(paid_gate.PaidCallsBlocked):
        gen.submit_full(req(photo))
    assert fake.calls == []


CLARO = "workflows/acme/claro"


def real_gen(fake, **kw):
    real = fc.load_contract(PROJECT_ROOT / "profiles")
    return FalWorkflowGenerator(FalClient(KEY, transport=httpx.MockTransport(fake)), real, {"light": CLARO}, **kw)


def test_real_submit_is_allowed_while_recover_is_pending_and_always_sends_the_envelope_header(fake, photo):
    g = real_gen(fake)
    assert fc.recover_pending(g.contract, "light")                         # recover.hero e request_id por no seguem pendentes
    info = g.submit_full(req(photo, "light"))
    assert info.request_id == "req-1" and info.meta["workflow"] == CLARO
    k = f"POST queue.fal.run/{CLARO}"
    assert json.loads(fake.bodies[k]) == {"image_url": "https://v3.fal.media/files/up/foto.jpg"}      # so image_url
    assert fake.headers[k]["x-fal-workflow-envelope"] == "true"
    r = real_gen(fake)
    r.poll("req-1", {"workflow": CLARO, "style": "light"}, "light")
    get_result = [h for key, h in fake.headers.items() if key.startswith("GET queue.fal.run") and not key.endswith("/status")]
    assert get_result and all(h["x-fal-workflow-envelope"] == "true" for h in get_result)          # tambem ao buscar o resultado


def test_pending_in_the_send_path_still_refuses_the_real_submit(fake, photo):
    g = real_gen(fake)
    g.contract["styles"]["light"]["pending"] = ["output.video: A CONFIRMAR"]          # pendencia de ENVIO (nao de recuperacao)
    with pytest.raises(PermanentError, match="A CONFIRMAR"):
        g.submit_full(req(photo, "light"))
    assert fake.calls == []


def test_photo_recovery_is_refused_while_recover_is_pending_and_makes_no_call(fake):
    g = real_gen(fake)
    art = fc.Artifact(kind="image", recover={"endpoint": "fal-ai/img/a", "request_id": "r-hero", "path": "images.0.url"})
    with pytest.raises(PermanentError, match="recuperacao de foto"):
        g.recover_artifact(art, "light")
    assert fake.calls == []                                                           # nenhum GET no no


def test_poll_returns_the_raw_envelope_for_result_json(gen, fake):
    r = gen.poll("req-1", META)
    assert r.raw == fake.result and "nodes" in r.raw and "output" in r.raw


def test_missing_workflow_id_is_a_clear_error(fake, photo):
    g = FalWorkflowGenerator(FalClient(KEY, transport=httpx.MockTransport(fake)), sample_contract(), {"dark": None})
    with pytest.raises(PermanentError, match="WORKFLOW_ID_DARK"):
        g.submit_full(req(photo))


# ---------------------------------------------------------------- erros de transporte
@pytest.mark.parametrize("status,exc", [(429, TransientError), (500, TransientError), (503, TransientError),
                                        (400, PermanentError), (404, PermanentError), (422, PermanentError),
                                        (402, ProviderBillingError)])
def test_http_status_mapping_on_status_call(gen, fake, status, exc):
    fake.fail["/status"] = httpx.Response(status, text="falha")
    with pytest.raises(exc):
        gen.poll("req-1", META)


def test_submit_http_errors_are_not_uncertain(gen, fake, photo):
    fake.fail["POST queue.fal.run"] = httpx.Response(503, text="indisponivel")
    with pytest.raises(TransientError):
        gen.submit_full(req(photo))


def test_submit_timeout_after_sending_is_uncertain_never_retried_silently(gen, fake, photo):
    fake.fail["POST queue.fal.run"] = httpx.ReadTimeout("lento")
    with pytest.raises(UncertainSubmit):
        gen.submit_full(req(photo))


def test_submit_connect_error_is_safe_to_retry(gen, fake, photo):
    fake.fail["POST queue.fal.run"] = httpx.ConnectError("sem rede")
    with pytest.raises(TransientError):
        gen.submit_full(req(photo))


def test_submit_response_without_request_id_is_uncertain(gen, fake, photo):
    fake.submit_resp = {"oops": 1}
    with pytest.raises(UncertainSubmit):
        gen.submit_full(req(photo))


def test_status_timeout_is_transient(gen, fake):
    fake.fail["/status"] = httpx.ReadTimeout("lento")
    with pytest.raises(TransientError):
        gen.poll("req-1", META)


# ---------------------------------------------------------------- poll
@pytest.mark.parametrize("state", ["IN_QUEUE", "IN_PROGRESS"])
def test_poll_running(gen, fake, state):
    fake.status = {"status": state, "queue_position": 2}
    assert gen.poll("req-1", META).state == OpState.RUNNING


def test_poll_completed_with_error_is_a_failure(gen, fake):
    fake.status = {"status": "COMPLETED", "error": "no falhou", "error_type": "runner_error"}
    r = gen.poll("req-1", META)
    assert r.state == OpState.FAILED and r.permanent and "no falhou" in r.error


def test_poll_completed_server_error_is_not_permanent(gen, fake):
    fake.status = {"status": "COMPLETED", "error": "x", "error_type": "server_error"}
    assert gen.poll("req-1", META).permanent is False


def test_poll_unexpected_status_fails(gen, fake):
    fake.status = {"status": "???"}
    assert gen.poll("req-1", META).state == OpState.FAILED


def test_poll_success_returns_canonical_package(gen, fake):
    fake.status = {"status": "COMPLETED", "metrics": {"inference_time": 41.5}}
    r = gen.poll("req-1", META)
    assert r.state == OpState.SUCCEEDED and r.confirmed_cost_usd is None
    pkg = r.package
    assert pkg.failure_kind() is None and pkg.missing() == []
    assert pkg.video.url.endswith("/final.mp4") and pkg.hero.url.endswith("/hero.jpg")
    assert pkg.title.startswith("Copo") and pkg.caption.startswith("Mantem")
    assert pkg.nodes["n_hero"] == {"endpoint": "fal-ai/img/a", "request_id": "r-hero"}
    assert r.usage["inference_time"] == 41.5


def test_poll_derives_urls_when_meta_has_only_workflow(gen, fake):
    gen.poll("req-9", META)
    assert any(u.endswith(f"{WF}/requests/req-9/status") for _, u in fake.calls)


def test_cancel_uses_the_cancel_url(gen, fake):
    gen.cancel("req-1", {"cancel_url": f"https://queue.fal.run/{WF}/requests/req-1/cancel"})
    assert fake.calls[-1][0] == "PUT" and fake.calls[-1][1].endswith("/cancel")


# ---------------------------------------------------------------- download, recuperacao, custo
def test_download_only_from_allowed_https_hosts(gen):
    assert gen.client.download(f"{BASE}/a.jpg") == b"bytes-do-arquivo"
    for bad in ("http://v3.fal.media/a.jpg", "https://evil.example.com/a.jpg", "https://169.254.169.254/x",
                "https://fal.media.evil.com/a.jpg"):
        with pytest.raises(PermanentError):
            gen.client.download(bad)


def test_recover_fetches_only_the_node_output_not_the_workflow(gen, fake):
    fake.result = {"image": {"url": f"{BASE}/recuperada.jpg"}}
    art = fc.Artifact(kind="image",
                      recover={"endpoint": "fal-ai/img/a", "request_id": "r-hero", "path": "image.url"})
    got = gen.recover_artifact(art)
    assert got.url.endswith("/recuperada.jpg")
    assert fake.calls[-1] == ("GET", "https://queue.fal.run/fal-ai/img/a/requests/r-hero")
    assert not any(m == "POST" and "queue.fal.run" in u for m, u in fake.calls)     # nenhum novo submit


def test_recover_without_node_info_returns_none(gen):
    assert gen.recover_artifact(fc.Artifact(kind="image")) is None


def test_billing_needs_its_own_key(fake):
    g = FalWorkflowGenerator(FalClient(KEY, None, transport=httpx.MockTransport(fake)), sample_contract(), {"dark": WF})
    with pytest.raises(PermanentError, match="FAL_BILLING_KEY"):
        g.reconcile_cost(["req-1"])


def test_billing_sums_cost_total(gen, fake):
    assert gen.reconcile_cost(["req-1"]) == 2.0
    assert fake.headers["GET api.fal.ai/v1/models/billing-events"]["authorization"] == "Key bill-FAKE-0123456789"
    assert billing_total({"items": []}) is None


# ---------------------------------------------------------------- segredos e rede
def test_fal_key_never_appears_in_errors(gen, fake, monkeypatch):
    monkeypatch.setenv("FAL_KEY", KEY)
    fake.fail["/status"] = httpx.Response(401, text=f"chave invalida {KEY}")
    with pytest.raises(PermanentError) as e:
        gen.poll("req-1", META)
    assert KEY not in str(e.value) and "***" in str(e.value)


def test_fal_keys_are_known_secrets(monkeypatch):
    from studio.config import secret_values
    monkeypatch.setenv("FAL_KEY", KEY)
    monkeypatch.setenv("FAL_BILLING_KEY", "bill-FAKE-0123456789")
    assert KEY in secret_values() and "bill-FAKE-0123456789" in secret_values()


def test_real_network_to_fal_is_blocked_in_tests():
    import socket
    assert fal_host_blocked("queue.fal.run") and fal_host_blocked("v3.fal.media") and not fal_host_blocked("127.0.0.1")
    for host in ("queue.fal.run", "api.fal.ai", "rest.alpha.fal.ai", "v3.fal.media"):
        with pytest.raises(OSError, match="bloqueada"):
            socket.create_connection((host, 443), timeout=1)
        with pytest.raises(OSError, match="bloqueada"):
            socket.getaddrinfo(host, 443)
