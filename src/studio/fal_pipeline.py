"""Pipeline do motor fal.ai: UMA execucao de workflow por producao, em vez de 3 cenas x (imagem + revisao + video).

O Kiroo NAO reconstroi as etapas generativas (video com narracao, foto, titulo e legenda): isso e do workflow. Aqui so:
envia a foto e o estilo, acompanha a execucao, recupera e valida os artefatos, prepara o MP4 final com o FFmpeg do
Kiroo e entrega o pacote (final.mp4 + 1 foto hero + capa + legenda). Estados de producao reaproveitados:

  received -> validated -> scripted -> producing (workflow no ar) -> editing (composicao) -> awaiting_final_review -> completed

Garantias (ver docs):
* Idempotencia: a tentativa e gravada ANTES do envio; um envio sem resposta fica "incerto" e NUNCA e repetido sozinho
  (a fal.ai nao tem chave de idempotencia). Reexecucao integral so por acao explicita do administrador, passando pelo
  paid_gate e pelo orcamento operacional.
* Ledger: a tentativa fica `submitted` ate a entrega COMPLETA; so entao vira `succeeded` e o pre-orcamento e liquidado
  (settle_pool). Entrega incompleta ou em revisao mantem a reserva; falha tecnica nao cobra (settle_pool) e o resto do
  pre-orcamento volta (close_pool). Nada no ledger muda: so a ordem em que a tentativa muda de estado.
* Entrega: `delivery/` so recebe arquivos depois de TUDO validado; a limpeza de retencao nunca a toca.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import budget as budget_mod
from . import fal_contract as fc
from . import package_files as pf
from . import paid_gate
from .agents import composer
from .agents.product_prep import prepare_product
from .db import now
from .models import ProductInput
from .orchestrator import BACKOFF_BASE_S, BACKOFF_MAX_S, BudgetExceeded, OrchestratorError
from .providers.base import OpState, PermanentError, ProviderBillingError, TransientError, WorkflowRequest
from .providers.fal import UncertainSubmit
from .states import TERMINAL, ProductionStatus as PS
from .storage import ProductionStorage, sha256_file

log = logging.getLogger("studio")

# Codigos estaveis de pausa (a interface e o administrador decidem pelo codigo)
SUBMIT_UNCERTAIN = "fal_submit_uncertain"
TIMEOUT = "fal_timeout"
ADMIN_REQUIRED = "fal_admin_required"
REFUSED = "fal_refused"
INCOMPLETE = "delivery_incomplete"
COMPOSE_REVIEW = "compose_review"
DOWNLOAD = "fal_download"

CLIENT_FINALIZING = "Estamos finalizando o seu pacote. A equipe do Kiroo ja foi avisada e avisaremos quando estiver pronto."
CLIENT_FAILED = "Nao foi possivel gerar o seu video desta vez. Nada foi cobrado."

MAX_DOWNLOAD_RETRIES = 5
RECOVER_MAX = 2
ATTEMPT_DIR = re.compile(r"^attempt_\d{2,}$")
KEEP_IN_ATTEMPT = {"result.json"}          # historico: fica para sempre


def _ts(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def engine_of(row) -> str:
    return row["engine"] if "engine" in row.keys() else "gemini"


# =================================================================== criacao
def create_production(o, product: ProductInput, *, style: str, workspace_id: str | None, client_request_id: str | None,
                      budget_usd: float, prebudget: bool) -> tuple[str, bool]:
    """Cria a producao do motor fal.ai. Devolve (pid, duplicado). O mesmo `client_request_id` no mesmo workspace devolve
    a producao que ja existe, sem reservar nem cobrar de novo (duplo clique)."""
    from .orchestrator import DuplicateRequest
    if style not in fc.STYLES:
        raise OrchestratorError("escolha o estilo: Escuro ou Claro")
    if workspace_id and client_request_id:
        row = o.db.conn.execute("SELECT id FROM productions WHERE workspace_id=? AND client_request_id=?",
                                (workspace_id, client_request_id)).fetchone()
        if row:
            return row["id"], True
    estimate = budget_mod.estimate_workflow(o.s, style)
    try:
        pid = o.create_production(product, format_id="produto_3cenas_15s", art_direction="ambiente_neutro", presenter="bia",
                                  budget_usd=budget_usd, go_ahead="all", autonomy="classico", workspace_id=workspace_id,
                                  prebudget=prebudget, engine="fal", style=style, client_request_id=client_request_id,
                                  estimate=estimate)
    except DuplicateRequest as dup:
        return dup.pid, True
    o.db.add_event(pid, "fal_created", f"motor fal.ai, estilo {fc.STYLE_LABELS[style]}", data={"style": style})
    return pid, False


# =================================================================== execucao
class FalRunner:
    def __init__(self, orch):
        self.o = orch
        if orch.fal_gen is None:
            raise OrchestratorError("motor fal.ai indisponivel: defina FAL_KEY (e libere as chamadas pagas) ou use o DEMO")
        self.gen = orch.fal_gen

    # ------------------------------------------------------------------ apoio
    @property
    def db(self):
        return self.o.db

    def _st(self, pid: str) -> ProductionStorage:
        return self.o._storage(pid)

    def _attempt(self, pid: str):
        return self.db.conn.execute("SELECT * FROM attempts WHERE production_id=? AND kind='workflow' AND superseded=0 "
                                    "ORDER BY created_at DESC, rowid DESC LIMIT 1", (pid,)).fetchone()

    @staticmethod
    def _meta(att) -> dict:
        return json.loads(att["remote_meta_json"] or "{}") if att is not None else {}

    def _set_meta(self, att_id: str, **kw) -> dict:
        att = self.db.attempt(att_id)
        meta = {**self._meta(att), **kw}
        self.db.update_attempt(att_id, remote_meta_json=json.dumps(meta, ensure_ascii=False))
        return meta

    def _dj(self, pid: str) -> dict:
        raw = self.db.production(pid)["delivery_json"]
        return json.loads(raw) if raw else {}

    def _set_dj(self, pid: str, **kw) -> dict:
        dj = {**self._dj(pid), **kw}
        self.db.update_production(pid, delivery_json=json.dumps(dj, ensure_ascii=False))
        return dj

    def _style(self, pid: str) -> str:
        return self.db.production(pid)["style"]

    def _adir_rel(self, att) -> str:
        return f"workflow/attempt_{att['attempt_no']:02d}"

    def _fail_production(self, pid: str, reason: str, detail: str = "") -> str:
        """Falha tecnica: sem debito ao cliente (settle_pool: tentativa failed) e o resto do pre-orcamento volta."""
        self.db.set_production_status(pid, PS.FAILED, CLIENT_FAILED)
        self.db.add_event(pid, "fal_failed", f"{reason}{': ' + detail if detail else ''}"[:500])
        budget_mod.notify_admin(self.db, pid, "fal_failed", f"{reason} {detail}"[:400])
        return "paused"

    def _pause(self, pid: str, client_msg: str, code: str, detail: str = "", *, alert: bool = True) -> str:
        self.o._pause(pid, client_msg, code)
        if detail:
            self.db.add_event(pid, "fal_paused", detail[:500], data={"code": code})
        if alert:
            budget_mod.notify_admin(self.db, pid, code, detail or client_msg)
        return "paused"

    def _interval(self) -> float:
        return self.o.s.poll_interval_s if getattr(self.gen, "simulated", False) else self.o.s.fal_poll_s

    # ------------------------------------------------------------------ laco
    def loop(self, pid: str, wait: bool, deadline: float | None) -> None:
        o = self.o
        while True:
            if o.stop_event is not None and o.stop_event.is_set():
                o.stopped = True
                break
            o._settle(pid)
            status = PS(self.db.production(pid)["status"])
            if status in TERMINAL or status in {PS.PAUSED, PS.AWAITING_FINAL_REVIEW}:
                break
            if status in {PS.RECEIVED, PS.AWAITING_REFERENCES}:
                if not self._prepare(pid):
                    break
            elif status in {PS.VALIDATED, PS.SCRIPTED, PS.PRODUCING} and o.needs_confirmation(pid):
                break   # "Seu proximo video": sem a confirmacao do cliente nada e gasto
            elif status == PS.VALIDATED:
                self.db.set_production_status(pid, PS.SCRIPTED, f"workflow do estilo {fc.STYLE_LABELS[self._style(pid)]}")
            elif status == PS.SCRIPTED:
                self.db.set_production_status(pid, PS.PRODUCING)
            elif status == PS.PRODUCING:
                outcome = self._produce(pid)
                if outcome == "waiting":
                    if not wait or (deadline and time.monotonic() > deadline):
                        break
                    o.sleep(self._interval())
                elif outcome != "progress":
                    break
            elif status == PS.EDITING:
                self._deliver(pid)

    # ------------------------------------------------------------------ preparo da foto
    def _prepare(self, pid: str) -> bool:
        o = self.o
        row = self.db.production(pid)
        profiles = json.loads(row["profiles_json"])
        product = ProductInput.model_validate_json(row["product_json"])
        st = self._st(pid)
        sheet = prepare_product(product, st, profiles["presenter"]["data"], "product_only", o.s.reference_root, o.base_dir)
        self.db.update_production(pid, sheet_json=sheet.model_dump_json())
        st.write_json("sheet.json", sheet.model_dump(mode="json"))
        usable = [r for r in sheet.product.references if r.usable_for_generation]
        if sheet.blocking_issues or not usable:
            reason = "; ".join(i.message for i in sheet.blocking_issues) or "envie uma foto do produto"
            self.db.set_production_status(pid, PS.AWAITING_REFERENCES, reason)
            return False
        self.db.set_production_status(pid, PS.VALIDATED, "foto recebida")
        return True

    def _photo(self, pid: str) -> tuple[Path, str]:
        """Foto enviada ao workflow: a primeira utilizavel, em JPG com no maximo 2048 px (sem ampliar)."""
        st = self._st(pid)
        sheet = json.loads(self.db.production(pid)["sheet_json"])
        refs = [r for r in sheet["product"]["references"] if r.get("stored_path") and r.get("role") != "context"
                and r.get("source") != "screen_recording"]
        if not refs:
            raise OrchestratorError("sem foto utilizavel")
        src = st.path(refs[0]["stored_path"])
        dst = st.path("inputs", "workflow_photo.jpg")
        if not dst.is_file():
            self.o.ffmpeg.fit_image(src, dst, 2048)
        return dst, sha256_file(dst)

    # ------------------------------------------------------------------ producao (workflow no ar)
    def _produce(self, pid: str) -> str:
        att = self._attempt(pid)
        if att is None or att["status"] == "failed":
            return self._start(pid)
        meta = self._meta(att)
        stage = meta.get("stage")
        if att["status"] == "created":
            if stage in ("uncertain", "submitting"):   # "submitting" achado no inicio: o processo caiu no meio do envio
                return self._mark_uncertain(pid, att, "envio interrompido sem confirmacao da fal.ai")
            retry_at = _ts(att["next_retry_at"])
            if retry_at and retry_at > datetime.now(timezone.utc):
                return "waiting"
            return self._submit(pid, att)
        if att["status"] == "submitted":
            retry_at = _ts(att["next_retry_at"])
            if retry_at and retry_at > datetime.now(timezone.utc):
                return "waiting"
            if stage in ("ingesting", "incomplete"):
                return self._ingest(pid, att)
            if stage == "ingested":
                self.db.set_production_status(pid, PS.EDITING, "pacote recebido: compondo o video")
                return "progress"
            return self._poll(pid, att)
        # succeeded: ja entregue antes (ex.: remontagem); segue para a composicao
        self.db.set_production_status(pid, PS.EDITING, "remontagem do pacote")
        return "progress"

    def _prior_executions(self, pid: str) -> int:
        n = 0
        for a in self.db.conn.execute("SELECT * FROM attempts WHERE production_id=? AND kind='workflow'", (pid,)):
            if a["submitted_at"] or self._meta(a).get("stage") == "uncertain":
                n += 1
        return n

    def _start(self, pid: str) -> str:
        o = self.o
        dj = self._dj(pid)
        if self._prior_executions(pid) and not dj.get("resubmit_authorized"):
            return self._pause(pid, CLIENT_FINALIZING, ADMIN_REQUIRED,
                               "ja houve uma execucao deste pacote: nova execucao so com autorizacao explicita do "
                               "administrador (studio fal resubmit)")
        unsent = self.db.conn.execute("SELECT COUNT(*) FROM attempts WHERE production_id=? AND kind='workflow' AND "
                                      "submitted_at IS NULL AND status='failed' AND error_permanent=0 AND superseded=0",
                                      (pid,)).fetchone()[0]
        if unsent >= 2:   # envios transitorios que nunca chegaram: nao fica tentando para sempre
            return self._pause(pid, CLIENT_FINALIZING, REFUSED, "o envio ao workflow falhou varias vezes sem ser aceito")
        inflight = self.db.conn.execute("SELECT COUNT(*) FROM attempts WHERE kind='workflow' AND status='submitted'").fetchone()[0]
        if inflight >= o.s.fal_max_inflight:
            return "waiting"
        style = self._style(pid)
        try:
            photo, sha = self._photo(pid)
        except Exception as exc:  # noqa: BLE001 — foto ilegivel: nada foi enviado nem cobrado
            return self._pause(pid, "Nao foi possivel preparar a foto. Envie outra e tente de novo.", REFUSED,
                               f"foto: {type(exc).__name__}: {exc}", alert=False)
        req = WorkflowRequest(style=style, image_path=photo)
        params = self.gen.params(req)
        input_hash = _hash({"provider": self.gen.provider, "style": style, "photo": sha, "workflow": params.get("workflow")})
        reusable = self.db.reusable_attempt(pid, "workflow", input_hash)
        if reusable is not None:
            self.db.add_event(pid, "attempt_reused", "workflow: resultado identico ja pago reaproveitado",
                              data={"attempt_id": reusable["id"]})
            self.db.set_production_status(pid, PS.EDITING, "remontagem do pacote")
            return "progress"
        try:
            estimate, source = self.gen.estimate_cost(req)
            hold = o._hold(pid, estimate, "pacote de video e foto", "workflow")
        except BudgetExceeded:
            return "paused"
        att_id = self.db.create_attempt(production_id=pid, scene_idx=None, kind="workflow", provider=self.gen.provider,
                                        model=self.gen.model, simulated=self.gen.simulated, input_hash=input_hash,
                                        prompt=None, params=params, references=[{"key": "photo", "path": str(photo.name),
                                                                                  "sha256": sha}],
                                        estimated_cost_usd=estimate, pricing_source=source)
        if hold:
            o.ledger().attach(hold, att_id)
        self._set_meta(att_id, style=style, stage="created")
        if dj.get("resubmit_authorized"):
            self._set_dj(pid, resubmit_authorized=False)      # a autorizacao vale para UMA execucao
        return self._submit(pid, self.db.attempt(att_id))

    def _submit(self, pid: str, att) -> str:
        o = self.o
        att_id = att["id"]
        style = self._meta(att).get("style") or self._style(pid)
        photo, _ = self._photo(pid)
        # gravado ANTES da chamada: se o processo cair daqui ate a resposta, o envio e tratado como incerto (nunca repetido)
        self._set_meta(att_id, stage="submitting", submit_started_at=now())
        try:
            info = self.gen.submit_full(WorkflowRequest(style=style, image_path=photo))
        except paid_gate.PaidCallsBlocked as exc:
            self.db.update_attempt(att_id, status="failed", error=str(exc)[:500], error_permanent=0, superseded=1,
                                   finished_at=now(), estimated_cost_usd=0.0)
            self._set_meta(att_id, stage="aborted")
            code = budget_mod.MONTHLY_CAP if exc.reason == "platform_cap" else f"{budget_mod.PAID_GATE}:{exc.reason}"
            return self._pause(pid, str(exc), code, alert=False)
        except UncertainSubmit as exc:
            return self._mark_uncertain(pid, att, str(exc))
        except TransientError as exc:
            self._set_meta(att_id, stage="retry")
            return o._transient(pid, self.db.attempt(att_id), exc, "envio")
        except ProviderBillingError as exc:
            self.db.update_attempt(att_id, status="failed", error=str(exc)[:500], error_permanent=0, superseded=1,
                                   finished_at=now(), estimated_cost_usd=0.0)
            self._set_meta(att_id, stage="aborted")
            o._pause_billing(pid, exc)
            return "paused"
        except PermanentError as exc:   # pedido recusado: nada foi aceito, nada e cobrado; o admin corrige e retoma
            self.db.update_attempt(att_id, status="failed", error=str(exc)[:1000], error_permanent=1, superseded=1,
                                   finished_at=now(), estimated_cost_usd=0.0)
            self._set_meta(att_id, stage="aborted")
            return self._pause(pid, CLIENT_FINALIZING, REFUSED, f"pedido recusado pela fal.ai: {exc}")
        self.db.update_attempt(att_id, status="submitted", remote_op_id=info.request_id, submitted_at=now(),
                               next_retry_at=None, transient_retries=0)
        self._set_meta(att_id, stage="submitted", **info.meta)
        self.db.add_event(pid, "attempt_submitted", f"workflow #{att['attempt_no']} enviado",
                          data={"remote_op_id": info.request_id})
        log.info("[%s] workflow enviado (op %s)", pid, info.request_id)
        return "progress"

    def _mark_uncertain(self, pid: str, att, detail: str) -> str:
        self._set_meta(att["id"], stage="uncertain")
        return self._pause(pid, CLIENT_FINALIZING, SUBMIT_UNCERTAIN,
                           f"envio sem confirmacao ({detail}). A execucao pode existir na fal.ai: confira no painel e use "
                           "`studio fal adopt <pid> --request-id ...` ou `studio fal not-sent <pid>`. Nada foi reenviado.")

    # ------------------------------------------------------------------ acompanhamento
    def _poll(self, pid: str, att) -> str:
        o = self.o
        att_id = att["id"]
        meta = self._meta(att)
        started = _ts(att["submitted_at"])
        if started and (datetime.now(timezone.utc) - started).total_seconds() > o.s.fal_timeout_s:
            try:
                self.gen.cancel(att["remote_op_id"], meta)
            except Exception as exc:  # noqa: BLE001
                log.info("[%s] cancelamento por tempo esgotado nao confirmado (%s)", pid, type(exc).__name__)
            self.db.update_attempt(att_id, status="failed", error="tempo esgotado esperando o workflow", error_permanent=0,
                                   finished_at=now())
            self._set_meta(att_id, stage="timeout")
            return self._pause(pid, CLIENT_FINALIZING, TIMEOUT,
                               f"a execucao passou de {o.s.fal_timeout_s:g}s. Confira na fal.ai; nada foi reenviado "
                               "(nova execucao so com `studio fal resubmit`).")
        try:
            res = self.gen.poll(att["remote_op_id"], meta, meta.get("style"))
        except TransientError as exc:   # a execucao remota segue: nao falha a tentativa por erro de CONSULTA
            retries = att["transient_retries"] + 1
            delay = min(BACKOFF_BASE_S * 2 ** (retries - 1), BACKOFF_MAX_S)
            self.db.update_attempt(att_id, transient_retries=retries, error=f"consulta: {exc}"[:500],
                                   next_retry_at=(datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec="seconds"))
            return "waiting"
        except ProviderBillingError as exc:
            o._pause_billing(pid, exc)
            return "paused"
        except PermanentError as exc:   # ex.: resultado expirou / nao encontrado
            self.db.update_attempt(att_id, status="failed", error=str(exc)[:1000], error_permanent=1, finished_at=now())
            self._set_meta(att_id, stage="poll_failed")
            return self._pause(pid, CLIENT_FINALIZING, "fal_poll_failed", f"consulta recusada: {exc}")
        if res.state == OpState.RUNNING:
            self.db.update_attempt(att_id, next_retry_at=(datetime.now(timezone.utc) + timedelta(seconds=self._interval()))
                                   .isoformat(timespec="seconds"), transient_retries=0)
            self._set_meta(att_id, queue=res.usage.get("queue_position"), remote_status=res.usage.get("status"))
            return "waiting"
        if res.state == OpState.FAILED:
            self.db.update_attempt(att_id, status="failed", error=(res.error or "")[:1000], error_permanent=int(res.permanent),
                                   finished_at=now(), usage_json=json.dumps(res.usage, default=str))
            self.db.add_event(pid, "attempt_failed", f"workflow #{att['attempt_no']}: {res.error}")
            return self._fail_production(pid, "o workflow terminou com erro", res.error or "")
        # sucesso: grava o resultado (historico) e passa a baixar
        pkg = res.package
        adir = self._st(pid).dir(self._adir_rel(att))
        (adir / "result.json").write_text(json.dumps({
            "request_id": att["remote_op_id"], "style": meta.get("style"), "package": fc.package_to_dict(pkg),
            "raw": res.raw,      # resposta BRUTA do workflow (com o envelope), para confirmar recover.hero e request_id por no
            "usage": res.usage, "completed_at": now()}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self._set_dj(pid, title=pkg.title, caption=pkg.caption, warnings=list(pkg.warnings))
        self.db.update_attempt(att_id, usage_json=json.dumps(res.usage, default=str), transient_retries=0)
        self._set_meta(att_id, stage="ingesting", nodes=pkg.nodes)
        return self._ingest(pid, self.db.attempt(att_id))

    # ------------------------------------------------------------------ recuperar e validar os artefatos
    def _load_package(self, pid: str, att) -> fc.WorkflowPackage:
        data = json.loads((self._st(pid).path(self._adir_rel(att), "result.json")).read_text(encoding="utf-8"))
        return fc.package_from_dict(data["package"])

    def _fetch_valid(self, adir: Path, base: str, kind: str, art: fc.Artifact) -> Path:
        """Baixa (se preciso) e valida pelos bytes. Reaproveita o arquivo ja gravado e valido (retomada)."""
        for p in sorted(adir.glob(base + ".*")):
            try:
                pf.validate(kind, p.read_bytes())
                return p
            except pf.PackageFileError:
                p.unlink(missing_ok=True)
        data = self.gen.fetch(art)
        pf.validate(kind, data)
        ext = {"video": ".mp4", "image": ".jpg"}[kind]
        out = adir / (base + ext)
        out.write_bytes(data)
        return out

    def _ingest(self, pid: str, att) -> str:
        att_id = att["id"]
        dj = self._dj(pid)
        pkg = self._load_package(pid, att)
        adir = self._st(pid).dir(self._adir_rel(att))
        tries = dict(dj.get("recover_tries") or {})
        warnings = list(dj.get("warnings") or [])
        try:
            # 1) o video (ja com a narracao embutida): sem ele, ou sem audio nele, e falha tecnica (sem debito)
            art = pkg.video
            if art is None or not art.available:
                self.db.update_attempt(att_id, status="failed", error="pacote sem video", error_permanent=1, finished_at=now())
                return self._fail_production(pid, "o pacote veio sem video")
            try:
                vpath = self._fetch_valid(adir, "video", "video", art)
                composer.check_source(self.o.ffmpeg, vpath)
            except (pf.PackageFileError, composer.SourceInvalid) as exc:
                for f in adir.glob("video.*"):
                    f.unlink(missing_ok=True)
                self.db.update_attempt(att_id, status="failed", error=f"video invalido: {exc}", error_permanent=1, finished_at=now())
                return self._fail_production(pid, "video invalido", str(exc))
            # 2) a foto hero; se faltar, tenta a recuperacao controlada pelo no (nunca reexecuta o workflow)
            missing: list[str] = []
            if not (self._have_image(adir) or self._try_image(adir, pkg.hero)):
                art = pkg.hero
                again = None
                if art is not None and art.recover and tries.get("hero", 0) < RECOVER_MAX:
                    tries["hero"] = tries.get("hero", 0) + 1
                    self._set_dj(pid, recover_tries=tries)
                    try:
                        again = self.gen.recover_artifact(art, style=self._style(pid))
                    except (TransientError, PermanentError) as exc:
                        self.db.add_event(pid, "fal_recover", f"foto hero: busca pelo no falhou ({type(exc).__name__})")
                if again is not None and self._try_image(adir, again):
                    self.db.add_event(pid, "fal_recover", "foto hero recuperada pelo no (sem novo envio)")
                else:
                    missing.append("hero")
        except TransientError as exc:   # download de arquivo: seguro repetir (a execucao ja terminou)
            n = att["transient_retries"] + 1
            if n > MAX_DOWNLOAD_RETRIES:
                return self._pause(pid, CLIENT_FINALIZING, DOWNLOAD, f"download repetidamente falhando: {exc}")
            self.db.update_attempt(att_id, transient_retries=n, error=f"download: {exc}"[:500],
                                   next_retry_at=(datetime.now(timezone.utc) + timedelta(seconds=min(BACKOFF_BASE_S * 2 ** n, 60)))
                                   .isoformat(timespec="seconds"))
            return "waiting"
        except ProviderBillingError as exc:
            self.o._pause_billing(pid, exc)
            return "paused"
        except PermanentError as exc:
            return self._pause(pid, CLIENT_FINALIZING, DOWNLOAD, f"download recusado: {exc}")
        self._set_dj(pid, warnings=warnings, missing=missing)
        if missing and not dj.get("allow_partial"):
            self._set_dj(pid, delivery_status="incomplete")
            self.db.update_production(pid, delivery_status="incomplete")
            self._set_meta(att_id, stage="incomplete")
            return self._pause(pid, CLIENT_FINALIZING, INCOMPLETE,
                               "entrega incompleta: falta a foto hero. Recuperacao pelo no esgotada ou "
                               "indisponivel. Opcoes: `studio fal recover|deliver-partial|resubmit|waive <pid>`.")
        self._set_meta(att_id, stage="ingested")
        self.db.update_production(pid, delivery_status="pending")
        self.db.set_production_status(pid, PS.EDITING, "pacote recebido: compondo o video")
        return "progress"

    @staticmethod
    def _have_image(adir: Path) -> bool:
        p = adir / "image_hero.jpg"
        if not p.is_file():
            return False
        try:
            pf.validate("image", p.read_bytes())
            return True
        except pf.PackageFileError:
            p.unlink(missing_ok=True)
            return False

    def _try_image(self, adir: Path, art: fc.Artifact | None) -> bool:
        """Baixa e valida a foto hero. False se nao ha origem ou o arquivo e invalido (conta como faltante)."""
        if art is None or not art.available:
            return False
        try:
            data = self.gen.fetch(art)
            pf.validate("image", data)
        except (pf.PackageFileError, PermanentError):
            return False
        (adir / "image_hero.jpg").write_bytes(data)
        return True

    # ------------------------------------------------------------------ composicao e entrega
    def _deliver(self, pid: str) -> None:
        o = self.o
        att = self._attempt(pid)
        if att is None:
            self._pause(pid, CLIENT_FINALIZING, COMPOSE_REVIEW, "sem execucao do workflow para compor")
            return
        st = self._st(pid)
        adir = st.path(self._adir_rel(att))
        dj = self._dj(pid)
        video = next(iter(sorted(adir.glob("video.*"))), None)
        if video is None:
            self._pause(pid, CLIENT_FINALIZING, COMPOSE_REVIEW, "arquivos do pacote ausentes: refaca a recuperacao")
            return
        hero = adir / "image_hero.jpg"
        missing = [] if hero.is_file() else ["hero"]
        if missing and not dj.get("allow_partial"):
            self._set_dj(pid, missing=missing, delivery_status="incomplete")
            self.db.update_production(pid, delivery_status="incomplete")
            self._set_meta(att["id"], stage="incomplete")
            self._pause(pid, CLIENT_FINALIZING, INCOMPLETE, "foto hero ausente na entrega")
            return
        work = st.dir("work/compose")
        cfg = composer.ComposeConfig.from_env()
        try:
            rep = composer.compose(o.ffmpeg, video, work / "final.mp4", work, cfg)
        except composer.SourceInvalid as exc:     # video sem audio/stream: falha tecnica, sem debito
            self.db.update_attempt(att["id"], status="failed", error=f"video invalido: {exc}", error_permanent=1, finished_at=now())
            self._fail_production(pid, "video invalido", str(exc))
            return
        except composer.ComposeNeedsReview as exc:
            self._pause(pid, CLIENT_FINALIZING, COMPOSE_REVIEW, f"{exc} (codigo {exc.code}). Ajuste a janela de duracao "
                        "(STUDIO_FAL_MIN_S/MAX_S) e retome, ou use `studio fal waive|resubmit <pid>`.")
            return
        delivery = st.dir("delivery")
        os.replace(work / "final.mp4", delivery / fc.FINAL_VIDEO)
        manifest = {fc.FINAL_VIDEO: {"role": "video", "sha256": sha256_file(delivery / fc.FINAL_VIDEO)}}
        if not missing:
            tmp = work / fc.HERO_FILE
            shutil.copy2(hero, tmp)
            os.replace(tmp, delivery / fc.HERO_FILE)
            manifest[fc.HERO_FILE] = {"role": "hero", "label": fc.HERO_LABEL, "sha256": sha256_file(delivery / fc.HERO_FILE)}
        composer.make_cover(o.ffmpeg, delivery / fc.FINAL_VIDEO, delivery / fc.COVER_FILE, cfg)
        manifest[fc.COVER_FILE] = {"role": "cover", "sha256": sha256_file(delivery / fc.COVER_FILE)}
        fmt = json.loads(self.db.production(pid)["profiles_json"])["format"]["data"]
        caption_txt, cwarn = composer.build_caption(dj.get("title", ""), dj.get("caption", ""), fmt)
        st.write_bytes(f"delivery/{fc.CAPTION_FILE}", caption_txt.encode("utf-8"))   # UTF-8 puro, sem traducao de quebra de linha
        text_ok = bool(dj.get("title") and dj.get("caption"))
        warnings = list(dict.fromkeys([*list(dj.get("warnings") or []), *rep.warnings, *cwarn]))
        status = "partial" if missing else "complete"      # texto faltando e AVISO (a entrega segue completa)
        st.write_json("delivery/delivery_meta.json", {
            "engine": "fal", "style": self._style(pid), "simulated": bool(self.gen.simulated), "delivery_status": status,
            "final_probe": rep.checks, "compose": {"video_action": rep.plan.video_action},
            "missing": missing, "text_status": "ok" if text_ok else "partial", "warnings": warnings, "files": manifest,
            "title": dj.get("title", ""), "caption": dj.get("caption", "")})
        if att["status"] != "succeeded":   # a ENTREGA completa e o que liquida o pre-orcamento (settle_pool)
            self.db.update_attempt(att["id"], status="succeeded", output_path=f"delivery/{fc.FINAL_VIDEO}",
                                   output_sha256=manifest[fc.FINAL_VIDEO]["sha256"], finished_at=now(), error=None,
                                   next_retry_at=None)
        self._set_meta(att["id"], stage="delivered")
        self._set_dj(pid, delivery_status=status, files=manifest, warnings=warnings, missing=missing)
        self.db.update_production(pid, delivery_status=status)
        self.db.add_event(pid, "edit_done", f"pacote {status}: video {rep.duration_s:.1f}s, "
                          f"{1 - len(missing)} foto(s), {'legenda' if text_ok else 'sem legenda completa'}")
        for w in warnings:
            self.db.add_event(pid, "delivery_warning", w)
        self.db.set_production_status(pid, PS.AWAITING_FINAL_REVIEW, f"pacote pronto: {rep.duration_s:.2f}s")


# =================================================================== acoes do administrador (CLI)
def _resume(o, pid: str, reason: str) -> None:
    """Retoma. Uma pausa de entrega incompleta feita na composicao volta a `producing` (para rebuscar os artefatos)."""
    runner = FalRunner(o)
    o.db.resume_production(pid, reason)
    att = runner._attempt(pid)
    if att is not None and runner._meta(att).get("stage") == "incomplete" and PS(o.db.production(pid)["status"]) != PS.PRODUCING:
        o.db.set_production_status(pid, PS.PRODUCING, reason)


def admin_action(o, pid: str, action: str, *, request_id: str | None = None, reason: str = "") -> str:
    """Decisoes sobre producoes pausadas do motor fal.ai. NENHUMA reexecuta o workflow sozinha, exceto `resubmit`
    (acao explicita, que passa pelo paid_gate e pelo orcamento operacional na hora do envio)."""
    runner = FalRunner(o)
    row = o.db.production(pid)
    if engine_of(row) != "fal":
        raise OrchestratorError("producao nao e do motor fal.ai")
    status = PS(row["status"])
    if status != PS.PAUSED:
        raise OrchestratorError(f"a producao nao esta pausada (estado: {status})")
    att = runner._attempt(pid)
    if action == "waive":   # dispensa: cancela, nada e cobrado do cliente e o pre-orcamento volta
        o.cancel(pid, f"dispensada pelo administrador: {reason or 'sem motivo'}. Nada foi cobrado.")
        return "waived"
    if action == "recover":   # tenta de novo buscar as imagens pelo no (nunca reenvia o workflow)
        runner._set_dj(pid, recover_tries={})
        _resume(o, pid, "recuperacao de artefatos pelo administrador")
        return "resumed"
    if action == "deliver-partial":   # entrega o que existe e liquida: decisao do admin, fica registrada
        runner._set_dj(pid, allow_partial=True)
        o.db.add_event(pid, "admin_decision", f"entrega parcial autorizada: {reason or 'sem motivo'}")
        _resume(o, pid, "entrega parcial autorizada pelo administrador")
        return "resumed"
    if action == "resubmit":   # a unica que gasta de novo: autorizacao explicita, vale para uma execucao
        if att is not None and att["status"] in ("created", "submitted"):
            o.db.update_attempt(att["id"], status="failed", error="substituida por nova execucao autorizada",
                                finished_at=now())
        runner._set_dj(pid, resubmit_authorized=True, missing=[], recover_tries={}, delivery_status="none")
        o.db.update_production(pid, delivery_status="none")
        o.db.add_event(pid, "admin_decision", f"nova execucao autorizada: {reason or 'sem motivo'}")
        o.db.resume_production(pid, "nova execucao autorizada pelo administrador")
        if PS(o.db.production(pid)["status"]) != PS.PRODUCING:
            o.db.set_production_status(pid, PS.PRODUCING, "nova execucao do workflow")
        return "resumed"
    if action == "adopt":   # envio incerto que existe na fal.ai: adota o request_id (sem novo envio)
        if att is None or runner._meta(att).get("stage") != "uncertain" or not request_id:
            raise OrchestratorError("adopt so vale para um envio incerto e exige --request-id")
        wf = runner.gen.workflow_ids.get(runner._style(pid)) if hasattr(runner.gen, "workflow_ids") else None
        o.db.update_attempt(att["id"], status="submitted", remote_op_id=request_id, submitted_at=now(), next_retry_at=None)
        runner._set_meta(att["id"], stage="submitted", workflow=wf, style=runner._style(pid))
        o.db.add_event(pid, "admin_decision", f"execucao adotada pelo administrador: {request_id}")
        o.db.resume_production(pid, "execucao adotada pelo administrador")
        return "resumed"
    if action == "not-sent":   # confirmado que NAO existe na fal.ai: descarta a tentativa (sem custo) e segue
        if att is None or runner._meta(att).get("stage") != "uncertain":
            raise OrchestratorError("not-sent so vale para um envio incerto")
        o.db.update_attempt(att["id"], status="failed", superseded=1, error="envio nao chegou a fal.ai (confirmado)",
                            estimated_cost_usd=0.0, finished_at=now())
        runner._set_meta(att["id"], stage="aborted")
        o.db.add_event(pid, "admin_decision", "envio confirmado como nao enviado: nova tentativa liberada")
        o.db.resume_production(pid, "retomada apos confirmar que o envio nao chegou")
        return "resumed"
    raise OrchestratorError(f"acao desconhecida: {action}")


# =================================================================== custo real (sem novo debito)
def reconcile_costs(db, gen, *, pid: str | None = None) -> list[dict]:
    """Grava o custo REAL do fornecedor (billing-events) em attempts.confirmed_cost_usd. Separado do que o cliente pagou:
    so atua em tentativas JA decididas no ledger (production_charges), e nunca lanca debito."""
    sql = ("SELECT a.* FROM attempts a WHERE a.kind='workflow' AND a.simulated=0 AND a.remote_op_id IS NOT NULL "
           "AND a.cost_reconciled_at IS NULL AND EXISTS (SELECT 1 FROM production_charges c WHERE c.attempt_id=a.id)")
    args: tuple = ()
    if pid:
        sql += " AND a.production_id=?"
        args = (pid,)
    out = []
    for a in db.conn.execute(sql, args).fetchall():
        meta = json.loads(a["remote_meta_json"] or "{}")
        ids = list(dict.fromkeys([a["remote_op_id"], *[n.get("request_id") for n in (meta.get("nodes") or {}).values()
                                                       if n.get("request_id")]]))
        try:
            total = gen.reconcile_cost(ids)
        except (PermanentError, TransientError) as exc:
            out.append({"attempt": a["id"], "pid": a["production_id"], "status": "erro", "detail": str(exc)[:200]})
            continue
        if total is None:
            out.append({"attempt": a["id"], "pid": a["production_id"], "status": "sem_dados"})
            continue
        db.update_attempt(a["id"], confirmed_cost_usd=total, cost_reconciled_at=now(),
                          pricing_source=f"{a['pricing_source'] or ''} | custo real: billing-events da fal.ai (A CONFIRMAR)".strip(" |"))
        db.add_event(a["production_id"], "fal_cost_reconciled", f"custo real do fornecedor: US${total:.4f} (estimado US${a['estimated_cost_usd']:.4f})",
                     data={"attempt_id": a["id"], "confirmed_usd": total, "estimated_usd": a["estimated_cost_usd"]})
        out.append({"attempt": a["id"], "pid": a["production_id"], "status": "ok", "confirmed_usd": total,
                    "estimated_usd": a["estimated_cost_usd"]})
    return out


# =================================================================== retencao (so os intermediarios)
def _safe_intermediate(root: Path, target: Path) -> bool:
    """So vale um ARQUIVO dentro de <producao>/workflow/attempt_NN/ (nunca delivery/, nunca fora da producao, nunca
    result.json). Resolve links simbolicos antes de decidir."""
    try:
        t = target.resolve()
        base = (root / "workflow").resolve()
        rel = t.relative_to(base)
    except (ValueError, OSError):
        return False
    parts = rel.parts
    if len(parts) < 2 or not ATTEMPT_DIR.match(parts[0]) or "delivery" in parts or t.name in KEEP_IN_ATTEMPT:
        return False
    return t.is_file() and not target.is_symlink()


def cleanup_intermediates(data_dir: Path, db, days: int, *, now_dt: datetime | None = None) -> dict:
    """Apaga os artefatos BRUTOS (workflow/attempt_NN/*, menos result.json) de producoes do motor fal.ai encerradas ha
    mais de `days` dias. delivery/ e o historico nunca sao tocados."""
    now_dt = now_dt or datetime.now(timezone.utc)
    cutoff = now_dt - timedelta(days=days)
    removed = freed = 0
    for r in db.conn.execute("SELECT id, status, updated_at FROM productions WHERE engine='fal' AND status IN "
                             "('completed','cancelled','failed')").fetchall():
        if datetime.fromisoformat(r["updated_at"]) > cutoff:
            continue
        root = data_dir / "productions" / r["id"]
        wf = root / "workflow"
        if not wf.is_dir():
            continue
        for d in wf.iterdir():
            if not ATTEMPT_DIR.match(d.name) or d.is_symlink():
                continue
            for f in d.rglob("*"):
                if _safe_intermediate(root, f):
                    size = f.stat().st_size
                    f.unlink()
                    removed += 1
                    freed += size
    return {"removed": removed, "freed_bytes": freed}
