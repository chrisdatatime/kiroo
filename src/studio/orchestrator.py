"""Orquestrador: controla fluxo, dependências, estados, tentativas, orçamento e retomada.

Cada chamada a `run()` avança a produção até um portão humano, uma pausa (orçamento,
pedido do operador) ou a conclusão. Tudo é persistido; um novo processo continua de
onde parou, consultando operações remotas já enviadas em vez de reenviá-las.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import budget as budget_mod
from .agents import creative, editing, fidelity, visual_review
from .agents.product_prep import prepare_product
from .config import Settings
from .training import prompt_block, review_criteria
from .credits import InsufficientCredits, Ledger, fmt as fmt_credits
from .db import Database, now
from .ffmpeg import FFmpeg, FFmpegError
from .models import ProductFacts, ProductInput, ProductSheet, ReviewDecision, ReviewResult, SceneSpec, Script
from .pricing import UnknownPrice
from .profiles import snapshot
from .providers.base import (FactsRequest, ImageGenerator, ImageRequest, OpState, PermanentError, Planner, PlanningContext,
                             ProviderBillingError, Reviewer, TransientError, VideoGenerator, VideoRequest)

# Prefixo fixo do motivo de pausa: a interface reconhece e mostra a saída certa (recarregar a conta do provedor).
PROVIDER_BILLING_REASON = "provedor de IA sem saldo"
from .reports import write_reports
from .states import PRODUCTION_LABELS, TERMINAL, ProductionStatus as PS, SceneStatus as SS
from .storage import ProductionStorage, sha256_file

log = logging.getLogger("studio")

MAX_TRANSIENT_RETRIES = 4
BACKOFF_BASE_S = 2.0
BACKOFF_MAX_S = 120.0
REVIEW_COST_ESTIMATE_USD = 0.01  # compatibilidade; o valor em uso vem de profiles/billing/operation_costs.json


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


class DuplicateRequest(OrchestratorError):
    """O mesmo pedido de criacao (client_request_id) ja existe no workspace: protecao contra duplo clique. `pid` e o
    da producao que ja foi criada; nada novo foi reservado nem cobrado."""

    def __init__(self, pid: str):
        super().__init__("pedido duplicado: a producao ja existe")
        self.pid = pid


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _parse_ts(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts) if ts else None


class Orchestrator:
    def __init__(self, settings: Settings, db: Database, *, image_gen: ImageGenerator, video_gen: VideoGenerator,
                 planner: Planner, reviewer: Reviewer, ffmpeg: FFmpeg, sleep=time.sleep, base_dir: Path | None = None,
                 fal_gen=None):
        self.s = settings
        self.fal_gen = fal_gen   # motor fal.ai (workflows); None = indisponivel. O Gemini nao o usa.
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
                          workspace_id: str | None = None, prebudget: bool = False,
                          direction_required: bool = False, engine: str = "gemini", style: str | None = None,
                          client_request_id: str | None = None, estimate: dict | None = None) -> str:
        """go_ahead="none" exige liberação explícita (set_go_ahead) antes de gerar imagens e antes dos vídeos.

        `budget_usd` é o ORÇAMENTO OPERACIONAL (freio interno). Com `prebudget=True` (modo real, com estúdio), o custo
        estimado do vídeo completo é RESERVADO do saldo do cliente antes de começar; sem saldo → InsufficientCredits e
        nada é criado nem cobrado."""
        if go_ahead not in GO_AHEAD_ORDER:
            raise OrchestratorError("liberação inválida")
        if autonomy not in AUTONOMY:
            raise OrchestratorError("autonomia inválida")
        mode = self.s.mode
        if product.creative is not None:   # a apresentação/ambiente escolhidos mandam no formato e na direção de arte
            from . import creative_options
            ids = creative_options.profile_ids(product.creative)
            format_id, art_direction = ids["format"], ids["art_direction"]
        if budget_usd < 0:
            raise OrchestratorError("orçamento não pode ser negativo")
        if mode == "real":
            if not self.s.allow_paid_calls:
                raise OrchestratorError("modo real exige STUDIO_ALLOW_PAID_CALLS=true")
            if engine == "fal":
                if not self.s.fal_api_key:
                    raise OrchestratorError("modo real exige FAL_KEY para o motor fal.ai")
            elif not self.s.gemini_api_key:
                raise OrchestratorError("modo real exige GEMINI_API_KEY")
            if budget_usd <= 0:
                raise OrchestratorError("modo real exige orçamento > 0 definido pelo operador")
        profiles = snapshot(self.s.profiles_dir, {"presenter": presenter, "art_direction": art_direction,
                                                  "format": format_id})
        if not (prebudget and mode == "real" and workspace_id):
            estimate = None   # DEMO e producoes sem estudio nao reservam saldo, mesmo que o chamador tenha calculado um
        else:
            if estimate is None:   # motor fal.ai passa o proprio (valor fixo do pacote); o Gemini calcula por cena
                estimate = budget_mod.estimate_production(self.s, len(profiles["format"]["data"].get("scenes") or []) or 3)
            self.ledger().can_reserve(workspace_id, estimate["cc"])   # bloqueia ANTES de criar qualquer coisa
        pid = self.db.create_production(mode=mode, format_id=format_id, product=product.model_dump(mode="json"),
                                        profiles=profiles, budget_usd=budget_usd, go_ahead=go_ahead,
                                        autonomy=autonomy)
        if direction_required and product.creative is None:
            self.db.update_production(pid, direction_required=1)
        fields: dict = {}
        if workspace_id:
            fields["workspace_id"] = workspace_id
        if engine == "fal":
            fields.update(engine="fal", style=style, client_request_id=client_request_id, format_id=f"fal_{style}")
        if fields:   # numa UNICA gravacao: o indice unico (workspace, client_request_id) barra o duplo clique atomicamente
            try:
                self.db.update_production(pid, **fields)
            except sqlite3.IntegrityError:
                self.db.set_production_status(pid, PS.CANCELLED, "pedido duplicado (mesmo client_request_id)")
                row = self.db.conn.execute("SELECT id FROM productions WHERE workspace_id=? AND client_request_id=? AND id<>?",
                                           (workspace_id, client_request_id, pid)).fetchone()
                raise DuplicateRequest(row["id"] if row else pid) from None
        if workspace_id:
            # A produção congela as versões de treinamento em vigor agora; versões novas valem só para as próximas.
            from .training import Training, default_edit_style
            snap = Training(self.db, self.s.data_dir).snapshot(workspace_id)
            self.db.update_production(pid, training_json=json.dumps(snap, ensure_ascii=False))
            style = default_edit_style(snap)
            if style:
                self.db.update_production(pid, edit_style=style)
        if estimate is not None:
            try:
                self.ledger().reserve_pool(workspace_id, pid, estimate["cc"], ref="base", usd=estimate["usd"],
                                           note="pré-orçamento do vídeo completo")
            except InsufficientCredits:   # o saldo mudou entre a checagem e a reserva: nada foi gasto
                self.db.set_production_status(pid, PS.CANCELLED, "saldo insuficiente para o pré-orçamento")
                raise
            self.db.update_production(pid, prebudget_cc=estimate["cc"])
            self.db.add_event(pid, "prebudget", f"pré-orçamento reservado: {fmt_credits(estimate['cc'])} créditos",
                              data=estimate)
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
        changed = self._sync_format(pid, product)
        if changed and PS(row["status"]) == PS.PAUSED:   # ao retomar, revalida e refaz o roteiro no novo formato
            self.db.update_production(pid, resume_status=PS.AWAITING_REFERENCES)
        elif changed or PS(row["status"]) not in {PS.RECEIVED, PS.PAUSED}:
            self.db.set_production_status(pid, PS.AWAITING_REFERENCES, "ficha atualizada: revalidar")

    def _sync_format(self, pid: str, product: ProductInput, *, source: str = "ficha") -> bool:
        """Apresentação → formato e ambiente → direção de arte. format_id e perfis congelados SEMPRE seguem a escolha
        gravada na ficha, por qualquer caminho (criação, substituição da ficha, Direção, invariante antes de gerar).
        Mudou o formato: a imagem-âncora (feita no formato antigo) e o aviso de formato deixam de valer.
        Retorna True se algo mudou."""
        from . import creative_options
        if product.creative is None:
            return False
        ids = creative_options.profile_ids(product.creative)
        want, art = ids["format"], ids["art_direction"]
        row = self.db.production(pid)
        profiles = self._profiles(pid)
        fmt_changed = row["format_id"] != want or profiles["format"]["id"] != want
        art_changed = profiles["art_direction"]["id"] != art
        if not (fmt_changed or art_changed):
            return False
        old, old_art = row["format_id"], profiles["art_direction"]["id"]
        sel = {**({"format": want} if fmt_changed else {}), **({"art_direction": art} if art_changed else {})}
        profiles.update(snapshot(self.s.profiles_dir, sel, only=tuple(sel)))
        fields = {"format_id": want, "profiles_json": json.dumps(profiles, ensure_ascii=False)}
        if fmt_changed:
            fields["format_advice"] = None
            if self._anchor(pid):
                fields["anchor_json"] = None
                self.db.add_event(pid, "anchor", "imagem-âncora removida: era do formato anterior")
        self.db.update_production(pid, **fields)
        self._storage(pid).write_json("profiles_snapshot.json", profiles)
        pres = product.creative.presentation
        if fmt_changed:
            self.db.add_event(pid, "format_changed", f"apresentação {pres}: formato {old} → {want} ({source})",
                              data={"presentation": pres, "from": old, "to": want, "source": source})
        if art_changed:
            self.db.add_event(pid, "art_direction_changed", f"ambiente {product.creative.environment}: direção de arte "
                              f"{old_art} → {art} ({source})", data={"from": old_art, "to": art, "source": source})
        return True

    def format_problems(self, pid: str, *, with_script: bool = True) -> list[str]:
        """Invariante: format_id, perfis congelados, ficha validada, roteiro e cenas derivam da apresentação GRAVADA.
        Lista vazia = consistente. `with_script=False` ignora roteiro/cenas (logo após a validação eles ainda vão ser
        refeitos)."""
        from . import creative_options
        row = self.db.production(pid)
        product = ProductInput.model_validate_json(row["product_json"])
        profiles = self._profiles(pid)
        probs: list[str] = []
        if profiles["format"]["id"] != row["format_id"]:
            probs.append(f"perfil congelado {profiles['format']['id']} ≠ format_id {row['format_id']}")
        if product.creative is not None:
            ids = creative_options.profile_ids(product.creative)
            pres = product.creative.presentation
            # Direção de arte fica fora da invariante dura de propósito: é sincronizada em toda mudança da ficha/Direção,
            # mas uma produção antiga em andamento não perde cenas já aprovadas (e pagas) só por causa do cenário.
            if row["format_id"] != ids["format"]:
                probs.append(f"apresentação {pres} exige {ids['format']}, mas format_id={row['format_id']}")
            if row["sheet_json"]:
                sheet_pres = ((json.loads(row["sheet_json"]).get("product") or {}).get("creative") or {}).get("presentation")
                if sheet_pres != pres:
                    probs.append(f"ficha validada com apresentação {sheet_pres}, gravada {pres}")
        if with_script and row["script_json"]:
            mode = profiles["format"]["data"]["presenter_mode"]
            if json.loads(row["script_json"]).get("format_id") != row["format_id"]:
                probs.append(f"roteiro feito para {json.loads(row['script_json']).get('format_id')}, "
                             f"formato atual {row['format_id']}")
            for sc in self.db.scenes(pid):
                if str(self._spec(sc).presenter_mode) != mode:
                    probs.append(f"cena {sc['idx']} com modo {self._spec(sc).presenter_mode}, formato exige {mode}")
        return probs

    MAX_FORMAT_REPAIRS = 2

    def _enforce_format(self, pid: str, status: PS) -> bool:
        """Antes de roteirizar ou gerar: se a invariante falhar, recalcula a partir da apresentação gravada, registra e
        volta para a validação (sem custo). Se nem assim fechar, bloqueia com erro claro. True = pode seguir."""
        probs = self.format_problems(pid, with_script=status != PS.VALIDATED)
        if not probs:
            return True
        self._format_repairs = getattr(self, "_format_repairs", 0) + 1
        self.db.add_event(pid, "format_invariant", "formato inconsistente antes de gerar: " + "; ".join(probs)[:600],
                          data={"problems": probs, "status": str(status)})
        if self._format_repairs > self.MAX_FORMAT_REPAIRS:
            self.db.set_production_status(pid, PS.FAILED, "formato inconsistente e não foi possível corrigir: "
                                          + "; ".join(probs)[:400])
            return False
        product = ProductInput.model_validate_json(self.db.production(pid)["product_json"])
        self._sync_format(pid, product, source="invariante")
        self.db.set_production_status(pid, PS.AWAITING_REFERENCES, "formato recalculado a partir da apresentação: "
                                      "revalidar e refazer o roteiro")
        return False

    def awaiting_direction(self, pid: str) -> bool:
        """Produção do app criada sem Direção (direction_required): o formato de criação é provisório e nada é
        roteirizado nem gerado até o operador escolher a apresentação. CLI/painel e produções antigas seguem."""
        row = self.db.production(pid)
        if not ("direction_required" in row.keys() and row["direction_required"]):
            return False
        return ProductInput.model_validate_json(row["product_json"]).creative is None

    # =============================================================== execução
    def run(self, pid: str, *, wait: bool = True, max_wait_s: float | None = None) -> str:
        row = self.db.production(pid)
        if row["mode"] != self.s.mode:
            raise OrchestratorError(f"produção em modo {row['mode']}, mas o ambiente está em modo {self.s.mode}")
        deadline = time.monotonic() + max_wait_s if max_wait_s else None
        self._format_repairs = 0
        try:
            if self._engine(pid) == "fal":   # motor fal.ai: ramo proprio; com engine=gemini o caminho abaixo e o de sempre
                from .fal_pipeline import FalRunner
                FalRunner(self).loop(pid, wait, deadline)
            else:
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

    def _engine(self, pid: str) -> str:
        row = self.db.production(pid)
        return row["engine"] if "engine" in row.keys() else "gemini"

    def _loop(self, pid: str, wait: bool, deadline: float | None) -> None:
        while True:
            if self.stop_event is not None and self.stop_event.is_set():
                self.stopped = True
                break
            self._settle(pid)
            status = PS(self.db.production(pid)["status"])
            if status in TERMINAL or status in {PS.PAUSED, PS.AWAITING_FINAL_REVIEW}:
                break
            if status in {PS.VALIDATED, PS.SCRIPTED, PS.PRODUCING, PS.EDITING} and not self._enforce_format(pid, status):
                continue   # formato recalculado (volta à validação) ou bloqueado com erro claro
            if status in {PS.RECEIVED, PS.AWAITING_REFERENCES}:
                if not self._prepare(pid):
                    break
            elif status in {PS.VALIDATED, PS.SCRIPTED, PS.PRODUCING} and self.needs_confirmation(pid):
                break   # "Seu próximo vídeo": sem a confirmação do cliente nada é gasto (nem roteiro por IA)
            elif status == PS.VALIDATED and self.awaiting_direction(pid):
                break   # fluxo do app: a Direção (apresentação) vem antes do roteiro e de qualquer geração
            elif status == PS.VALIDATED:
                if not self._script(pid):
                    break
            elif status == PS.SCRIPTED:
                self.db.set_production_status(pid, PS.PRODUCING)
            elif status == PS.PRODUCING:
                self._reconcile_autopilot(pid)
                outcome = self._step_scenes(pid)
                if outcome == "done":
                    self.db.set_production_status(pid, PS.EDITING, "todas as cenas aprovadas")
                elif outcome == "waiting":
                    if not wait or (deadline and time.monotonic() > deadline):
                        break
                    self.sleep(self.s.poll_interval_s)
                elif outcome == "progress":
                    continue
                elif PS(self.db.production(pid)["status"]) == PS.AWAITING_REFERENCES:
                    continue   # a barreira de formato mandou revalidar: refaz ficha e roteiro (sem custo) na mesma execução
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

    def _facts(self, pid: str) -> ProductFacts | None:
        row = self.db.production(pid)
        raw = row["facts_json"] if "facts_json" in row.keys() else None
        return ProductFacts.model_validate(json.loads(raw)["facts"]) if raw else None

    def _anchor(self, pid: str) -> dict | None:
        row = self.db.production(pid)
        raw = row["anchor_json"] if "anchor_json" in row.keys() else None
        return json.loads(raw) if raw else None

    def _corrections(self, row, kind: str) -> list[dict]:
        """Histórico acumulado de correções da cena (produções antigas: só a última, em `{kind}_correction`)."""
        col = f"{kind}_corrections_json"
        raw = row[col] if col in row.keys() else None
        if raw:
            return json.loads(raw)
        legacy = row[f"{kind}_correction"]
        return [{"text": legacy, "source": "legado", "attempt": None}] if legacy else []

    def _set_corrections(self, pid: str, idx: int, kind: str, history: list[dict]) -> None:
        self.db.update_scene(pid, idx, **{
            f"{kind}_corrections_json": json.dumps(history, ensure_ascii=False) if history else None,
            f"{kind}_correction": history[-1]["text"] if history else None})

    def _extract_facts(self, pid: str, sheet: ProductSheet) -> ProductFacts:
        """Ficha técnica VISUAL (cor, botões, lados, cabo, logos, proporções) a partir das fotos oficiais.
        Feita uma vez por conjunto de fotos (refazer o roteiro não paga de novo). Sem IA ou com falha: só o que o
        operador digitou. Levanta BudgetExceeded se o freio de gasto bloquear."""
        refs = [r for r in sheet.product.references if r.usable_for_generation]
        key = sorted(r.sha256 for r in refs if r.sha256)
        row = self.db.production(pid)
        raw = row["facts_json"] if "facts_json" in row.keys() else None
        if raw and json.loads(raw).get("refs") == key:
            return ProductFacts.model_validate(json.loads(raw)["facts"])
        st = self._storage(pid)
        describe = getattr(self.planner, "describe_product", None)
        facts = None
        if describe is not None and refs:
            req = FactsRequest(name=sheet.product.name, variant=sheet.product.variant,
                               references=[st.path(r.stored_path) for r in refs],
                               visual_attributes=dict(sheet.product.visual_attributes))
            try:
                data, _meta = self._call_text("facts", None, lambda: describe(req), self.planner, pid=pid,
                                              prompt="describe_product")
                facts = fidelity.parse_facts(data, source=f"{self.planner.provider}:{self.planner.model}",
                                             simulated=self.planner.simulated)
            except (TransientError, PermanentError) as exc:
                self.db.add_event(pid, "facts_failed",
                                  f"ficha técnica por IA falhou; usando só os atributos digitados: {exc}")
        if facts is None:
            facts = fidelity.facts_from_operator(sheet, simulated=self.planner.simulated)
        self.db.update_production(pid, facts_json=json.dumps({"refs": key, "facts": facts.model_dump(mode="json")},
                                                             ensure_ascii=False))
        st.write_json("product_facts.json", facts.model_dump(mode="json"))
        self.db.add_event(pid, "product_facts", "ficha técnica do produto pronta"
                          + (f": {facts.button_count} botões" if facts.button_count is not None else "")
                          + ("; assimétrico" if facts.asymmetric else "") + f"; complexidade {facts.complexity}",
                          data={"source": facts.source, "complexity": facts.complexity, "asymmetric": facts.asymmetric})
        return facts

    def _advise_format(self, pid: str, facts: ProductFacts, presenter_mode: str) -> None:
        """Produto assimétrico/complexo em "Somente mãos": sugere "Produto em destaque" e avisa o operador.
        Não troca sozinho (a escolha é do operador) e não pausa a produção."""
        advice = fidelity.FORMAT_ADVICE if presenter_mode == "hands_only" and fidelity.is_complex(facts) else None
        if advice and not self.db.production(pid)["format_advice"]:
            self.db.add_event(pid, "format_advice", advice, data={"suggested": "product_only"})
        self.db.update_production(pid, format_advice=advice)

    def _script_obj(self, pid: str) -> Script:
        return Script.model_validate_json(self.db.production(pid)["script_json"])

    def _prepare(self, pid: str) -> bool:
        row = self.db.production(pid)
        profiles = self._profiles(pid)
        product = ProductInput.model_validate_json(row["product_json"])
        st = self._storage(pid)
        mode = profiles["format"]["data"]["presenter_mode"]
        sheet = prepare_product(product, st, profiles["presenter"]["data"], mode, self.s.reference_root, self.base_dir)
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
        try:
            facts = self._extract_facts(pid, sheet)
        except BudgetExceeded:
            return False
        self._advise_format(pid, facts, profiles["format"]["data"]["presenter_mode"])
        ctx = PlanningContext(draft=draft, product_sheet_json=sheet.model_dump_json(),
                              art_direction=profiles["art_direction"]["data"],
                              presenter_mode=profiles["format"]["data"]["presenter_mode"],
                              training=prompt_block(self._training(pid), "theo") + prompt_block(self._training(pid), "nina"),
                              facts=fidelity.facts_block(facts))
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
                                 video_correction=None, image_corrections_json=None, video_corrections_json=None)
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
        anchor = self._anchor(pid)
        if anchor and any(k.startswith("product:") for k in spec.references):
            # imagem-âncora aprovada pelo operador: referência PRINCIPAL do produto (vai primeiro)
            refs.append({"key": "product:anchor", "path": anchor["path"], "sha256": anchor["sha256"]})
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
        corrections = fidelity.corrections_block(self._corrections(row, kind))
        facts = fidelity.facts_block(self._facts(pid))
        # modo do formato ATUAL (a barreira _generation_allowed já garantiu que roteiro e cenas o seguem)
        mode = self._profiles(pid)["format"]["data"]["presenter_mode"]
        negative = fidelity.negative_for(mode)
        lock = ("\n\n" + fidelity.PRODUCT_ONLY_LOCK_EN) if mode == "product_only" else ""
        if kind == "image":
            refs = self._resolve_refs(pid, spec, self._sheet(pid))
            prompt = spec.image_prompt
            for r in refs:
                if r["key"].startswith("presenter:"):
                    usage = self._sheet(pid).presenter_assets[r["key"].split(":", 1)[1]]["usage_en"]
                    prompt += f"\nPresenter reference image: {usage}"
            if any(r["key"] == "product:anchor" for r in refs):
                prompt += ("\n\nPRIMARY PRODUCT REFERENCE: the FIRST attached image is the operator-approved anchor of "
                           "this exact product. Match it exactly (shape, buttons, sides, cable, logos, color); the "
                           "official photos only confirm details.")
            if facts:
                prompt += "\n\n" + facts
            prompt += "\n\n" + negative
            prompt += prompt_block(self._training(pid), "iris")
            if corrections:
                prompt += "\n\n" + corrections
            prompt += lock   # por último: nada depois (treino, correção) pode reintroduzir mãos
            req = ImageRequest(prompt=prompt, reference_images=[st.path(r["path"]) for r in refs],
                               aspect_ratio=script.aspect_ratio, image_size=self.s.image_size)
        else:
            img = self.db.attempt(row["approved_image_attempt"])
            refs = [{"key": "start_image", "path": img["output_path"], "sha256": img["output_sha256"]}]
            prompt = spec.animation_prompt
            if facts:
                prompt += "\n\n" + facts
            prompt += "\n\n" + negative
            prompt += prompt_block(self._training(pid), "lia")
            if corrections:
                prompt += "\n\n" + corrections
            prompt += lock
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

    def _pause(self, pid: str, reason: str, code: str) -> None:
        """Pausa com motivo legível e código estável (a interface e o administrador decidem pelo código)."""
        self.db.set_production_status(pid, PS.PAUSED, reason)
        self.db.update_production(pid, pause_code=code)

    def _check_budget(self, pid: str, estimate: float, what: str, stage: str | None = None) -> None:
        """Freios independentes, nesta ordem (o primeiro que bloquear pausa; nada é chamado nem cobrado):
        1. portão de chamadas pagas e teto mensal (conta/plataforma; teto 0 nunca gasta) — só modo real;
        2. orçamento operacional da produção (freio interno): pausa, avisa o administrador e NÃO pede nada ao cliente."""
        prod = self.db.production(pid)
        if prod["mode"] == "real" and estimate > 0:
            from . import paid_gate
            from .spend import month_real_spend
            wid = prod["workspace_id"] if "workspace_id" in prod.keys() else None
            try:   # kill switch, liberação do ambiente, teto da plataforma e teto diário do agente
                paid_gate.check_spend(self.db, estimate, workspace_id=wid, agent=paid_gate.KIND_AGENT.get(stage or ""))
            except paid_gate.PaidCallsBlocked as exc:
                code = budget_mod.MONTHLY_CAP if exc.reason == "platform_cap" else f"{budget_mod.PAID_GATE}:{exc.reason}"
                self._pause(pid, str(exc), code)
                log.warning("[%s] chamada paga bloqueada (%s) para %s", pid, exc.reason, what)
                raise BudgetExceeded(str(exc)) from None
            ws = self.db.conn.execute("SELECT * FROM workspaces WHERE id=?", (wid,)).fetchone() if wid else None
            # teto e gasto são do workspace; vale o menor entre o da conta e o da plataforma
            cap = paid_gate.effective_cap(ws["monthly_cap_usd"] if ws else self.s.monthly_cap_usd)
            spent = month_real_spend(self.db, workspace_id=wid)
            reason = None
            if cap <= 0:
                reason = "teto mensal de gastos não definido (desligue o DEMO pela interface ou defina STUDIO_MONTHLY_CAP_USD)"
            elif spent + estimate > cap + 1e-9:
                reason = (f"teto mensal atingido para {what}: gasto do mês US${spent:.4f} + estimado "
                          f"US${estimate:.4f} > teto US${cap:.2f}")
            if reason:
                self._pause(pid, reason, budget_mod.MONTHLY_CAP)
                log.warning("[%s] %s", pid, reason)
                raise BudgetExceeded(reason)
        budget = prod["budget_usd"]
        committed = self.committed_cost(pid)
        if committed + estimate > budget + 1e-9:
            detail = (f"orçamento operacional insuficiente para {what}: comprometido US${committed:.4f} + estimado "
                      f"US${estimate:.4f} > limite interno US${budget:.2f}")
            self._pause(pid, budget_mod.CLIENT_MESSAGES[budget_mod.OPS_BUDGET_REACHED], budget_mod.OPS_BUDGET_REACHED)
            budget_mod.notify_admin(self.db, pid, budget_mod.OPS_BUDGET_REACHED, detail)
            raise BudgetExceeded(detail)

    # ------------------------------------------------------- créditos (Fase C)
    def _wid(self, pid: str) -> str | None:
        prod = self.db.production(pid)
        return prod["workspace_id"] if "workspace_id" in prod.keys() else None

    def ledger(self) -> Ledger:
        if self._ledger is None:
            self._ledger = Ledger(self.db)
        return self._ledger

    def needs_confirmation(self, pid: str) -> bool:
        """Produção real com pré-orçamento que o cliente ainda não confirmou ("Confirmar e criar vídeo")."""
        prod = self.db.production(pid)
        return (prod["mode"] == "real" and self._has_prebudget(pid) and "cost_confirmed_at" in prod.keys()
                and prod["cost_confirmed_at"] is None)

    def confirm_cost(self, pid: str, authorized_cc: int | None = None) -> None:
        """O cliente autoriza o custo mostrado em "Seu próximo vídeo". Se o valor mudou desde que ele viu (`authorized_cc`
        diferente do reservado), recusa: ele precisa rever. Idempotente."""
        prod = self.db.production(pid)
        if not self._has_prebudget(pid) or prod["cost_confirmed_at"] is not None:
            return
        if PS(prod["status"]) in TERMINAL:
            raise OrchestratorError("produção encerrada")
        if authorized_cc is not None and int(authorized_cc) != prod["prebudget_cc"]:
            raise OrchestratorError("o custo mudou desde que você viu o resumo; revise e confirme de novo")
        self.db.update_production(pid, cost_confirmed_at=now(), cost_confirmed_cc=prod["prebudget_cc"])
        self.db.add_event(pid, "cost_confirmed", f"cliente autorizou {fmt_credits(prod['prebudget_cc'])} créditos",
                          data={"cc": prod["prebudget_cc"]})

    def _has_prebudget(self, pid: str) -> bool:
        prod = self.db.production(pid)
        return "prebudget_cc" in prod.keys() and prod["prebudget_cc"] is not None

    def _hold(self, pid: str, estimate: float, what: str, stage: str) -> str | None:
        """Teto do mês + orçamento operacional e, nas produções antigas, reserva de créditos por chamada.
        Com pré-orçamento o saldo do cliente já foi reservado na criação: nenhuma chamada pede saldo de novo.
        Produção encerrada (cancelada/falhou/concluída): nenhuma chamada paga nova, nem de texto."""
        if PS(self.db.production(pid)["status"]) in TERMINAL:
            raise BudgetExceeded(f"produção encerrada: {what} não foi enviado")
        self._check_budget(pid, estimate, what, stage)
        wid = self._wid(pid)
        if wid is None or estimate <= 0 or self.db.production(pid)["mode"] != "real":
            return None  # DEMO e produções sem workspace (CLI antiga) não usam créditos
        if self._has_prebudget(pid):
            if self.needs_confirmation(pid):   # defesa: nenhum caminho chega aqui sem a confirmação do cliente
                raise BudgetExceeded("aguardando a confirmação do cliente")
            return None  # o acerto sai do pré-orçamento em settle_pool
        try:
            return self.ledger().hold(wid, pid, estimate, stage)
        except InsufficientCredits as exc:
            reason = (f"saldo de créditos insuficiente para {what}: saldo {fmt_credits(exc.balance_cc)} créditos, "
                      f"estimado {fmt_credits(exc.needed_cc)} créditos (estimado US${estimate:.4f})")
            self._pause(pid, reason, budget_mod.CREDITS_INSUFFICIENT)
            log.warning("[%s] %s", pid, reason)
            raise BudgetExceeded(reason) from exc

    def _settle(self, pid: str) -> None:
        wid = self._wid(pid)
        if wid is None:
            return
        if not self._has_prebudget(pid):
            self.ledger().settle(pid)
            return
        self.ledger().settle_pool(pid, wid)
        if PS(self.db.production(pid)["status"]) in TERMINAL:
            self.ledger().close_pool(pid)

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
        if not self._generation_allowed(pid):
            return "paused"

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

    def _generation_allowed(self, pid: str) -> bool:
        """Última barreira antes de qualquer chamada paga de imagem/vídeo: produção em PRODUCING e formato coerente com
        a apresentação gravada. Se não, recalcula (volta à validação) e não gasta nada."""
        status = PS(self.db.production(pid)["status"])
        if status != PS.PRODUCING:
            return False
        return self._enforce_format(pid, status)

    def _abort_unsent(self, pid: str, att, reason: str) -> None:
        """Tentativa criada mas ainda não enviada: falha técnica sem custo (nada sai do saldo) e fora da contagem."""
        self.db.update_attempt(att["id"], status="failed", error=reason[:1000], error_permanent=0, superseded=1,
                               finished_at=now(), estimated_cost_usd=0.0)
        self.db.add_event(pid, "attempt_aborted", f"{att['kind']} #{att['attempt_no']} não enviado: {reason}",
                          scene_idx=att["scene_idx"])

    def _submit(self, pid: str, att_id: str) -> str:
        att = self.db.attempt(att_id)
        if not self._generation_allowed(pid):
            self._abort_unsent(pid, att, "produção não está gerando ou o formato mudou")
            return "paused"
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
            self._pause(pid, f"{PROVIDER_BILLING_REASON}: {str(exc)[:300]}", budget_mod.PROVIDER_BILLING)
            budget_mod.notify_admin(self.db, pid, budget_mod.PROVIDER_BILLING, str(exc)[:300])

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
        if PS(self.db.production(pid)["status"]) in TERMINAL or att["status"] != "submitted":
            return "paused"   # cancelada no meio: o resultado não é mais buscado nem registrado (nada é cobrado)
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
        if PS(self.db.production(pid)["status"]) in TERMINAL or self.db.attempt(att_id)["status"] != "submitted":
            return "paused"   # cancelada enquanto o provedor respondia: descartado, sem registrar nem cobrar
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
        estimate = 0.0 if provider.simulated else budget_mod.review_cost(kind)
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
        estimate = 0.0 if provider.simulated else budget_mod.review_cost(kind)
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
        extra = fidelity.critical_criteria(self._facts(pid)) + review_criteria(self._training(pid))
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
                    hold = self._hold(pid, 0.0 if self.reviewer.simulated else budget_mod.review_cost(f"review_{kind}"),
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
            if result.decision == ReviewDecision.REJECTED:
                self._log_reason(pid, idx, kind, att["attempt_no"], result.reason_codes, "auto", critical=True)
            elif result.warnings:
                self._log_reason(pid, idx, kind, att["attempt_no"], result.reason_codes, "auto", critical=False)
                self.db.add_event(pid, "review_warning", f"{kind} #{att['attempt_no']} segue com aviso (não bloqueia): "
                                  + "; ".join(result.warnings)[:400], scene_idx=idx)

        autonomy = self._autonomy(pid)
        if result.decision == ReviewDecision.REJECTED and autonomy != "manual":
            row = self.db.scene(pid, idx)
            limit = (self.s.max_image_attempts if kind == "image" else self.s.max_video_attempts) + row[f"extra_{kind}_attempts"]
            if self.db.count_generation_attempts(pid, idx, kind) < limit:
                fix = fidelity.correction_text(result)
                history = fidelity.add_correction(self._corrections(row, kind), fix, source="auto",
                                                  attempt_no=att["attempt_no"])
                self.db.update_scene(pid, idx, **{f"current_{kind}_attempt": None})
                self._set_corrections(pid, idx, kind, history)
                self.db.add_event(pid, "auto_correction", f"{kind} reprovado na revisão automática; nova tentativa com "
                                  f"{len(history)} correção(ões) acumulada(s): {fix}", scene_idx=idx)
                return "progress"
            n = len(self.candidates(pid, idx, kind))
            self.db.set_scene_status(pid, idx, SS.BLOCKED, f"{kind} reprovado e tentativas esgotadas"
                                     + (f": compare as {n} versões lado a lado e aprove a melhor" if n > 1 else ""))
            return "idle"
        target = SS.AWAITING_IMAGE_APPROVAL if kind == "image" else SS.AWAITING_VIDEO_APPROVAL
        self.db.set_scene_status(pid, idx, target, f"revisão automática: {result.decision}")
        if result.decision in AUTO_APPROVE.get(autonomy, set()):
            self.approve(pid, idx, kind, f"aprovado pelo piloto ({autonomy}) após revisão automática: {result.decision}",
                         reviewer="piloto")
        return "progress"

    def _log_reason(self, pid: str, idx: int, kind: str, attempt_no, codes: list[str], source: str, *,
                    critical: bool) -> None:
        """Motivo de cada reprovação/aviso, só com categorias fixas (métricas do administrador, sem texto livre)."""
        self.db.add_event(pid, "retry_reason", f"{kind} #{attempt_no}: {', '.join(codes) or 'outro'}", scene_idx=idx,
                          data={"kind": kind, "attempt_no": attempt_no, "codes": codes or ["outro"],
                                "critical": critical, "source": source})

    def candidates(self, pid: str, idx: int, kind: str) -> list:
        """Versões geradas desta cena que ainda valem (não substituídas) — para a escolha lado a lado."""
        return [a for a in self.db.attempts(pid, scene_idx=idx, kind=kind)
                if a["status"] == "succeeded" and not a["superseded"] and a["output_path"]]

    def choose_attempt(self, pid: str, idx: int, kind: str, attempt_id: str, note: str = "") -> None:
        """Um clique: aprova uma das versões já geradas (tentativas esgotadas, ou o operador preferiu outra)."""
        if kind not in ("image", "video"):
            raise OrchestratorError("etapa inválida")
        if attempt_id not in {a["id"] for a in self.candidates(pid, idx, kind)}:
            raise OrchestratorError(f"versão não encontrada entre as da cena {idx}")
        row = self.db.scene(pid, idx)
        status = SS(row["status"])
        allowed = {SS.BLOCKED, SS.AWAITING_IMAGE_APPROVAL if kind == "image" else SS.AWAITING_VIDEO_APPROVAL}
        if status not in allowed:
            raise OrchestratorError(f"cena {idx} não está aguardando escolha (estado: {status})")
        if kind == "video" and not row["approved_image_attempt"]:
            raise OrchestratorError("cena sem imagem aprovada")
        att = self.db.attempt(attempt_id)
        self.db.update_scene(pid, idx, **{f"current_{kind}_attempt": attempt_id})
        self.db.add_event(pid, "version_chosen", f"{kind}: versão #{att['attempt_no']} escolhida lado a lado",
                          scene_idx=idx, data={"attempt_id": attempt_id})
        self.approve(pid, idx, kind, note or "escolhida lado a lado pelo operador")

    def set_anchor(self, pid: str, attempt_id: str | None) -> None:
        """Imagem-âncora do produto: uma imagem gerada que o operador aprovou como fiel vira a referência PRINCIPAL das
        próximas gerações (cenas já aprovadas não mudam). `None` remove a âncora."""
        if attempt_id is None:
            self.db.update_production(pid, anchor_json=None)
            self.db.add_event(pid, "anchor", "imagem-âncora removida")
            return
        att = self.db.conn.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if (att is None or att["production_id"] != pid or att["kind"] != "image" or att["status"] != "succeeded"
                or not att["output_path"]):
            raise OrchestratorError("a âncora precisa ser uma imagem gerada desta produção")
        self._storage(pid).path(att["output_path"])
        self.db.update_production(pid, anchor_json=json.dumps({"attempt_id": attempt_id, "path": att["output_path"],
                                                               "sha256": att["output_sha256"], "scene": att["scene_idx"]}))
        self.db.add_event(pid, "anchor", f"imagem-âncora: cena {att['scene_idx']}, versão #{att['attempt_no']} "
                          "(referência principal do produto nas próximas cenas)", scene_idx=att["scene_idx"])

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
                                     approved_image_attempt=att_id, image_correction=None, image_corrections_json=None)
            if previous and previous != att_id:
                for other in self.db.scenes(pid):
                    if idx in self._spec(other).image_dependencies() and other["status"] != SS.PENDING:
                        self._reset_scene(pid, other["idx"], f"imagem aprovada da cena {idx} mudou")
        else:
            self.db.set_scene_status(pid, idx, SS.VIDEO_APPROVED, "aprovado pelo operador",
                                     approved_video_attempt=att_id, video_correction=None, video_corrections_json=None)

    def adjustment_info(self, pid: str, idx: int) -> dict:
        """Ajustes pedidos pelo cliente nesta cena: incluídos no pré-orçamento, usados, autorizados e custo do extra."""
        row = self.db.scene(pid, idx)
        included = budget_mod.included_adjustments_per_scene()
        used = row["adjustments_used"] if "adjustments_used" in row.keys() else 0
        authorized = row["adjustments_authorized"] if "adjustments_authorized" in row.keys() else 0
        from .credits import to_cc
        return {"included": included, "used": used, "authorized": authorized,
                "free_left": max(included + authorized - used, 0),
                "extra_cost_cc": {st: to_cc(budget_mod.adjustment_cost_usd(self.s, st)) for st in ("image", "video")}}

    def _consume_adjustment(self, pid: str, idx: int, stage: str, authorize_extra: bool) -> None:
        """Ajuste pedido pelo cliente (só produções com pré-orçamento): os incluídos saem do que já foi reservado;
        além deles, só com autorização explícita — e aí o custo do ajuste é reservado do saldo antes de refazer."""
        info = self.adjustment_info(pid, idx)
        if info["free_left"] <= 0:
            cost = info["extra_cost_cc"][stage]
            if not authorize_extra:
                raise budget_mod.AdjustmentNeedsAuthorization(idx, stage, cost, info["included"], info["used"])
            n = info["authorized"] + 1
            wid = self._wid(pid)
            if wid is not None and self.db.production(pid)["mode"] == "real":
                self.ledger().reserve_pool(wid, pid, cost, ref=f"extra:{idx}:{n}",
                                           note=f"ajuste extra autorizado: cena {idx} ({stage})")
            self.db.update_scene(pid, idx, adjustments_authorized=n)
            self.db.add_event(pid, "adjustment_authorized", f"ajuste extra autorizado: {fmt_credits(cost)} créditos",
                              scene_idx=idx, data={"stage": stage, "cost_cc": cost, "n": n})
        row = self.db.scene(pid, idx)
        # Ajuste do cliente nunca esbarra no limite interno de tentativas (que existe contra laço automático).
        extra = {f"extra_{stage}_attempts": row[f"extra_{stage}_attempts"] + 1}
        if stage == "image":
            extra["extra_video_attempts"] = row["extra_video_attempts"] + 1
        self.db.update_scene(pid, idx, adjustments_used=info["used"] + 1, **extra)

    def reject(self, pid: str, idx: int, stage: str, note: str, *, redo_image: bool = False,
               authorize_extra: bool = False) -> None:
        if not note.strip():
            raise OrchestratorError("descreva a correção desejada (--note)")
        row = self.db.scene(pid, idx)
        stage_target = "image" if (stage == "image" or redo_image) else "video"
        if stage_target == "video" and not row["approved_image_attempt"]:
            raise OrchestratorError("cena sem imagem aprovada; reprove a imagem")
        if self._has_prebudget(pid):
            self._consume_adjustment(pid, idx, stage_target, authorize_extra)
            row = self.db.scene(pid, idx)
        att_id = row[f"current_{stage}_attempt"]
        if att_id:
            self.db.add_review(production_id=pid, scene_idx=idx, attempt_id=att_id, stage=stage, reviewer="human",
                               decision=ReviewDecision.REJECTED, result={"note": note})
        self._reopen_production(pid)
        cur_id = row[f"current_{stage_target}_attempt"]
        cur_no = self.db.attempt(cur_id)["attempt_no"] if cur_id else None
        self._log_reason(pid, idx, stage_target, cur_no, fidelity.reason_codes([note]), "human", critical=True)
        history = fidelity.add_correction(self._corrections(row, stage_target), note, source="human", attempt_no=cur_no)
        if stage_target == "image":
            self.db.supersede_attempts(pid, idx, "video", "imagem será refeita")
            self.db.set_scene_status(pid, idx, SS.GENERATING_IMAGE, f"correção solicitada: {note}",
                                     current_image_attempt=None, current_video_attempt=None,
                                     approved_video_attempt=None)
        else:
            if not row["approved_image_attempt"]:
                raise OrchestratorError("cena sem imagem aprovada; reprove a imagem")
            self.db.set_scene_status(pid, idx, SS.GENERATING_VIDEO, f"correção solicitada: {note}",
                                     current_video_attempt=None, approved_video_attempt=None)
        self._set_corrections(pid, idx, stage_target, history)

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
        """Encerra de vez. Nada novo é enviado (as barreiras de _hold/_submit recusam qualquer chamada depois daqui);
        tentativas ainda não enviadas são descartadas sem custo e as que já estavam no provedor são abandonadas sem
        cobrança do cliente. Acerta o que terminou e devolve o resto do pré-orçamento."""
        status = PS(self.db.production(pid)["status"])
        if status in TERMINAL:
            raise OrchestratorError(f"produção já encerrada ({PRODUCTION_LABELS[status].lower()})")
        self.db.set_production_status(pid, PS.CANCELLED, reason)
        dropped = 0
        for att in self.db.attempts(pid):
            if att["kind"] in ("image", "video", "workflow") and att["status"] in ("created", "submitted") and not att["superseded"]:
                sent = att["status"] == "submitted"
                if sent and att["kind"] == "workflow" and self.fal_gen is not None:   # cancela la na fal.ai (melhor esforco)
                    try:
                        self.fal_gen.cancel(att["remote_op_id"], json.loads(att["remote_meta_json"] or "{}"))
                    except Exception as exc:  # noqa: BLE001 — a execucao pode ja ter terminado; nada a fazer
                        log.info("[%s] cancelamento remoto do workflow nao confirmado (%s)", pid, type(exc).__name__)
                self.db.update_attempt(att["id"], status="failed", superseded=1, error_permanent=0, finished_at=now(),
                                       next_retry_at=None, estimated_cost_usd=att["estimated_cost_usd"] if sent else 0.0,
                                       error="cancelada pelo operador" + (": resultado do provedor descartado, sem "
                                                                          "cobrança" if sent else ": não enviado"))
                dropped += 1
        if dropped:
            self.db.add_event(pid, "cancel_inflight", f"{dropped} geração(ões) em andamento interrompida(s) sem cobrança")
        self._settle(pid)   # acerta o que terminou e devolve o resto do pré-orçamento

    def set_autonomy(self, pid: str, mode: str) -> None:
        """Muda o piloto. Assistido/Automático liberam as etapas pagas (dentro do limite) de uma vez."""
        if mode not in AUTONOMY:
            raise OrchestratorError("autonomia inválida")
        self.db.update_production(pid, autonomy=mode)
        self.db.add_event(pid, "autonomy", f"piloto: {mode}")
        if mode in ("assistido", "automatico"):
            self.set_go_ahead(pid, "all")
            # cenas que já esperam você e o piloto aprovaria: aplica a regra agora
            self._reconcile_autopilot(pid)

    def _reconcile_autopilot(self, pid: str) -> int:
        """Aplica a regra do piloto às cenas que JÁ esperam aprovação. A revisão e a aprovação automática são passos
        separados no banco: se o processo morre entre eles, a cena fica em `awaiting_*` e nada mais a aprovaria (a produção
        ficava em `producing` com o laço ocioso para sempre). Idempotente: só age sobre cenas ainda aguardando."""
        mode = self._autonomy(pid)
        if mode not in AUTO_APPROVE:
            return 0
        done = 0
        for row in self.db.scenes(pid):
            st = SS(row["status"])
            if st not in (SS.AWAITING_IMAGE_APPROVAL, SS.AWAITING_VIDEO_APPROVAL):
                continue
            kind = "image" if st == SS.AWAITING_IMAGE_APPROVAL else "video"
            att_id = row[f"current_{kind}_attempt"]
            if not att_id:
                continue
            reviews = [r for r in self.db.reviews_for_attempt(att_id) if r["reviewer"].startswith("auto:")]
            if reviews and ReviewDecision(reviews[-1]["decision"]) in AUTO_APPROVE[mode]:
                try:
                    self.approve(pid, row["idx"], kind, f"aprovado pelo piloto ({mode})", reviewer="piloto")
                    done += 1
                except OrchestratorError:
                    pass
        return done

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
        """Orçamento OPERACIONAL (freio interno). Só o administrador/operador muda; não mexe no saldo do cliente."""
        self.db.update_production(pid, budget_usd=budget_usd)
        self.db.add_event(pid, "budget_changed", f"novo limite operacional US${budget_usd:.2f}")

    def final_decision(self, pid: str, approve: bool, note: str = "", reviewer: str = "human") -> None:
        if self.db.production(pid)["status"] != PS.AWAITING_FINAL_REVIEW:
            raise OrchestratorError("produção não está aguardando revisão final")
        self.db.add_review(production_id=pid, scene_idx=None, attempt_id=None, stage="final", reviewer=reviewer,
                           decision=ReviewDecision.APPROVED if approve else ReviewDecision.REJECTED, result={"note": note})
        if approve:
            self.db.set_production_status(pid, PS.COMPLETED, note or "aprovada na revisão final")
            self._settle(pid)   # devolve ao saldo o que sobrou do pré-orçamento
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
        info = {"name": p.name, "product_url": p.product_url}
        if p.variant.strip():
            info["variant"] = p.variant
        if p.affiliate_link.strip():
            info["affiliate_link"] = p.affiliate_link
            info["note"] = "Link preservado exatamente como fornecido. Vincule este produto/variante na publicação."
        st.write_json("delivery/product.json", info)
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
