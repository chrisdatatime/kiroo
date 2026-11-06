"""Orquestrador: controla fluxo, dependências, estados, tentativas, orçamento e retomada.

Cada chamada a `run()` avança a produção até um portão humano, uma pausa (orçamento,
pedido do operador) ou a conclusão. Tudo é persistido; um novo processo continua de
onde parou, consultando operações remotas já enviadas em vez de reenviá-las.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .agents import creative, editing, visual_review
from .agents.product_prep import prepare_product
from .config import Settings
from .training import prompt_block, review_criteria
from .credits import InsufficientCredits, Ledger, fmt as fmt_credits
from .db import Database, now
from .ffmpeg import FFmpeg, FFmpegError
from .models import ProductInput, ProductSheet, ReviewDecision, ReviewResult, SceneSpec, Script
from .pricing import UnknownPrice
from .profiles import snapshot
from .providers.base import (ImageGenerator, ImageRequest, OpState, PermanentError, Planner, PlanningContext,
                             ProviderBillingError, Reviewer, TransientError, VideoGenerator, VideoRequest)

# Prefixo fixo do motivo de pausa: a interface reconhece e mostra a saída certa (recarregar a conta do provedor).
PROVIDER_BILLING_REASON = "provedor de IA sem saldo"
from .reports import write_reports
from .states import TERMINAL, ProductionStatus as PS, SceneStatus as SS
from .storage import ProductionStorage, sha256_file

log = logging.getLogger("studio")

MAX_TRANSIENT_RETRIES = 4
BACKOFF_BASE_S = 2.0
BACKOFF_MAX_S = 120.0
REVIEW_COST_ESTIMATE_USD = 0.01  # reserva por revisão real quando o uso ainda não é conhecido


GO_AHEAD_ORDER = {"none": 0, "images": 1, "videos": 2, "all": 3}

# Autonomia do estúdio (piloto):
#   manual     — você aprova tudo; reprovações do revisor vêm para você (sem refazer sozinho)
#   assistido  — refaz o que o revisor reprovar e aprova o que ele aprovar; para nas dúvidas
#   automatico — segue até o vídeo montado, aprovando também o inconclusivo; para no limite e na revisão final
#   classico   — comportamento original da CLI/painel: refaz sozinho, nunca aprova sozinho
AUTONOMY = ("manual", "assistido", "automatico", "classico")
AUTO_APPROVE = {"assistido": {ReviewDecision.APPROVED}, "automatico": {ReviewDecision.APPROVED, ReviewDecision.INCONCLUSIVE}}
_REVIEW_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="revisao")


class BudgetExceeded(Exception):
    pass


class OrchestratorError(Exception):
    pass


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _parse_ts(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts) if ts else None


class Orchestrator:
    def __init__(self, settings: Settings, db: Database, *, image_gen: ImageGenerator, video_gen: VideoGenerator,
                 planner: Planner, reviewer: Reviewer, ffmpeg: FFmpeg, sleep=time.sleep, base_dir: Path | None = None):
        self.s = settings
        self.db = db
        self.image_gen = image_gen
        self.video_gen = video_gen
        self.planner = planner
        self.reviewer = reviewer
        self.ffmpeg = ffmpeg
        self.sleep = sleep
        self.base_dir = base_dir or Path.cwd()
        self._review_jobs: dict = {}
        self._review_holds: dict = {}
        self._ledger: Ledger | None = None
        # Desligamento gracioso: o servidor liga este evento; o laço para entre duas etapas (nunca no meio de uma
        # chamada paga) e `stopped` avisa que a produção foi interrompida e não concluída.
        self.stop_event = None
        self.stopped = False

    # ================================================================ criação
    def create_production(self, product: ProductInput, *, format_id: str, art_direction: str, presenter: str,
                          budget_usd: float, go_ahead: str = "all", autonomy: str = "classico",
                          workspace_id: str | None = None) -> str:
        """go_ahead="none" exige liberação explícita (set_go_ahead) antes de gerar imagens e antes dos vídeos."""
        if go_ahead not in GO_AHEAD_ORDER:
            raise OrchestratorError("liberação inválida")
        if autonomy not in AUTONOMY:
            raise OrchestratorError("autonomia inválida")
        mode = self.s.mode
        if budget_usd < 0:
            raise OrchestratorError("orçamento não pode ser negativo")
        if mode == "real":
            if not self.s.allow_paid_calls:
                raise OrchestratorError("modo real exige STUDIO_ALLOW_PAID_CALLS=true")
            if not self.s.gemini_api_key:
                raise OrchestratorError("modo real exige GEMINI_API_KEY")
            if budget_usd <= 0:
                raise OrchestratorError("modo real exige orçamento > 0 definido pelo operador")
        profiles = snapshot(self.s.profiles_dir, {"presenter": presenter, "art_direction": art_direction,
                                                  "format": format_id})
        pid = self.db.create_production(mode=mode, format_id=format_id, product=product.model_dump(mode="json"),
                                        profiles=profiles, budget_usd=budget_usd, go_ahead=go_ahead,
                                        autonomy=autonomy)
        if workspace_id:
            self.db.update_production(pid, workspace_id=workspace_id)
            # A produção congela as versões de treinamento em vigor agora; versões novas valem só para as próximas.
            from .training import Training, default_edit_style
            snap = Training(self.db, self.s.data_dir).snapshot(workspace_id)
            self.db.update_production(pid, training_json=json.dumps(snap, ensure_ascii=False))
            style = default_edit_style(snap)
            if style:
                self.db.update_production(pid, edit_style=style)
        st = self._storage(pid)
        st.write_json("profiles_snapshot.json", profiles)
        st.write_json("inputs/product_input.json", product.model_dump(mode="json"))
        log.info("[%s] produção criada (modo %s)", pid, mode)
        return pid

    def update_product(self, pid: str, product: ProductInput) -> None:
        """Substitui a ficha. A revalidação e o novo roteiro invalidam só as cenas cujo insumo mudou."""
        row = self.db.production(pid)
        if PS(row["status"]) in TERMINAL:
            raise OrchestratorError("produção encerrada")
        self.db.update_production(pid, product_json=json.dumps(product.model_dump(mode="json"), ensure_ascii=False))
        self._storage(pid).write_json("inputs/product_input.json", product.model_dump(mode="json"))
        self.db.add_event(pid, "product_updated", "ficha substituída pelo operador")
        if PS(row["status"]) not in {PS.RECEIVED, PS.PAUSED}:
            self.db.set_production_status(pid, PS.AWAITING_REFERENCES, "ficha atualizada: revalidar")

    # =============================================================== execução
    def run(self, pid: str, *, wait: bool = True, max_wait_s: float | None = None) -> str:
        row = self.db.production(pid)
        if row["mode"] != self.s.mode:
            raise OrchestratorError(f"produção em modo {row['mode']}, mas o ambiente está em modo {self.s.mode}")
        deadline = time.monotonic() + max_wait_s if max_wait_s else None
        try:
            self._loop(pid, wait, deadline)
        except FFmpegError as exc:
            status = PS(self.db.production(pid)["status"])
            if status not in TERMINAL and status != PS.PAUSED:
                self.db.set_production_status(pid, PS.PAUSED, f"erro de FFmpeg: {exc}")
        except ProviderBillingError as exc:  # roteiro/revisão (chamadas de texto) também podem esbarrar no saldo
            self._pause_billing(pid, exc)
        finally:
            self._settle(pid)
        write_reports(self.db, pid, self._storage(pid))
        return self.db.production(pid)["status"]

    def _loop(self, pid: str, wait: bool, deadline: float | None) -> None:
        while True:
            if self.stop_event is not None and self.stop_event.is_set():
                self.stopped = True
                break
            self._settle(pid)
            status = PS(self.db.production(pid)["status"])
            if status in TERMINAL or status in {PS.PAUSED, PS.AWAITING_FINAL_REVIEW}:
                break
            if status in {PS.RECEIVED, PS.AWAITING_REFERENCES}:
                if not self._prepare(pid):
                    break
            elif status == PS.VALIDATED:
                if not self._script(pid):
                    break
            elif status == PS.SCRIPTED:
                self.db.set_production_status(pid, PS.PRODUCING)
            elif status == PS.PRODUCING:
                outcome = self._step_scenes(pid)
                if outcome == "done":
                    self.db.set_production_status(pid, PS.EDITING, "todas as cenas aprovadas")
                elif outcome == "waiting":
                    if not wait or (deadline and time.monotonic() > deadline):
                        break
                    self.sleep(self.s.poll_interval_s)
                elif outcome == "progress":
                    continue
                else:  # idle (aguardando humano) ou paused
                    break
            elif status == PS.EDITING:
                self._edit(pid)

    # ============================================================== preparação
    def _storage(self, pid: str) -> ProductionStorage:
        return ProductionStorage(self.s.data_dir, pid)

    def _profiles(self, pid: str) -> dict:
        return json.loads(self.db.production(pid)["profiles_json"])

    def _sheet(self, pid: str) -> ProductSheet:
        raw = self.db.production(pid)["sheet_json"]
        if not raw:
            raise OrchestratorError("ficha ainda não validada")
        return ProductSheet.model_validate_json(raw)

    def _training(self, pid: str) -> dict | None:
        row = self.db.production(pid)
        raw = row["training_json"] if "training_json" in row.keys() else None
        return json.loads(raw) if raw else None

    def _script_obj(self, pid: str) -> Script:
        return Script.model_validate_json(self.db.production(pid)["script_json"])

    def _prepare(self, pid: str) -> bool:
        row = self.db.production(pid)
        profiles = self._profiles(pid)
        product = ProductInput.model_validate_json(row["product_json"])
        st = self._storage(pid)
        mode = profiles["format"]["data"]["presenter_mode"]
        sheet = prepare_product(product, st, profiles["presenter"]["data"], mode, self.s.assets_dir, self.base_dir)
        self.db.update_production(pid, sheet_json=sheet.model_dump_json())
        st.write_json("sheet.json", sheet.model_dump(mode="json"))
        for issue in sheet.issues:
            self.db.add_event(pid, "sheet_issue", issue.message, data={"code": issue.code, "blocking": issue.blocking})
        if sheet.blocking_issues:
            reason = "; ".join(i.message for i in sheet.blocking_issues)
            self.db.set_production_status(pid, PS.AWAITING_REFERENCES, reason)
            return False
        self.db.set_production_status(pid, PS.VALIDATED, "ficha validada")
        return True

    def _scene_fingerprint(self, spec: SceneSpec, sheet: ProductSheet) -> str:
        product_refs = sorted(r.sha256 for r in sheet.product.references if r.usable_for_generation)
        presenter = sorted(a["sha256"] for a in sheet.presenter_assets.values())
        return _hash({"spec": spec.model_dump(mode="json"), "product_refs": product_refs, "presenter": presenter})

    def _script(self, pid: str) -> bool:
        profiles = self._profiles(pid)
        sheet = self._sheet(pid)
        draft = creative.build_draft(sheet, profiles)
        ctx = PlanningContext(draft=draft, product_sheet_json=sheet.model_dump_json(),
                              art_direction=profiles["art_direction"]["data"],
                              presenter_mode=profiles["format"]["data"]["presenter_mode"],
                              training=prompt_block(self._training(pid), "theo") + prompt_block(self._training(pid), "nina"))
        try:
            script, meta = self._call_text("plan", None, lambda: self.planner.refine_script(ctx), self.planner,
                                           pid=pid, prompt="refine_script")
        except BudgetExceeded:
            return False
        except (TransientError, PermanentError) as exc:
            self.db.add_event(pid, "planner_failed", f"planejamento por IA falhou; usando rascunho do template: {exc}")
            script = draft.model_copy(update={"planner": f"template (IA falhou: {type(exc).__name__})"})
        script = script.model_copy(update={"simulated": self.planner.simulated})
        errors = creative.validate_script(script, profiles, sheet)
        if errors and script is not draft:
            self.db.add_event(pid, "script_rejected", "roteiro do planner inválido; usando rascunho", data={"errors": errors})
            script = draft.model_copy(update={"planner": "template (saída da IA reprovada na validação)",
                                              "simulated": self.planner.simulated})
            errors = creative.validate_script(script, profiles, sheet)
        if errors:
            self.db.set_production_status(pid, PS.FAILED, "roteiro inválido: " + "; ".join(errors))
            return False

        st = self._storage(pid)
        self.db.update_production(pid, script_json=script.model_dump_json())
        st.write_json("script.json", script.model_dump(mode="json"))
        st.write_text("script.md", creative.render_markdown(script, sheet, self.planner.simulated))
        for s in script.scenes:
            st.write_text(f"prompts/scene_{s.index}_image_{self.image_gen.provider}.txt", s.image_prompt)
            st.write_text(f"prompts/scene_{s.index}_animation_{self.video_gen.provider}.txt", s.animation_prompt)

        existing = {r["idx"]: r for r in self.db.scenes(pid)}
        for s in script.scenes:
            fp = self._scene_fingerprint(s, sheet)
            prev = existing.get(s.index)
            if prev is not None and prev["spec_hash"] != fp:
                self.db.upsert_scene(pid, s.index, s.model_dump_json(), fp)
                self._reset_scene(pid, s.index, "roteiro/referências mudaram")
            else:
                self.db.upsert_scene(pid, s.index, s.model_dump_json(), fp)
        self.db.set_production_status(pid, PS.SCRIPTED, f"roteiro com {len(script.scenes)} cenas ({script.planner})")
        return True

    # ================================================================== cenas
    def _spec(self, row) -> SceneSpec:
        return SceneSpec.model_validate_json(row["spec_json"])

    def _reset_scene(self, pid: str, idx: int, reason: str, *, cascade: bool = True) -> None:
        self.db.supersede_attempts(pid, idx, "image", reason)
        self.db.supersede_attempts(pid, idx, "video", reason)
        self.db.set_scene_status(pid, idx, SS.PENDING, reason, current_image_attempt=None, approved_image_attempt=None,
                                 current_video_attempt=None, approved_video_attempt=None, image_correction=None,
                                 video_correction=None)
        if cascade:
            for other in self.db.scenes(pid):
                if idx in self._spec(other).image_dependencies() and other["status"] != SS.PENDING:
                    self._reset_scene(pid, other["idx"], f"dependência: cena {idx} mudou")

    def _step_scenes(self, pid: str) -> str:
        outcomes = []
        for row in self.db.scenes(pid):
            if PS(self.db.production(pid)["status"]) != PS.PRODUCING:
                return "paused"
            row = self.db.scene(pid, row["idx"])
            status = SS(row["status"])
            go = GO_AHEAD_ORDER[self.db.production(pid)["go_ahead"]]
            if status == SS.PENDING:
                deps = self._spec(row).image_dependencies()
                if go >= GO_AHEAD_ORDER["images"] and all(self.db.scene(pid, d)["approved_image_attempt"] for d in deps):
                    self.db.set_scene_status(pid, row["idx"], SS.GENERATING_IMAGE, "dependências atendidas")
                    outcomes.append("progress")
            elif status == SS.GENERATING_IMAGE:
                outcomes.append(self._drive(pid, row["idx"], "image"))
            elif status == SS.IMAGE_APPROVED and go >= GO_AHEAD_ORDER["videos"]:
                self.db.set_scene_status(pid, row["idx"], SS.GENERATING_VIDEO, "imagem aprovada")
                outcomes.append("progress")
            elif status == SS.GENERATING_VIDEO:
                outcomes.append(self._drive(pid, row["idx"], "video"))
        if all(r["status"] == SS.VIDEO_APPROVED for r in self.db.scenes(pid)):
            return "done"
        for o in ("paused", "progress", "waiting"):
            if o in outcomes:
                return o
        return "idle"

    # ---------------------------------------------------------- tentativas
    def _gen(self, kind: str):
        return self.image_gen if kind == "image" else self.video_gen

    def _resolve_refs(self, pid: str, spec: SceneSpec, sheet: ProductSheet) -> list[dict]:
        st = self._storage(pid)
        refs: list[dict] = []
        for key in spec.references:
            parts = key.split(":")
            if parts[0] == "product":
                for r in sheet.product.references:
                    if r.usable_for_generation and (parts[1] == "all" or r.role == parts[1]):
                        refs.append({"key": f"product:{r.role}", "path": r.stored_path, "sha256": r.sha256})
            elif parts[0] == "presenter":
                for slot, a in sheet.presenter_assets.items():
                    refs.append({"key": f"presenter:{slot}", "path": a["stored_path"], "sha256": a["sha256"]})
            elif parts[0] == "scene":
                dep = self.db.scene(pid, int(parts[1]))
                att = self.db.attempt(dep["approved_image_attempt"])
                refs.append({"key": key, "path": att["output_path"], "sha256": att["output_sha256"]})
        for r in refs:
            st.path(r["path"])  # valida que está dentro da produção
        return refs

    def _build_request(self, pid: str, idx: int, kind: str):
        row = self.db.scene(pid, idx)
        spec = self._spec(row)
        script = self._script_obj(pid)
        st = self._storage(pid)
        correction = row[f"{kind}_correction"]
        if kind == "image":
            refs = self._resolve_refs(pid, spec, self._sheet(pid))
            prompt = spec.image_prompt
            for r in refs:
                if r["key"].startswith("presenter:"):
                    usage = self._sheet(pid).presenter_assets[r["key"].split(":", 1)[1]]["usage_en"]
                    prompt += f"\nPresenter reference image: {usage}"
            prompt += prompt_block(self._training(pid), "iris")
            if correction:
                prompt += f"\n\nCORRECTION REQUESTED AFTER REVIEW (apply strictly): {correction}"
            req = ImageRequest(prompt=prompt, reference_images=[st.path(r["path"]) for r in refs],
                               aspect_ratio=script.aspect_ratio, image_size=self.s.image_size)
        else:
            img = self.db.attempt(row["approved_image_attempt"])
            refs = [{"key": "start_image", "path": img["output_path"], "sha256": img["output_sha256"]}]
            prompt = spec.animation_prompt
            prompt += prompt_block(self._training(pid), "lia")
            if correction:
                prompt += f"\n\nCORRECTION REQUESTED AFTER REVIEW (apply strictly): {correction}"
            req = VideoRequest(prompt=prompt, start_image=st.path(img["output_path"]), aspect_ratio=script.aspect_ratio,
                               resolution=self.s.video_resolution, target_duration_s=spec.target_duration_s)
        return req, refs

    def _request_from_attempt(self, pid: str, att) -> ImageRequest | VideoRequest:
        st = self._storage(pid)
        refs = json.loads(att["references_json"])
        params = json.loads(att["params_json"])
        if att["kind"] == "image":
            return ImageRequest(prompt=att["prompt"], reference_images=[st.path(r["path"]) for r in refs],
                                aspect_ratio=params["aspect_ratio"], image_size=params["image_size"])
        spec = self._spec(self.db.scene(pid, att["scene_idx"]))
        return VideoRequest(prompt=att["prompt"], start_image=st.path(refs[0]["path"]),
                            aspect_ratio=params["aspect_ratio"], resolution=params["resolution"],
                            target_duration_s=spec.target_duration_s)

    def committed_cost(self, pid: str) -> float:
        total = 0.0
        for a in self.db.attempts(pid):
            if a["simulated"] or a["confirmed_cost_usd"] is None:
                total += a["estimated_cost_usd"] or 0.0
            else:
                total += a["confirmed_cost_usd"]
        return round(total, 4)

    def _check_budget(self, pid: str, estimate: float, what: str) -> None:
        prod = self.db.production(pid)
        budget = prod["budget_usd"]
        committed = self.committed_cost(pid)
        reason = None
        if committed + estimate > budget + 1e-9:
            reason = (f"orçamento insuficiente para {what}: comprometido US${committed:.4f} + estimado "
                      f"US${estimate:.4f} > limite US${budget:.2f}")
        elif prod["mode"] == "real" and estimate > 0:
            from .spend import month_real_spend
            wid = prod["workspace_id"] if "workspace_id" in prod.keys() else None
            ws = self.db.conn.execute("SELECT * FROM workspaces WHERE id=?", (wid,)).fetchone() if wid else None
            cap = ws["monthly_cap_usd"] if ws else self.s.monthly_cap_usd  # teto e gasto são do workspace
            spent = month_real_spend(self.db, workspace_id=wid)
            if cap <= 0:
                reason = "teto mensal de gastos não definido (desligue o DEMO pela interface ou defina STUDIO_MONTHLY_CAP_USD)"
            elif spent + estimate > cap + 1e-9:
                reason = (f"teto mensal atingido para {what}: gasto do mês US${spent:.4f} + estimado "
                          f"US${estimate:.4f} > teto US${cap:.2f}")
        if reason:
            self.db.set_production_status(pid, PS.PAUSED, reason)
            log.warning("[%s] %s", pid, reason)
            raise BudgetExceeded(reason)

    # ------------------------------------------------------- créditos (Fase C)
    def _wid(self, pid: str) -> str | None:
        prod = self.db.production(pid)
        return prod["workspace_id"] if "workspace_id" in prod.keys() else None

    def ledger(self) -> Ledger:
        if self._ledger is None:
            self._ledger = Ledger(self.db)
        return self._ledger

    def _hold(self, pid: str, estimate: float, what: str, stage: str) -> str | None:
        """Orçamento + teto do mês + reserva de créditos do workspace, nessa ordem. Sem saldo → pausa."""
        self._check_budget(pid, estimate, what)
        wid = self._wid(pid)
        if wid is None or estimate <= 0 or self.db.production(pid)["mode"] != "real":
            return None  # DEMO e produções sem workspace (CLI antiga) não usam créditos
        try:
            return self.ledger().hold(wid, pid, estimate, stage)
        except InsufficientCredits as exc:
            reason = (f"saldo de créditos insuficiente para {what}: saldo {fmt_credits(exc.balance_cc)} créditos, "
                      f"estimado {fmt_credits(exc.needed_cc)} créditos (estimado US${estimate:.4f})")
            self.db.set_production_status(pid, PS.PAUSED, reason)
            log.warning("[%s] %s", pid, reason)
            raise BudgetExceeded(reason) from exc

    def _settle(self, pid: str) -> None:
        if self._wid(pid) is not None:
            self.ledger().settle(pid)

    def _drive(self, pid: str, idx: int, kind: str) -> str:
        row = self.db.scene(pid, idx)
        att_id = row[f"current_{kind}_attempt"]
        att = self.db.attempt(att_id) if att_id else None
        if att is not None and att["superseded"]:
            att = None

        if att is None or att["status"] == "failed":
            return self._start_attempt(pid, idx, kind)
        if att["status"] == "created":
            retry_at = _parse_ts(att["next_retry_at"])
            if retry_at and retry_at > datetime.now(timezone.utc):
                return "waiting"
            return self._submit(pid, att["id"])
        if att["status"] == "submitted":
            retry_at = _parse_ts(att["next_retry_at"])
            if retry_at and retry_at > datetime.now(timezone.utc):
                return "waiting"
            return self._poll(pid, att["id"])
        if att["status"] == "succeeded":
            return self._auto_review(pid, idx, kind, att["id"])
        raise OrchestratorError(f"estado de tentativa inesperado: {att['status']}")

    def _start_attempt(self, pid: str, idx: int, kind: str) -> str:
        row = self.db.scene(pid, idx)
        gen_status = SS.GENERATING_IMAGE if kind == "image" else SS.GENERATING_VIDEO
        limit = (self.s.max_image_attempts if kind == "image" else self.s.max_video_attempts) + row[f"extra_{kind}_attempts"]
        used = self.db.count_generation_attempts(pid, idx, kind)
        if used >= limit:
            self.db.set_scene_status(pid, idx, SS.BLOCKED, f"limite de {limit} tentativas de {kind} atingido")
            return "idle"

        gen = self._gen(kind)
        req, refs = self._build_request(pid, idx, kind)
        params = gen.params(req)
        input_hash = _hash({"provider": gen.provider, "model": gen.model, "kind": kind, "prompt": req.prompt,
                            "params": params, "refs": sorted(r["sha256"] for r in refs)})
        reusable = self.db.reusable_attempt(pid, kind, input_hash)
        if reusable is not None:
            self.db.update_scene(pid, idx, **{f"current_{kind}_attempt": reusable["id"]})
            self.db.add_event(pid, "attempt_reused", f"{kind}: resultado idêntico já pago reaproveitado",
                              scene_idx=idx, data={"attempt_id": reusable["id"]})
            return "progress"
        if self.db.inflight_count() >= self.s.max_inflight_ops:
            return "waiting"
        try:
            estimate, source = gen.estimate_cost(req)
        except UnknownPrice as exc:
            self.db.set_scene_status(pid, idx, SS.BLOCKED, f"sem preço para estimar custo: {exc}")
            return "idle"
        try:
            hold = self._hold(pid, estimate, f"{kind} da cena {idx}", kind)
        except BudgetExceeded:
            return "paused"
        att_id = self.db.create_attempt(production_id=pid, scene_idx=idx, kind=kind, provider=gen.provider,
                                        model=gen.model, simulated=gen.simulated, input_hash=input_hash,
                                        prompt=req.prompt, params=params, references=refs,
                                        estimated_cost_usd=estimate, pricing_source=source)
        if hold:
            self.ledger().attach(hold, att_id)
        self.db.set_scene_status(pid, idx, gen_status, "", **{f"current_{kind}_attempt": att_id})
        return self._submit(pid, att_id)

    def _submit(self, pid: str, att_id: str) -> str:
        att = self.db.attempt(att_id)
        gen = self._gen(att["kind"])
        req = self._request_from_attempt(pid, att)
        try:
            op_id = gen.submit(req)
        except TransientError as exc:
            return self._transient(pid, att, exc, "envio")
        except ProviderBillingError as exc:
            return self._provider_billing(pid, att, exc)
        except PermanentError as exc:
            self.db.update_attempt(att_id, status="failed", error=str(exc)[:1000], error_permanent=1,
                                   finished_at=now(), estimated_cost_usd=0.0,
                                   pricing_source=f"{att['pricing_source']} | recusado no envio: sem custo estimado")
            self.db.add_event(pid, "attempt_failed", f"{att['kind']} #{att['attempt_no']} falha permanente no envio: {exc}",
                              scene_idx=att["scene_idx"])
            # O provedor recusou o pedido em si: repetir igual só repete a recusa. Precisa de decisão/correção.
            self.db.set_scene_status(pid, att["scene_idx"], SS.BLOCKED,
                                     f"pedido recusado pelo provedor: {str(exc)[:300]}")
            return "idle"
        self.db.update_attempt(att_id, status="submitted", remote_op_id=op_id, submitted_at=now(), next_retry_at=None)
        self.db.add_event(pid, "attempt_submitted", f"{att['kind']} #{att['attempt_no']} enviado",
                          scene_idx=att["scene_idx"], data={"remote_op_id": op_id})
        log.info("[%s][cena %s] %s enviado (op %s)", pid, att["scene_idx"], att["kind"], op_id)
        return "progress"

    def _provider_billing(self, pid: str, att, exc: Exception) -> str:
        """Conta do provedor sem saldo: o pedido está certo, então a tentativa não conta (fica substituída),
        nada é cobrado e a produção pausa; ao retomar, a cena gera de novo do zero."""
        self.db.update_attempt(att["id"], status="failed", error=str(exc)[:1000], error_permanent=0, superseded=1,
                               finished_at=now(), estimated_cost_usd=0.0)
        self.db.add_event(pid, "attempt_failed", f"{att['kind']} #{att['attempt_no']}: {PROVIDER_BILLING_REASON}",
                          scene_idx=att["scene_idx"])
        kind = att["kind"]
        self.db.set_scene_status(pid, att["scene_idx"], SS.GENERATING_IMAGE if kind == "image" else SS.GENERATING_VIDEO,
                                 PROVIDER_BILLING_REASON, **{f"current_{kind}_attempt": None})
        self._pause_billing(pid, exc)
        return "paused"

    def _pause_billing(self, pid: str, exc: Exception) -> None:
        status = PS(self.db.production(pid)["status"])
        if status not in TERMINAL and status != PS.PAUSED:
            self.db.set_production_status(pid, PS.PAUSED, f"{PROVIDER_BILLING_REASON}: {str(exc)[:300]}")

    def _transient(self, pid: str, att, exc: Exception, stage: str) -> str:
        retries = att["transient_retries"] + 1
        if retries > MAX_TRANSIENT_RETRIES:
            self.db.update_attempt(att["id"], status="failed", error=f"{stage}: {exc}"[:1000], error_permanent=0,
                                   finished_at=now(), transient_retries=retries)
            self.db.add_event(pid, "attempt_failed", f"{att['kind']} #{att['attempt_no']}: falhas transitórias esgotadas",
                              scene_idx=att["scene_idx"])
            return "progress"
        delay = min(BACKOFF_BASE_S * 2 ** (retries - 1), BACKOFF_MAX_S)
        retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec="seconds")
        self.db.update_attempt(att["id"], transient_retries=retries, next_retry_at=retry_at, error=f"{stage}: {exc}"[:1000])
        self.db.add_event(pid, "transient_error", f"{att['kind']} #{att['attempt_no']} {stage}: {exc}; nova espera {delay:.0f}s",
                          scene_idx=att["scene_idx"])
        return "waiting"

    def _poll(self, pid: str, att_id: str) -> str:
        att = self.db.attempt(att_id)
        gen = self._gen(att["kind"])
        try:
            result = gen.poll(att["remote_op_id"])
        except TransientError as exc:
            return self._transient(pid, att, exc, "consulta")
        except ProviderBillingError as exc:
            return self._provider_billing(pid, att, exc)
        except PermanentError as exc:
            # Pedido recusado (ex.: geração síncrona em segundo plano): repetir igual não adianta.
            self.db.update_attempt(att_id, status="failed", error=str(exc)[:1000], error_permanent=1, finished_at=now(),
                                   estimated_cost_usd=0.0)
            self.db.add_event(pid, "attempt_failed", f"{att['kind']} #{att['attempt_no']} recusado: {exc}", scene_idx=att["scene_idx"])
            self.db.set_scene_status(pid, att["scene_idx"], SS.BLOCKED, f"pedido recusado pelo provedor: {str(exc)[:300]}")
            return "idle"
        if result.state == OpState.RUNNING:
            # Próxima consulta só após o intervalo, mesmo que outras cenas sigam avançando.
            next_check = datetime.now(timezone.utc) + timedelta(seconds=self.s.poll_interval_s)
            self.db.update_attempt(att_id, next_retry_at=next_check.isoformat(timespec="seconds"))
            return "waiting"
        if result.state == OpState.FAILED:
            self.db.update_attempt(att_id, status="failed", error=(result.error or "")[:1000],
                                   error_permanent=int(result.permanent), finished_at=now(),
                                   usage_json=json.dumps(result.usage))
            self.db.add_event(pid, "attempt_failed", f"{att['kind']} #{att['attempt_no']}: {result.error}",
                              scene_idx=att["scene_idx"])
            return "progress"
        st = self._storage(pid)
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "video/mp4": ".mp4"}.get(
            result.mime_type or "", ".png" if att["kind"] == "image" else ".mp4")
        prefix = "SIMULADO_" if att["simulated"] else ""
        folder = "images" if att["kind"] == "image" else "videos"
        rel = f"scenes/scene_{att['scene_idx']}/{folder}/{prefix}attempt_{att['attempt_no']:02d}{ext}"
        path = st.write_bytes(rel, result.data or b"")
        self.db.update_attempt(att_id, status="succeeded", output_path=rel, output_sha256=sha256_file(path),
                               finished_at=now(), confirmed_cost_usd=result.confirmed_cost_usd,
                               usage_json=json.dumps(result.usage), error=None, next_retry_at=None)
        self.db.add_event(pid, "attempt_succeeded", f"{att['kind']} #{att['attempt_no']} → {rel}", scene_idx=att["scene_idx"])
        return self._auto_review(pid, att["scene_idx"], att["kind"], att_id)

    # ---------------------------------------------------------------- revisão
    def _call_text(self, kind: str, scene_idx, fn, provider, *, pid: str | None = None, prompt: str = ""):
        """Executa uma chamada de texto/visão registrando custo como tentativa auditável."""
        estimate = 0.0 if provider.simulated else REVIEW_COST_ESTIMATE_USD
        hold = self._hold(pid, estimate, kind, kind) if pid is not None else None
        try:
            result, meta = fn()
        except BaseException:
            self.ledger().release(hold, f"{kind}: chamada falhou")
            raise
        if pid is not None:
            self._record_text_call(pid, kind, scene_idx, provider, meta, prompt, hold=hold)
        return result, meta

    def _record_text_call(self, pid: str, kind: str, scene_idx, provider, meta: dict, prompt: str,
                          hold: str | None = None) -> None:
        estimate = 0.0 if provider.simulated else REVIEW_COST_ESTIMATE_USD
        est = meta.get("estimated_cost_usd", estimate)
        src = meta.get("pricing_source", "SIMULADO — sem custo" if provider.simulated else "reserva fixa por chamada")
        aid = self.db.create_attempt(production_id=pid, scene_idx=scene_idx, kind=kind, provider=provider.provider,
                                     model=provider.model, simulated=provider.simulated,
                                     input_hash=_hash([kind, scene_idx, now()]), prompt=prompt, params={},
                                     references=[], estimated_cost_usd=est, pricing_source=src)
        self.db.update_attempt(aid, status="succeeded", submitted_at=now(), finished_at=now(),
                               usage_json=json.dumps(meta.get("usage", {}), default=str))
        if hold:
            self.ledger().attach(hold, aid)
            self._settle(pid)

    def _review_fn(self, pid: str, idx: int, kind: str, att):
        spec = self._spec(self.db.scene(pid, idx))
        extra = review_criteria(self._training(pid))
        if extra:
            spec = spec.model_copy(update={"approval_criteria": [*spec.approval_criteria, *extra]})
        st = self._storage(pid)
        output = st.path(att["output_path"])
        aspect = self._script_obj(pid).aspect_ratio
        if kind == "image":
            refs = [st.path(r["path"]) for r in json.loads(att["references_json"])]
            return lambda: visual_review.review_image(self.reviewer, self.ffmpeg, spec, output, refs, aspect)
        img = self.db.attempt(self.db.scene(pid, idx)["approved_image_attempt"])
        frames_dir = st.dir(f"scenes/scene_{idx}/frames/attempt_{att['attempt_no']:02d}")
        img_path = st.path(img["output_path"])
        return lambda: visual_review.review_video(self.reviewer, self.ffmpeg, spec, output, img_path, frames_dir, aspect)

    def _autonomy(self, pid: str) -> str:
        row = self.db.production(pid)
        return row["autonomy"] if "autonomy" in row.keys() else "classico"

    def _auto_review(self, pid: str, idx: int, kind: str, att_id: str) -> str:
        existing = [r for r in self.db.reviews_for_attempt(att_id) if r["reviewer"].startswith("auto:")]
        att = self.db.attempt(att_id)
        if existing:
            result = ReviewResult.model_validate_json(existing[-1]["result_json"])
        else:
            # Revisões reais rodam em paralelo (sem travar as outras cenas); a simulada é instantânea.
            job = self._review_jobs.get(att_id)
            if job is None:
                try:
                    hold = self._hold(pid, 0.0 if self.reviewer.simulated else REVIEW_COST_ESTIMATE_USD,
                                      f"revisão de {kind}", f"review_{kind}")
                except BudgetExceeded:
                    return "paused"
                self._review_holds[att_id] = hold
                fn = self._review_fn(pid, idx, kind, att)
                if self.reviewer.simulated:
                    job = Future()
                    try:
                        job.set_result(fn())
                    except Exception as exc:  # noqa: BLE001
                        job.set_exception(exc)
                else:
                    self._review_jobs[att_id] = _REVIEW_POOL.submit(fn)
                    return "waiting"
            elif not job.done():
                return "waiting"
            self._review_jobs.pop(att_id, None)
            hold = self._review_holds.pop(att_id, None)
            try:
                result, meta = job.result()
                self._record_text_call(pid, f"review_{kind}", idx, self.reviewer, meta, f"review {att_id}", hold=hold)
            except Exception as exc:  # noqa: BLE001 — revisão é auxiliar: falha vira "inconclusivo"
                self.ledger().release(hold, f"revisão de {kind} falhou")
                result = ReviewResult(decision=ReviewDecision.INCONCLUSIVE, issues=[f"revisão automática falhou: {exc}"],
                                      method="falha na chamada", reviewer=self.reviewer.provider)
            self.db.add_review(production_id=pid, scene_idx=idx, attempt_id=att_id, stage=kind,
                               reviewer=f"auto:{self.reviewer.provider}:{self.reviewer.model}",
                               decision=result.decision, result=result.model_dump(mode="json"))

        autonomy = self._autonomy(pid)
        if result.decision == ReviewDecision.REJECTED and autonomy != "manual":
            row = self.db.scene(pid, idx)
            limit = (self.s.max_image_attempts if kind == "image" else self.s.max_video_attempts) + row[f"extra_{kind}_attempts"]
            if self.db.count_generation_attempts(pid, idx, kind) < limit:
                fix = result.suggested_fix or "; ".join(result.issues)
                self.db.update_scene(pid, idx, **{f"current_{kind}_attempt": None, f"{kind}_correction": fix})
                self.db.add_event(pid, "auto_correction", f"{kind} reprovado na revisão automática; nova tentativa: {fix}",
                                  scene_idx=idx)
                return "progress"
            self.db.set_scene_status(pid, idx, SS.BLOCKED, f"{kind} reprovado e tentativas esgotadas")
            return "idle"
        target = SS.AWAITING_IMAGE_APPROVAL if kind == "image" else SS.AWAITING_VIDEO_APPROVAL
        self.db.set_scene_status(pid, idx, target, f"revisão automática: {result.decision}")
        if result.decision in AUTO_APPROVE.get(autonomy, set()):
            self.approve(pid, idx, kind, f"aprovado pelo piloto ({autonomy}) após revisão automática: {result.decision}",
                         reviewer="piloto")
        return "progress"

    # ========================================================= ações humanas
    def _reopen_production(self, pid: str) -> None:
        status = PS(self.db.production(pid)["status"])
        if status in {PS.EDITING, PS.AWAITING_FINAL_REVIEW}:
            self.db.set_production_status(pid, PS.PRODUCING, "cena reaberta pelo operador")

    def approve(self, pid: str, idx: int, stage: str, note: str = "", reviewer: str = "human") -> None:
        row = self.db.scene(pid, idx)
        status = SS(row["status"])
        att_id = row[f"current_{stage}_attempt"]
        expected = SS.AWAITING_IMAGE_APPROVAL if stage == "image" else SS.AWAITING_VIDEO_APPROVAL
        if status not in {expected, SS.BLOCKED} or not att_id or self.db.attempt(att_id)["status"] != "succeeded":
            raise OrchestratorError(f"cena {idx} não tem {stage} aguardando aprovação (estado: {status})")
        self.db.add_review(production_id=pid, scene_idx=idx, attempt_id=att_id, stage=stage, reviewer=reviewer,
                           decision=ReviewDecision.APPROVED, result={"note": note})
        if stage == "image":
            previous = row["approved_image_attempt"]
            self.db.set_scene_status(pid, idx, SS.IMAGE_APPROVED, "aprovada pelo operador",
                                     approved_image_attempt=att_id, image_correction=None)
            if previous and previous != att_id:
                for other in self.db.scenes(pid):
                    if idx in self._spec(other).image_dependencies() and other["status"] != SS.PENDING:
                        self._reset_scene(pid, other["idx"], f"imagem aprovada da cena {idx} mudou")
        else:
            self.db.set_scene_status(pid, idx, SS.VIDEO_APPROVED, "aprovado pelo operador",
                                     approved_video_attempt=att_id, video_correction=None)

    def reject(self, pid: str, idx: int, stage: str, note: str, *, redo_image: bool = False) -> None:
        if not note.strip():
            raise OrchestratorError("descreva a correção desejada (--note)")
        row = self.db.scene(pid, idx)
        stage_target = "image" if (stage == "image" or redo_image) else "video"
        att_id = row[f"current_{stage}_attempt"]
        if att_id:
            self.db.add_review(production_id=pid, scene_idx=idx, attempt_id=att_id, stage=stage, reviewer="human",
                               decision=ReviewDecision.REJECTED, result={"note": note})
        self._reopen_production(pid)
        if stage_target == "image":
            self.db.supersede_attempts(pid, idx, "video", "imagem será refeita")
            self.db.set_scene_status(pid, idx, SS.GENERATING_IMAGE, f"correção solicitada: {note}",
                                     current_image_attempt=None, image_correction=note, current_video_attempt=None,
                                     approved_video_attempt=None)
        else:
            if not row["approved_image_attempt"]:
                raise OrchestratorError("cena sem imagem aprovada; reprove a imagem")
            self.db.set_scene_status(pid, idx, SS.GENERATING_VIDEO, f"correção solicitada: {note}",
                                     current_video_attempt=None, approved_video_attempt=None, video_correction=note)

    def grant_attempts(self, pid: str, idx: int, stage: str, extra: int) -> None:
        row = self.db.scene(pid, idx)
        self.db.update_scene(pid, idx, **{f"extra_{stage}_attempts": row[f"extra_{stage}_attempts"] + extra})
        if row["status"] == SS.BLOCKED:
            target = SS.GENERATING_IMAGE if stage == "image" else SS.GENERATING_VIDEO
            self.db.set_scene_status(pid, idx, target, f"+{extra} tentativas concedidas pelo operador",
                                     **{f"current_{stage}_attempt": None})

    def edit_scene_prompt(self, pid: str, idx: int, *, image_prompt: str | None = None,
                          animation_prompt: str | None = None) -> None:
        """Muda prompt de uma cena e invalida apenas o que depende dele."""
        row = self.db.scene(pid, idx)
        spec = self._spec(row)
        update = {k: v for k, v in {"image_prompt": image_prompt, "animation_prompt": animation_prompt}.items() if v}
        new_spec = spec.model_copy(update=update)
        script = self._script_obj(pid)
        script.scenes[idx - 1] = new_spec
        self.db.update_production(pid, script_json=script.model_dump_json())
        self.db.upsert_scene(pid, idx, new_spec.model_dump_json(), self._scene_fingerprint(new_spec, self._sheet(pid)))
        self.db.add_event(pid, "prompt_edited", ", ".join(update), scene_idx=idx)
        st = self._storage(pid)
        st.write_json("script.json", script.model_dump(mode="json"))
        st.write_text("script.md", creative.render_markdown(script, self._sheet(pid), script.simulated))
        self._reopen_production(pid)
        if image_prompt:
            self._reset_scene(pid, idx, "prompt de imagem alterado")
        elif animation_prompt and row["approved_image_attempt"]:
            self.db.supersede_attempts(pid, idx, "video", "prompt de animação alterado")
            self.db.set_scene_status(pid, idx, SS.GENERATING_VIDEO, "prompt de animação alterado",
                                     current_video_attempt=None, approved_video_attempt=None)

    def pause(self, pid: str, reason: str = "pausa manual") -> None:
        self.db.set_production_status(pid, PS.PAUSED, reason)

    def resume(self, pid: str) -> None:
        self.db.resume_production(pid)

    def cancel(self, pid: str, reason: str = "cancelada pelo operador") -> None:
        self.db.set_production_status(pid, PS.CANCELLED, reason)

    def set_autonomy(self, pid: str, mode: str) -> None:
        """Muda o piloto. Assistido/Automático liberam as etapas pagas (dentro do limite) de uma vez."""
        if mode not in AUTONOMY:
            raise OrchestratorError("autonomia inválida")
        self.db.update_production(pid, autonomy=mode)
        self.db.add_event(pid, "autonomy", f"piloto: {mode}")
        if mode in ("assistido", "automatico"):
            self.set_go_ahead(pid, "all")
            # cenas que já esperam você e o piloto aprovaria: aplica a regra agora
            for row in self.db.scenes(pid):
                st = SS(row["status"])
                if st in (SS.AWAITING_IMAGE_APPROVAL, SS.AWAITING_VIDEO_APPROVAL):
                    kind = "image" if st == SS.AWAITING_IMAGE_APPROVAL else "video"
                    reviews = [r for r in self.db.reviews_for_attempt(row[f"current_{kind}_attempt"]) if r["reviewer"].startswith("auto:")]
                    if reviews and ReviewDecision(reviews[-1]["decision"]) in AUTO_APPROVE[mode]:
                        self.approve(pid, row["idx"], kind, f"aprovado pelo piloto ({mode})", reviewer="piloto")

    def set_go_ahead(self, pid: str, stage: str) -> None:
        """Libera a próxima etapa paga (o operador viu a estimativa). Nunca retrocede."""
        if stage not in ("images", "videos", "all"):
            raise OrchestratorError("etapa inválida para liberação")
        current = self.db.production(pid)["go_ahead"]
        if GO_AHEAD_ORDER[stage] > GO_AHEAD_ORDER[current]:
            self.db.update_production(pid, go_ahead=stage)
            self.db.add_event(pid, "go_ahead", f"operador liberou: {stage}")

    def validate(self, pid: str) -> bool:
        """Só a preparação da ficha (sem custo): valida referências e fatos antes da direção."""
        if PS(self.db.production(pid)["status"]) in {PS.RECEIVED, PS.AWAITING_REFERENCES}:
            return self._prepare(pid)
        return True

    def set_budget(self, pid: str, budget_usd: float) -> None:
        self.db.update_production(pid, budget_usd=budget_usd)
        self.db.add_event(pid, "budget_changed", f"novo limite US${budget_usd:.2f}")

    def final_decision(self, pid: str, approve: bool, note: str = "", reviewer: str = "human") -> None:
        if self.db.production(pid)["status"] != PS.AWAITING_FINAL_REVIEW:
            raise OrchestratorError("produção não está aguardando revisão final")
        self.db.add_review(production_id=pid, scene_idx=None, attempt_id=None, stage="final", reviewer=reviewer,
                           decision=ReviewDecision.APPROVED if approve else ReviewDecision.REJECTED, result={"note": note})
        if approve:
            self.db.set_production_status(pid, PS.COMPLETED, note or "aprovada na revisão final")
        else:
            self.db.set_production_status(pid, PS.EDITING, note or "reprovada na revisão final: remontar")
        write_reports(self.db, pid, self._storage(pid))

    # ================================================================= edição
    def _music_choice(self, pid: str) -> dict | None:
        row = self.db.production(pid)
        raw = row["music_json"] if "music_json" in row.keys() else None
        return json.loads(raw) if raw else None

    def _sound_for(self, style: str, music_id: str, pid: str | None = None):
        """Trilha e efeitos do estilo (sintetizados em cache na primeira vez; sem custo de API).
        A escolha explícita da biblioteca musical (music_json) tem prioridade sobre o padrão do estilo."""
        from .agents import sound
        cfg = editing.EDIT_STYLES.get(style)
        if cfg is None:
            return None, None, {}
        cache = self.s.data_dir / "sound_cache"
        names = {v[0] for v in cfg["sfx"].values()}
        choice = self._music_choice(pid) if pid else None
        if choice and choice["mode"] != "auto":
            from .music import MusicLibrary
            sfx = {n: sound.sfx_file(self.ffmpeg, cache, n) for n in names}
            if choice["mode"] in ("none", "platform"):
                return None, None, sfx
            lib = MusicLibrary(self.db, self.s)
            wid = self._wid(pid)
            track = lib.track(wid, choice["track_id"])
            path = lib.file_of(wid, choice["track_id"], self.ffmpeg) if track else None
            if path is None:
                log.warning("trilha escolhida %s indisponível; seguindo sem trilha", choice["track_id"])
                return None, None, sfx
            music = {"id": track["id"], "title": track["title"], "license": track.get("license") or track.get("usage_terms") or "Autorização declarada pelo usuário",
                     "bpm": track.get("bpm") if choice.get("beat_sync") else None, "start_s": choice.get("start_s") or track.get("start_s") or 0,
                     "gain_db": choice.get("volume_db"), "fade_in_s": choice.get("fade_in_s"), "fade_out_s": choice.get("fade_out_s")}
            return music, path, sfx
        lib = {t["id"]: t for t in sound.library(self.s.assets_dir)}
        want = cfg["music"] if music_id in ("", "auto") else (None if music_id == "none" else music_id)
        music = lib.get(want) if want else None
        if want and music is None:
            log.warning("trilha %s não encontrada; seguindo sem trilha", want)
        music_path = sound.track_file(self.ffmpeg, cache, music) if music else None
        return music, music_path, {n: sound.sfx_file(self.ffmpeg, cache, n) for n in names}

    def set_music(self, pid: str, raw: dict) -> None:
        """Guarda a trilha da produção. Com o vídeo pronto, remonta só com FFmpeg, preservando as cenas."""
        from .music import MusicError, MusicLibrary, clean_choice
        try:
            choice = clean_choice(raw)
            if choice["track_id"] and MusicLibrary(self.db, self.s).track(self._wid(pid), choice["track_id"]) is None:
                raise MusicError("trilha não encontrada")
        except MusicError as exc:
            raise OrchestratorError(str(exc)) from exc
        self.db.update_production(pid, music_json=json.dumps(choice, ensure_ascii=False))
        self.db.add_event(pid, "music_choice", f"trilha: {choice['mode']} {choice['track_id'] or ''}".strip())
        if PS(self.db.production(pid)["status"]) in {PS.AWAITING_FINAL_REVIEW, PS.COMPLETED}:
            self.db.set_production_status(pid, PS.EDITING, "remontagem: troca de trilha")

    def set_edit(self, pid: str, style: str, music_id: str = "auto") -> None:
        """Escolhe estilo/trilha da montagem. Com o vídeo já montado, remonta (só FFmpeg: sem custo de geração)."""
        from .agents import sound
        if style not in editing.EDIT_STYLES:
            raise OrchestratorError("estilo de edição inválido")
        if music_id not in ("auto", "none") and music_id not in {t["id"] for t in sound.library(self.s.assets_dir)}:
            raise OrchestratorError("trilha não encontrada")
        self.db.update_production(pid, edit_style=style, music_id=music_id)
        if music_id != "auto":
            self.db.update_production(pid, music_json=None)  # a trilha escolhida aqui substitui a da biblioteca
        status = PS(self.db.production(pid)["status"])
        self.db.add_event(pid, "edit_style", f"estilo {style}, trilha {music_id}")
        if status in {PS.AWAITING_FINAL_REVIEW, PS.COMPLETED}:
            self.db.set_production_status(pid, PS.EDITING, f"remontagem: estilo {editing.EDIT_STYLES[style]['label']}")

    def _edit(self, pid: str) -> None:
        st = self._storage(pid)
        script = self._script_obj(pid)
        sheet = self._sheet(pid)
        fmt = self._profiles(pid)["format"]["data"]
        takes, probes = {}, {}
        approved_dir = st.dir("delivery/approved")
        for row in self.db.scenes(pid):
            vid = self.db.attempt(row["approved_video_attempt"])
            img = self.db.attempt(row["approved_image_attempt"])
            takes[row["idx"]] = st.path(vid["output_path"])
            probes[row["idx"]] = self.ffmpeg.probe(takes[row["idx"]])
            for att, label in ((img, "image"), (vid, "take")):
                src = st.path(att["output_path"])
                (approved_dir / f"scene_{row['idx']}_{label}{src.suffix}").write_bytes(src.read_bytes())
        # Decisão de 28/10/2026: sem aviso gravado na tela (fica na legenda). Roteiros antigos ainda trazem esse texto.
        kept = [o for o in script.overlays if not editing.DISCLOSURE_OVERLAY.search(o.text)]
        if len(kept) != len(script.overlays):
            script = script.model_copy(update={"overlays": kept})
            self.db.add_event(pid, "overlay_removed", "aviso de publicidade/IA fora da tela (fica na legenda)")
        row = self.db.production(pid)
        style = row["edit_style"] if "edit_style" in row.keys() else editing.DEFAULT_STYLE
        music, music_path, sfx_paths = self._sound_for(style, row["music_id"] if "music_id" in row.keys() else "auto", pid)
        plan = editing.build_edit_plan(script, takes, probes, style=style, music=music, music_path=music_path,
                                       sfx_paths=sfx_paths)
        errors = editing.validate_edit_plan(plan, probes, script, fmt.get("duration_tolerance_s", 1.5))
        st.write_json("delivery/edit_plan.json", plan.model_dump(mode="json"))
        if errors:
            self.db.set_production_status(pid, PS.PAUSED, "plano de edição inválido: " + "; ".join(errors))
            return
        delivery = st.dir("delivery")
        out = editing.assemble_and_package(self.ffmpeg, plan, delivery, st.dir("work/edit"), fmt["cover"]["time_s"])
        caption, warnings = editing.build_caption(sheet, fmt)
        st.write_text("delivery/caption.txt", caption)
        p = sheet.product
        st.write_json("delivery/product.json", {
            "name": p.name, "variant": p.variant, "affiliate_link": p.affiliate_link, "product_url": p.product_url,
            "note": "Link preservado exatamente como fornecido. Vincule este produto/variante na publicação.",
        })
        st.write_json("delivery/delivery_meta.json", {
            "simulated": script.simulated or self.image_gen.simulated or self.video_gen.simulated,
            "final_probe": out["final_probe"], "cover_time_s": out["cover_time_s"], "caption_warnings": warnings,
            "disclosure": fmt["disclosure"], "edit_style": plan.style,
            "transitions": [t.kind for t in plan.transitions],
            "music": {"title": plan.music.title, "license": plan.music.license, "offset_s": plan.music.offset_s, "gain_db": plan.music.gain_db} if plan.music else None,
            "music_platform": (self._music_choice(pid) or {}).get("platform_title"),
            "sfx": [c.label for c in plan.sfx], "no_music_version": bool(out["no_music"]),
        })
        self.db.add_event(pid, "edit_done", f"montagem {plan.style}: "
                          + (f"trilha {plan.music.title}; " if plan.music else "sem trilha; ")
                          + f"{len(plan.sfx)} efeito(s) sonoro(s)")
        for w in warnings:
            self.db.add_event(pid, "delivery_warning", w)
        self.db.set_production_status(pid, PS.AWAITING_FINAL_REVIEW,
                                      f"pacote pronto: {out['final_probe']['duration_s']:.2f}s")
