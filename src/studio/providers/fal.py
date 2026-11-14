"""Motor fal.ai: cliente REST fino (httpx) e gerador de workflows.

O Kiroo NAO reconstroi as etapas generativas: ele envia a foto, acompanha a execucao do workflow e recupera os
artefatos. Aqui so ha transporte e mapeamento de erros; o mapeamento das chaves de saida vive em fal_contract.py.

Fatos da documentacao oficial (fal.ai/docs, lida em 13/11/2026):
  * submit:  POST https://queue.fal.run/<endpoint do workflow>  (Authorization: Key ...), devolve request_id,
    status_url, response_url e cancel_url. Usamos SEMPRE as URLs devolvidas (a doc avisa que montar com o caminho do
    endpoint pode dar 405).
  * status:  IN_QUEUE | IN_PROGRESS | COMPLETED. Falha e cancelamento tambem chegam como COMPLETED, com `error`.
  * workflows: o resultado traz so a saida final; com X-Fal-Workflow-Envelope: true traz tambem `nodes`.
  * custo real NAO vem na resposta: so na Billing Events API (chave com escopo billing).
  * nao ha chave de idempotencia: quem evita duplicar e o Kiroo (uma tentativa gravada ANTES do envio).
SUPOSICOES (marcadas A CONFIRMAR): o fluxo de upload (initiate + PUT) segue o do cliente oficial, mas a doc nao traz
endpoint REST de upload; o header de lifecycle no initiate tambem e suposicao.
"""

from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .. import fal_contract, paid_gate
from ..logs import redact
from .base import OpResult, OpState, PermanentError, ProviderBillingError, TransientError, WorkflowRequest

PROVIDER = "fal-workflow"
QUEUE_URL = "https://queue.fal.run"
REST_UPLOAD_URL = "https://rest.alpha.fal.ai"      # A CONFIRMAR: fluxo de upload do cliente oficial
API_URL = "https://api.fal.ai"
DEFAULT_DOWNLOAD_HOSTS = ("fal.media", "fal.ai", "fal.run")
MAX_DOWNLOAD_BYTES = 600 * 1024 * 1024
LIFECYCLE_HEADER = "X-Fal-Object-Lifecycle-Preference"
ENVELOPE_HEADER = "X-Fal-Workflow-Envelope"
START_TIMEOUT_HEADER = "X-Fal-Request-Start-Timeout"
NO_RETRY_HEADER = "X-Fal-No-Retry"


class UncertainSubmit(Exception):
    """O envio pode ter sido aceito pela fal.ai mesmo sem resposta (timeout depois de enviar). NUNCA repetir sozinho:
    sem chave de idempotencia, repetir poderia executar e cobrar duas vezes. Vai para revisao do administrador."""


@dataclass
class SubmitInfo:
    request_id: str
    meta: dict          # workflow, status_url, response_url, cancel_url


def _httpx():
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover
        raise PermanentError("pacote httpx nao instalado: pip install -e .[real]") from exc
    return httpx


def _msg(exc_or_text) -> str:
    return redact(str(exc_or_text))[:400]


class FalClient:
    """Transporte HTTP. `transport` permite testar com httpx.MockTransport (nenhuma rede real em teste)."""

    def __init__(self, api_key: str, billing_key: str | None = None, *, transport=None, timeout_s: float = 30.0,
                 download_hosts: tuple[str, ...] = DEFAULT_DOWNLOAD_HOSTS):
        self._key, self._billing_key = api_key, billing_key
        self._transport = transport
        self._timeout = timeout_s
        self.download_hosts = download_hosts
        self._c = None

    @property
    def http(self):
        if self._c is None:
            self._c = _httpx().Client(transport=self._transport, timeout=self._timeout, follow_redirects=False)
        return self._c

    def _auth(self, billing: bool = False) -> dict:
        key = self._billing_key if billing else self._key
        return {"Authorization": f"Key {key}"}

    # ------------------------------------------------------------------ erros
    @staticmethod
    def raise_for(resp, what: str) -> None:
        code = resp.status_code
        if code < 400:
            return
        text = _msg(resp.text)
        if code == 402 or "insufficient" in text.lower() and "balance" in text.lower() or "exhausted balance" in text.lower():
            raise ProviderBillingError(f"{what}: conta da fal.ai sem saldo ({code})")
        if code in (408, 425, 429) or code >= 500:
            raise TransientError(f"{what}: HTTP {code} {text[:200]}")
        raise PermanentError(f"{what}: HTTP {code} {text[:200]}")

    def _call(self, method: str, url: str, what: str, *, sent_is_uncertain: bool = False, **kw):
        httpx = _httpx()
        try:
            resp = self.http.request(method, url, **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:   # nada saiu: pode repetir
            raise TransientError(f"{what}: sem conexao ({type(exc).__name__})") from None
        except httpx.TimeoutException as exc:                                           # saiu e nao respondeu
            if sent_is_uncertain:
                raise UncertainSubmit(f"{what}: sem resposta ({type(exc).__name__})") from None
            raise TransientError(f"{what}: tempo esgotado ({type(exc).__name__})") from None
        except httpx.TransportError as exc:
            if sent_is_uncertain:
                raise UncertainSubmit(f"{what}: conexao interrompida ({type(exc).__name__})") from None
            raise TransientError(f"{what}: rede ({type(exc).__name__})") from None
        self.raise_for(resp, what)
        return resp

    # ------------------------------------------------------------------ API
    def upload(self, path: Path, *, lifecycle_s: int | None = None) -> str:
        """Envia a foto para a CDN da fal.ai e devolve a URL. A CONFIRMAR: fluxo initiate + PUT do cliente oficial."""
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        headers = {**self._auth(), "Content-Type": "application/json"}
        if lifecycle_s:
            headers[LIFECYCLE_HEADER] = json.dumps({"expiration_duration_seconds": int(lifecycle_s)})
        r = self._call("POST", f"{REST_UPLOAD_URL}/storage/upload/initiate?storage_type=fal-cdn-v3", "upload (iniciar)",
                       headers=headers, json={"content_type": ctype, "file_name": path.name})
        try:
            info = r.json()
            file_url, upload_url = info["file_url"], info["upload_url"]
        except (ValueError, KeyError, TypeError):
            raise PermanentError("upload: resposta inesperada da fal.ai") from None
        self._call("PUT", upload_url, "upload (enviar)", content=path.read_bytes(), headers={"Content-Type": ctype})
        return file_url

    def submit(self, workflow_id: str, payload: dict, *, start_timeout_s: float | None = None) -> SubmitInfo:
        headers = {**self._auth(), ENVELOPE_HEADER: "true", NO_RETRY_HEADER: "1"}
        if start_timeout_s:
            headers[START_TIMEOUT_HEADER] = f"{start_timeout_s:g}"
        r = self._call("POST", f"{QUEUE_URL}/{workflow_id.strip('/')}", "envio do workflow", sent_is_uncertain=True,
                       headers=headers, json=payload)
        try:
            d = r.json()
            rid = str(d["request_id"])
        except (ValueError, KeyError, TypeError):
            raise UncertainSubmit("envio do workflow: resposta sem request_id") from None
        return SubmitInfo(rid, {"workflow": workflow_id, "status_url": d.get("status_url"),
                                "response_url": d.get("response_url"), "cancel_url": d.get("cancel_url")})

    def status(self, status_url: str) -> dict:
        return self._json(self._call("GET", status_url, "consulta de status", headers=self._auth()), "status")

    def result(self, response_url: str) -> dict:
        return self._json(self._call("GET", response_url, "resultado do workflow",
                                     headers={**self._auth(), ENVELOPE_HEADER: "true"}), "resultado")

    def node_result(self, endpoint: str, request_id: str) -> dict:
        return self.result(f"{QUEUE_URL}/{endpoint.strip('/')}/requests/{request_id}")

    def cancel(self, cancel_url: str) -> None:
        self._call("PUT", cancel_url, "cancelamento", headers=self._auth())

    def billing(self, request_ids: list[str]) -> dict:
        """Custo real (US$) por request_id. Exige FAL_BILLING_KEY (a chave comum nao tem escopo de billing)."""
        if not self._billing_key:
            raise PermanentError("FAL_BILLING_KEY nao definida: custo real indisponivel")
        r = self._call("GET", f"{API_URL}/v1/models/billing-events", "billing-events", headers=self._auth(billing=True),
                       params=[("request_id", i) for i in request_ids[:50]])
        return self._json(r, "billing-events")

    def download(self, url: str, *, max_bytes: int = MAX_DOWNLOAD_BYTES) -> bytes:
        u = urlparse(url)
        host = (u.hostname or "").lower()
        if u.scheme != "https" or not any(host == h or host.endswith("." + h) for h in self.download_hosts):
            raise PermanentError(f"download recusado: endereco fora da lista permitida ({host or 'invalido'})")
        r = self._call("GET", url, "download do artefato")          # arquivo publico da CDN: sem a chave da fal
        if len(r.content) > max_bytes:
            raise PermanentError("download recusado: arquivo grande demais")
        return r.content

    @staticmethod
    def _json(resp, what: str) -> dict:
        try:
            d = resp.json()
        except ValueError:
            raise PermanentError(f"{what}: resposta nao e JSON") from None
        if not isinstance(d, dict):
            raise PermanentError(f"{what}: resposta inesperada")
        return d


def billing_total(billing_json: dict) -> float | None:
    """Soma cost_total (US$) dos eventos do billing-events. None se nao houver eventos."""
    items = billing_json.get("items") or billing_json.get("events") or billing_json.get("billing_events") or []
    vals = [i.get("cost_total") for i in items if isinstance(i, dict) and isinstance(i.get("cost_total"), (int, float))]
    return round(float(sum(vals)), 6) if vals else None


class FalWorkflowGenerator:
    """submit/poll de um workflow (um por estilo). Gera o pacote canonico (WorkflowPackage), sem baixar arquivos."""

    provider = PROVIDER
    simulated = False

    def __init__(self, client: FalClient, contract: dict, workflow_ids: dict[str, str | None], *,
                 start_timeout_s: float | None = None, upload_lifecycle_s: int | None = 3600, estimator=None):
        self.client, self.contract = client, contract
        self.workflow_ids = workflow_ids
        self.start_timeout_s = start_timeout_s
        self.upload_lifecycle_s = upload_lifecycle_s
        self._estimator = estimator
        self.model = "fal-workflow"
        self.submit_count = 0

    # ---------------------------------------------------------------- guardas
    def _workflow(self, style: str) -> str:
        wid = self.workflow_ids.get(style)
        if not wid:
            raise PermanentError(f"workflow do estilo {style} nao configurado (WORKFLOW_ID_"
                                 f"{'DARK' if style == 'dark' else 'LIGHT'})")
        return wid

    def _guard(self, style: str) -> str:
        paid_gate.check()            # kill switch / ambiente / teto: recusa antes de qualquer rede
        wid = self._workflow(style)
        pend = fal_contract.placeholders(self.contract, style, include_recover=False)   # recover nao bloqueia o envio
        if pend:
            raise PermanentError("contrato do workflow ainda A CONFIRMAR (Fase 0): " + ", ".join(pend[:4]))
        return wid

    def params(self, request: WorkflowRequest) -> dict:
        return {"style": request.style, "workflow": self.workflow_ids.get(request.style)}

    def estimate_cost(self, request: WorkflowRequest) -> tuple[float, str]:
        if self._estimator is None:
            raise PermanentError("sem estimativa de custo para o workflow")
        return self._estimator(request.style)

    # ---------------------------------------------------------------- submit / poll
    def submit_full(self, request: WorkflowRequest) -> SubmitInfo:
        wid = self._guard(request.style)
        url = self.client.upload(request.image_path, lifecycle_s=self.upload_lifecycle_s)
        payload = fal_contract.build_input(self.contract, request.style, url)
        self.submit_count += 1
        return self.client.submit(wid, payload, start_timeout_s=self.start_timeout_s)

    def submit(self, request: WorkflowRequest) -> str:
        return self.submit_full(request).request_id

    def poll(self, op_id: str, meta: dict | None = None, style: str | None = None) -> OpResult:
        meta = meta or {}
        wid = meta.get("workflow")
        status_url = meta.get("status_url") or (f"{QUEUE_URL}/{wid}/requests/{op_id}/status" if wid else None)
        response_url = meta.get("response_url") or (f"{QUEUE_URL}/{wid}/requests/{op_id}" if wid else None)
        if not status_url or not response_url:
            return OpResult(OpState.FAILED, error="sem enderecos de consulta da execucao", permanent=True)
        st = self.client.status(status_url)
        state = str(st.get("status") or "").upper()
        if state in ("IN_QUEUE", "IN_PROGRESS", ""):
            return OpResult(OpState.RUNNING, usage={"status": state, "queue_position": st.get("queue_position")})
        if state != "COMPLETED":
            return OpResult(OpState.FAILED, error=f"status inesperado da fal.ai: {state}", permanent=True)
        if st.get("error"):             # a doc: falha e cancelamento tambem chegam como COMPLETED
            et = str(st.get("error_type") or "")
            return OpResult(OpState.FAILED, error=_msg(f"{et}: {st['error']}"), permanent=et not in ("server_error", "timeout"),
                            usage={"error_type": et})
        result = self.client.result(response_url)
        pkg = fal_contract.parse_result(result, style or meta.get("style") or "dark", self.contract)
        usage = {"request_id": op_id, "nodes": pkg.nodes,
                 "inference_time": (st.get("metrics") or {}).get("inference_time")}
        return OpResult(OpState.SUCCEEDED, package=pkg, usage=usage, raw=result)

    def cancel(self, op_id: str, meta: dict | None = None) -> None:
        url = (meta or {}).get("cancel_url")
        if url:
            self.client.cancel(url)

    def fetch(self, artifact: fal_contract.Artifact) -> bytes:
        if artifact.data is not None:
            return artifact.data
        if artifact.path is not None:
            return Path(artifact.path).read_bytes()
        if artifact.url:
            return self.client.download(artifact.url)
        raise PermanentError("artefato sem origem")

    def recover_artifact(self, artifact: fal_contract.Artifact, style: str = "light") -> fal_contract.Artifact | None:
        """Busca DE NOVO so este arquivo pelo request_id do no (nunca reexecuta o workflow). None se nao der."""
        rec = artifact.recover
        if not rec:
            return None
        pend = fal_contract.recover_pending(self.contract, style)
        if pend:     # recuperacao so depois de confirmar recover.hero e o request_id por no (rodada real)
            raise PermanentError("recuperacao de foto pelo no ainda A CONFIRMAR (manual): " + "; ".join(pend[:2]))
        res = self.client.node_result(rec["endpoint"], rec["request_id"])
        url = fal_contract._url_of(fal_contract.get_path(res, rec["path"]))
        if not url:
            return None
        return fal_contract.Artifact(kind=artifact.kind, url=url, recover=rec)

    def reconcile_cost(self, request_ids: list[str]) -> float | None:
        return billing_total(self.client.billing(request_ids))
