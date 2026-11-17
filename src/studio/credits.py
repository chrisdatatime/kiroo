"""Livro-razão de créditos por workspace (Fase C).

Unidade: centésimo de crédito (inteiro), para não acumular arredondamento por chamada.
Ciclo de cada chamada paga:
  reserva (−estimado) antes de chamar → ao terminar, liberação (+reservado) e débito (−custo).
  Recusa sem custo = só a liberação (estorno). Reserva órfã (processo caiu antes de criar a tentativa) é liberada
  depois de ORPHAN_MINUTES.
O custo debitado segue a mesma regra do orçamento da produção: custo confirmado quando o provedor informa, senão o
estimado. Workspaces isentos (dono da plataforma) registram tudo, mas não precisam de saldo.
Entradas não são apagadas nem editadas; correções viram lançamentos de ajuste. `ext_ref` único torna cada lançamento
idempotente (os webhooks da Stripe repetem eventos).

Origem dos créditos (Fase 6, migração 16): toda entrada vira um LOTE (`credit_lots`) com origem
  bonus        bônus de boas-vindas (não expira)
  subscription créditos do plano (expiram no fim do ciclo; não acumulam)
  topup        avulso, liberações da equipe, ajustes e o saldo convertido na migração (não expiram)
O consumo segue a ordem bônus → plano → avulso (no plano, o que vence antes sai antes). Cada saída/volta fica em
`credit_lot_moves`; a devolução de uma reserva (erro técnico, `refund` no extrato) volta para os MESMOS lotes de onde
saiu. Saldo = soma do livro menos o que restou de lotes de plano já vencidos (a baixa vira o lançamento `expire` na
próxima escrita da conta).
"""

from __future__ import annotations

import math
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from .db import Database, new_id, now

ORPHAN_MINUTES = 15
# Serializa threads que compartilham UMA conexão (o orquestrador usa uma só); entre conexões/processos quem garante a
# exclusão é o BEGIN IMMEDIATE do SQLite (lock de escrita do arquivo), que é o que protege o saldo de verdade.
_LOCK = threading.RLock()

# O schema vive em migrations.py (PRAGMA user_version).

KINDS_IN = {"grant", "purchase", "adjust", "welcome_bonus", "subscription"}  # entradas (cada uma cria um lote)
# "welcome_bonus": 20 créditos uma vez por pessoa (welcome.py). Não é compra: não dá plano nem entra na receita, e
# nada o estorna (não reembolsável).
# Stripe (payments_stripe.py): "subscription" (créditos do ciclo do plano, com validade), "purchase" (avulso) e
# "reversal" (reembolso/contestação: tira só o que ainda não foi usado do lote daquela compra; o saldo não fica negativo).
LABELS = {"grant": "Créditos liberados", "purchase": "Compra", "adjust": "Ajuste", "reserve": "Reserva",
          "release": "Reserva devolvida", "debit": "Uso", "reversal": "Estorno de compra",
          "welcome_bonus": "Bônus de boas-vindas", "subscription": "Créditos do plano", "expire": "Créditos do plano expirados"}
LOT_ORIGINS = ("bonus", "subscription", "topup")             # ordem de consumo
ORIGIN_OF_KIND = {"welcome_bonus": "bonus", "subscription": "subscription", "purchase": "topup", "grant": "topup",
                  "adjust": "topup"}
ORIGIN_LABELS = {"bonus": "Bônus de boas-vindas", "subscription": "Créditos do plano", "topup": "Créditos avulsos"}
STAGES = {"image": "Imagens", "video": "Vídeos", "review_image": "Conferência das imagens",
          "review_video": "Conferência dos takes", "plan": "Direção (roteiro)",
          "workflow": "Pacote de vídeo e fotos"}


class InsufficientCredits(Exception):
    def __init__(self, balance_cc: int, needed_cc: int):
        super().__init__(f"saldo {balance_cc / 100:.2f} créditos, necessário {needed_cc / 100:.2f}")
        self.balance_cc = balance_cc
        self.needed_cc = needed_cc


def to_cc(usd: float) -> int:
    """US$ → centésimos de crédito pela política vigente (arredonda para cima)."""
    if not usd or usd <= 0:
        return 0
    from .billing import policy  # import tardio: billing importa o orquestrador
    p = policy()
    return math.ceil(usd * p.fx_brl_per_usd * p.margin / p.credit_price_brl * 100 - 1e-9)


def fmt_balance(cc: int) -> str:
    """Saldo para EXIBIÇÃO: crédito inteiro, arredondado para baixo (19,6 → 19; −0,4 → −1). O livro segue em
    centésimos; só o texto muda. Separador de milhar pt-BR (2.000)."""
    n = math.floor(int(cc) / 100)
    s = f"{abs(n):,}".replace(",", ".")
    return ("−" if n < 0 else "") + s


def fmt(cc: int) -> str:
    """Centésimos → texto em créditos (pt-BR)."""
    s = f"{abs(cc) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if s.endswith(",00"):
        s = s[:-3]
    return ("−" if cc < 0 else "") + s


# ------------------------------------------------------------------ saldo por origem (tela Configurações › Créditos)
def origin_rows(lots: list[dict]) -> list[dict]:
    """Pura (testada): barras por origem a partir dos lotes (`origin`, `received_cc` = o que entrou menos estornos,
    `left_cc` = o que resta se o lote ainda vale, `expires_at`). Plano: só o ciclo que vale agora. Na ordem de consumo;
    origens sem lote não aparecem."""
    by: dict[str, dict] = {}
    for lot in lots:
        o = lot["origin"]
        d = by.setdefault(o, {"received_cc": 0, "left_cc": 0, "expires_at": None})
        d["received_cc"] += max(int(lot["received_cc"]), 0)
        d["left_cc"] += max(int(lot["left_cc"]), 0)
        if lot.get("expires_at") and (d["expires_at"] is None or lot["expires_at"] < d["expires_at"]):
            d["expires_at"] = lot["expires_at"]
    out = []
    for key in LOT_ORIGINS:
        d = by.get(key)
        if not d or d["received_cc"] <= 0:
            continue
        out.append({"key": key, "label": ORIGIN_LABELS[key], "received_cc": d["received_cc"], "left_cc": d["left_cc"],
                    "received": fmt_balance(d["received_cc"]), "left": fmt_balance(d["left_cc"]),
                    "expires_at": d["expires_at"]})
    return out


# ------------------------------------------------------------------ extrato do cliente (texto, status, CSV)
STATUS = {"paid": "Pago", "done": "Concluído", "not_charged": "Não cobrado", "gift": "Presente", "reversed": "Estornado",
          "expired": "Expirado"}
CRLF = chr(13) + chr(10)


def fmt_entry(cc: int) -> str:
    """Valor de um lançamento em crédito INTEIRO para o extrato: entrada "+20", saída "−20", sem custo "0"."""
    n = int(abs(cc)) // 100
    if cc == 0 or n == 0:
        return "0"
    return ("+" if cc > 0 else "−") + f"{n:,}".replace(",", ".")


def fmt_charge(cc: int) -> str:
    """Quanto o vídeo custou, sem sinal: "20" ou "0"."""
    return f"{max(int(cc), 0) // 100:,}".replace(",", ".")


def entry_status(kind: str, amount_cc: int) -> tuple[str, str]:
    """Selo do extrato: (código, rótulo). Compra → Pago; vídeo → Concluído; devolução sem débito → Não cobrado;
    bônus/liberação → Presente; estorno de compra → Estornado; ajuste → Concluído."""
    code = {"purchase": "paid", "subscription": "paid", "reversal": "reversed", "welcome_bonus": "gift", "grant": "gift",
            "refund": "not_charged", "release": "not_charged", "expire": "expired"}.get(kind, "done")
    return code, STATUS[code]


def style_label(scene: str | None, platform: str | None = None) -> str:
    """Subtitulo do video fal.ai no extrato: "Casa Clara · Shopee Vídeo" (vazio para producoes de outro motor)."""
    from .prompts.production import platform_label, scene_label
    parts = [x for x in (scene_label(scene), platform_label(platform)) if x]
    return " · ".join(parts)


def entry_texts(kind: str, *, product: str = "", scene: str | None = None, platform: str | None = None, note: str = "", package: str | None = None,
                method: str | None = None) -> tuple[str, str]:
    """(título, subtítulo) do lançamento: "Compra · Pro" / "Pix", "Vídeo · Tênis" / "Casa Clara · Shopee Vídeo"."""
    from .plans import LABELS as PLAN_LABELS
    if kind in ("purchase", "reversal"):
        plan = PLAN_LABELS.get(package or "", "Avulso" if package else "")
        how = {"pix": "Pix", "card": "Cartão"}.get(method or "", "")
        head = "Compra" if kind == "purchase" else "Estorno de compra"
        return (f"{head} · {plan}" if plan else head), how
    if kind == "subscription":
        plan = PLAN_LABELS.get(package or "", "")
        return (f"Plano · {plan}" if plan else "Plano"), note or "Créditos do ciclo"
    if kind == "expire":
        return "Créditos do plano expirados", "Os créditos do plano não passam para o ciclo seguinte"
    if kind == "welcome_bonus":
        return "Bônus de boas-vindas", "Seu primeiro vídeo"
    if kind == "grant":
        return "Créditos liberados", note or "Presente da equipe"
    if kind == "adjust":
        return "Ajuste", note
    video = f"Vídeo · {product}" if product else "Vídeo"
    return video, style_label(scene, platform) or ("Falha técnica, sem custo" if kind == "refund" else "")


def _csv_cell(v) -> str:
    t = " ".join(str(v if v is not None else "").split())
    if t[:1] in ("=", "+", "-", "@"):   # planilha não pode tratar texto do usuário como fórmula
        t = "'" + t
    return '"' + t.replace('"', '""') + '"'


def statement_csv(rows: list[dict]) -> str:
    """CSV do extrato (separador ";", como o Excel em pt-BR espera). Valores em crédito inteiro; o texto livre é
    neutralizado contra injeção de fórmula. O valor ("+20", "−20", "0") é gerado por nós, não por texto do usuário."""
    lines = [";".join(_csv_cell(h) for h in ("Data", "Descrição", "Detalhe", "Status", "Créditos"))]
    for r in rows:
        at = str(r.get("at") or "")[:19].replace("T", " ")
        lines.append(";".join([_csv_cell(at), _csv_cell(r.get("title")), _csv_cell(r.get("subtitle")),
                               _csv_cell(r.get("status_label")), '"' + str(r.get("credits") or "0") + '"']))
    return CRLF.join(lines) + CRLF


class Ledger:
    def __init__(self, db: Database):
        self.db = db

    @contextmanager
    def _txn(self):
        """Transação de escrita com lock do SQLite (BEGIN IMMEDIATE): leitura do saldo + lançamento viram atômicos,
        mesmo entre conexões e processos diferentes. Espera o lock até o busy_timeout da conexão. Se o chamador já
        abriu uma transação, participa dela."""
        with _LOCK:
            if self.db.conn.in_transaction:
                yield
                return
            self.db.conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.db.conn.execute("ROLLBACK")
                raise
            self.db.conn.execute("COMMIT")

    def transaction(self):
        """Transação de escrita do livro (BEGIN IMMEDIATE) para quem precisa juntar checagens e lançamentos
        (ex.: limite diário do administrador + concessão + auditoria, tudo ou nada)."""
        return self._txn()

    # ------------------------------------------------------------- leitura
    def balance(self, wid: str) -> int:
        """Soma do livro VÁLIDO: tudo o que foi lançado, menos o que restou de lotes de plano já vencidos e ainda não
        baixados (a baixa vira lançamento `expire` na próxima escrita da conta)."""
        total = self.db.conn.execute("SELECT COALESCE(SUM(amount_cc),0) FROM credit_entries WHERE workspace_id=?",
                                     (wid,)).fetchone()[0]
        return total - self._pending_expired(wid)

    def _pending_expired(self, wid: str, at: str | None = None) -> int:
        return self.db.conn.execute(
            "SELECT COALESCE(SUM(remaining_cc),0) FROM credit_lots WHERE workspace_id=? AND closed_at IS NULL"
            " AND expires_at IS NOT NULL AND expires_at<=? AND remaining_cc>0", (wid, at or now())).fetchone()[0]

    def lots(self, wid: str, *, valid_only: bool = False) -> list[dict]:
        """Lotes da conta com o que entrou (menos estornos) e o que resta; `valid` = ainda não venceu nem foi baixado."""
        t = now()
        rows = self.db.conn.execute(
            "SELECT l.*, COALESCE((SELECT -SUM(m.amount_cc) FROM credit_lot_moves m JOIN credit_entries e ON e.id=m.entry_id"
            " WHERE m.lot_id=l.id AND e.kind='reversal'),0) revoked_cc FROM credit_lots l WHERE l.workspace_id=?"
            " ORDER BY l.created_at, l.rowid", (wid,)).fetchall()
        out = []
        for r in rows:
            valid = r["closed_at"] is None and (r["expires_at"] is None or r["expires_at"] > t)
            if valid_only and not valid:
                continue
            out.append({"id": r["id"], "origin": r["origin"], "amount_cc": r["amount_cc"], "remaining_cc": r["remaining_cc"],
                        "received_cc": r["amount_cc"] - r["revoked_cc"], "left_cc": r["remaining_cc"] if valid else 0,
                        "expires_at": r["expires_at"], "valid": valid, "source": r["source"], "payment_id": r["payment_id"]})
        return out

    def held(self, wid: str) -> int:
        """Reservas ainda abertas (positivo). No pré-orçamento, o que já virou uso (drawdown) sai da reserva."""
        return self.db.conn.execute(
            "SELECT COALESCE(-SUM(r.amount_cc),0) FROM credit_entries r WHERE r.workspace_id=?"
            " AND r.kind IN ('reserve','drawdown')"
            " AND NOT EXISTS (SELECT 1 FROM credit_entries x WHERE x.hold_id=r.hold_id AND x.kind='release')",
            (wid,)).fetchone()[0]

    def exempt(self, wid: str) -> bool:
        row = self.db.conn.execute("SELECT credits_exempt FROM workspaces WHERE id=?", (wid,)).fetchone()
        return bool(row and row[0])

    def summary(self, wid: str) -> dict:
        bal, held = self.balance(wid), self.held(wid)
        return {"balance_cc": bal, "held_cc": held, "available_cc": bal, "exempt": self.exempt(wid),
                "balance": fmt_balance(bal), "balance_exact": fmt(bal), "held": fmt_balance(held), "held_exact": fmt(held)}

    def origins(self, wid: str) -> list[dict]:
        """Saldo por origem (bônus, plano, avulso) para as barras da tela de Créditos. Plano: só o ciclo que vale."""
        return origin_rows([lot for lot in self.lots(wid) if lot["origin"] != "subscription" or lot["valid"]])

    def statement(self, wid: str, limit: int = 60) -> list[dict]:
        """Extrato do CLIENTE: o que entrou e o uso por vídeo (reserva+liberação+débito viram uma linha), com título,
        subtítulo, status e valor em crédito inteiro. O detalhe por chamada fica só no admin (`usage`)."""
        rows = self.db.conn.execute(
            "SELECT e.*, p.product_json, CASE WHEN p.engine='fal' THEN p.scene END scene, CASE WHEN p.engine='fal' THEN p.platform END platform, pay.package_code pay_pkg, pay.method pay_method"
            " FROM credit_entries e LEFT JOIN productions p ON p.id=e.production_id"
            " LEFT JOIN payments pay ON pay.id=e.payment_id"
            " WHERE e.workspace_id=? AND e.kind IN ('grant','purchase','adjust','debit','release','reversal','welcome_bonus',"
            "'subscription','expire')"
            " ORDER BY e.created_at DESC, e.rowid DESC LIMIT ?", (wid, limit * 3)).fetchall()
        debited = {r["hold_id"] for r in rows if r["kind"] == "debit"}
        out = []
        for r in rows:
            if r["kind"] == "release" and r["hold_id"] in debited:
                continue  # a liberação de uma reserva que virou débito não interessa no extrato
            kind = "refund" if r["kind"] == "release" else r["kind"]
            amount = 0 if kind == "refund" else r["amount_cc"]
            title, sub = entry_texts(kind, product=_title(r["product_json"]), scene=r["scene"], platform=r["platform"], note=r["note"] or "",
                                     package=r["pay_pkg"], method=r["pay_method"])
            status, status_label = entry_status(kind, amount)
            out.append({"id": r["id"], "kind": kind, "at": r["created_at"], "amount_cc": amount, "amount": fmt(amount),
                        "credits": fmt_entry(amount), "title": title, "subtitle": sub,
                        "status": status, "status_label": status_label,
                        "label": "Estorno (sem custo)" if kind == "refund" else LABELS.get(kind, kind),
                        "stage": STAGES.get(r["stage"] or "", r["stage"] or ""), "production_id": r["production_id"],
                        "product": _title(r["product_json"]), "note": r["note"] or ""})
            if len(out) >= limit:
                break
        return out

    def videos(self, wid: str, limit: int = 100) -> list[dict]:
        """"Por vídeo" do cliente: produto, estilo, data e créditos cobrados (0 = não cobrado, ex.: falha técnica).
        Só vídeos encerrados: os que têm débito ou devolução da reserva."""
        rows = self.db.conn.execute(
            "SELECT p.id, p.product_json, CASE WHEN p.engine='fal' THEN p.scene END scene,"
            " CASE WHEN p.engine='fal' THEN p.platform END platform, MAX(e.created_at) at,"
            " SUM(CASE WHEN e.kind='debit' THEN -e.amount_cc ELSE 0 END) cc"
            " FROM credit_entries e JOIN productions p ON p.id=e.production_id"
            " WHERE e.workspace_id=? AND e.kind IN ('debit','release') GROUP BY p.id ORDER BY at DESC LIMIT ?",
            (wid, limit)).fetchall()
        out = []
        for r in rows:
            status, status_label = entry_status("debit" if r["cc"] > 0 else "refund", -r["cc"])
            out.append({"production_id": r["id"], "product": _title(r["product_json"]), "style": style_label(r["scene"], r["platform"]),
                        "at": r["at"], "credits_cc": r["cc"], "credits": fmt_charge(r["cc"]),
                        "status": status, "status_label": status_label})
        return out

    def usage(self, wid: str) -> list[dict]:
        """Consumo (débitos) por produção e, dentro dela, por operação (`stages`) e por cena → operação (`scenes`).
        Cena None = o que não é de uma cena só (roteiro). Sai do próprio extrato: cada débito aponta a tentativa."""
        rows = self.db.conn.execute(
            "SELECT e.production_id, e.stage, a.scene_idx scene, SUM(-e.amount_cc) cc, COUNT(*) n, p.product_json"
            " FROM credit_entries e LEFT JOIN productions p ON p.id=e.production_id"
            " LEFT JOIN attempts a ON a.id=e.attempt_id"
            " WHERE e.workspace_id=? AND e.kind='debit' GROUP BY e.production_id, e.stage, a.scene_idx", (wid,)).fetchall()
        by: dict[str, dict] = {}
        for r in rows:
            d = by.setdefault(r["production_id"], {"production_id": r["production_id"], "product": _title(r["product_json"]),
                                                   "total_cc": 0, "stages": [], "_st": {}, "_sc": {}})
            d["total_cc"] += r["cc"]
            label = STAGES.get(r["stage"] or "", r["stage"] or "outros")
            st = d["_st"].setdefault(label, {"stage": label, "cc": 0, "calls": 0})
            st["cc"] += r["cc"]
            st["calls"] += r["n"]
            sc = d["_sc"].setdefault(r["scene"], {"scene": r["scene"], "cc": 0, "operations": []})
            sc["cc"] += r["cc"]
            sc["operations"].append({"operation": label, "cc": r["cc"], "credits": fmt(r["cc"]), "calls": r["n"]})
        out = sorted(by.values(), key=lambda d: -d["total_cc"])
        for d in out:
            d["total"] = fmt(d["total_cc"])
            d["stages"] = sorted(({**s, "credits": fmt(s["cc"])} for s in d.pop("_st").values()), key=lambda s: -s["cc"])
            scenes = d.pop("_sc")
            for sc in scenes.values():
                sc["credits"] = fmt(sc["cc"])
                sc["operations"].sort(key=lambda o: -o["cc"])
            # cenas em ordem; "sem cena" (roteiro) por último
            d["scenes"] = sorted(scenes.values(), key=lambda s: (s["scene"] is None, s["scene"] or 0))
        return out

    # ------------------------------------------------------------- escrita
    def _insert(self, *, lots: str = "auto", lot_id: str | None = None, expires_at: str | None = None,
                source: str | None = None, **f) -> str:
        """Grava o lançamento e o movimento dos lotes. `lots`: auto (pela espécie), new (cria lote), consume (ordem
        bônus → plano → avulso), return (volta aos lotes da reserva `hold_id`), lot (sai do lote `lot_id`), neutral."""
        eid = new_id("cre")
        f.setdefault("created_at", now())
        kind, amount, wid = f.get("kind"), int(f.get("amount_cc") or 0), f["workspace_id"]
        mode = self._lot_mode(kind, amount, f.get("hold_id"), lot_id) if lots == "auto" else lots
        if mode == "new":
            f.setdefault("origin", f.pop("origin", None) or ORIGIN_OF_KIND.get(kind, "topup"))
        cols = ", ".join(["id", *f])
        self.db.conn.execute(f"INSERT INTO credit_entries({cols}) VALUES ({', '.join('?' * (len(f) + 1))})",
                             (eid, *f.values()))
        if amount == 0 or mode == "neutral":
            return eid
        if mode == "new":
            self.db.conn.execute(
                "INSERT INTO credit_lots(id, workspace_id, origin, amount_cc, remaining_cc, expires_at, entry_id, source,"
                " payment_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id("lot"), wid, f["origin"], amount, amount, expires_at, eid, source or f.get("ext_ref"),
                 f.get("payment_id"), f["created_at"]))
        elif mode == "consume":
            self._consume(wid, eid, f.get("hold_id"), -amount)
        elif mode == "return":
            self._return(wid, eid, f.get("hold_id"), amount)
        elif mode == "lot":
            self._move(wid, lot_id, eid, f.get("hold_id"), amount)
        return eid

    def _lot_mode(self, kind: str, amount: int, hold_id: str | None, lot_id: str | None) -> str:
        if lot_id:
            return "lot"
        if kind == "drawdown":
            return "neutral"          # parte da reserva virou uso: o saldo não muda, os lotes também não
        if kind == "debit" and hold_id and self._hold_open(hold_id):
            return "neutral"          # débito pago pela reserva ainda aberta (pré-orçamento): já saiu dos lotes na reserva
        if amount > 0:
            return "return" if kind == "release" else "new"
        return "consume"

    def _hold_open(self, hold_id: str) -> bool:
        return self.db.conn.execute(
            "SELECT 1 FROM credit_entries r WHERE r.hold_id=? AND r.kind='reserve' AND NOT EXISTS"
            " (SELECT 1 FROM credit_entries x WHERE x.hold_id=r.hold_id AND x.kind='release') LIMIT 1", (hold_id,)).fetchone() is not None

    def _move(self, wid: str, lot_id: str | None, entry_id: str, hold_id: str | None, cc: int) -> None:
        self.db.conn.execute("INSERT INTO credit_lot_moves(workspace_id, lot_id, entry_id, hold_id, amount_cc, created_at)"
                             " VALUES (?,?,?,?,?,?)", (wid, lot_id, entry_id, hold_id, int(cc), now()))
        if lot_id:
            self.db.conn.execute("UPDATE credit_lots SET remaining_cc=remaining_cc+? WHERE id=?", (int(cc), lot_id))

    def _consume(self, wid: str, entry_id: str, hold_id: str | None, cc: int) -> None:
        """Tira `cc` dos lotes válidos na ordem bônus → plano → avulso (no plano, o que vence antes). O que faltar
        (conta isenta, saldo de antes da migração) fica registrado sem lote."""
        self._expire_due(wid)
        left = int(cc)
        rows = self.db.conn.execute(
            "SELECT id, remaining_cc FROM credit_lots WHERE workspace_id=? AND closed_at IS NULL AND remaining_cc>0"
            " AND (expires_at IS NULL OR expires_at>?) ORDER BY CASE origin WHEN 'bonus' THEN 0 WHEN 'subscription' THEN 1"
            " ELSE 2 END, COALESCE(expires_at,'9999'), created_at, rowid", (wid, now())).fetchall()
        for r in rows:
            if left <= 0:
                break
            take = min(left, int(r["remaining_cc"]))
            self._move(wid, r["id"], entry_id, hold_id, -take)
            left -= take
        if left > 0:
            self._move(wid, None, entry_id, hold_id, -left)

    def _return(self, wid: str, entry_id: str, hold_id: str | None, cc: int) -> None:
        """Devolve `cc` aos lotes de onde a reserva saiu, do último consumido para o primeiro (o uso efetivo fica nos
        primeiros da ordem). Lote vencido ou baixado recebe e já baixa de novo. Sem histórico (reserva de antes da
        migração): vira um lote avulso sem validade."""
        left = int(cc)
        if hold_id:
            taken: dict = {}
            for m in self.db.conn.execute("SELECT lot_id, amount_cc, id FROM credit_lot_moves WHERE hold_id=? ORDER BY id",
                                          (hold_id,)).fetchall():
                t = taken.setdefault(m["lot_id"], [0, 0])
                t[0] -= m["amount_cc"]                    # consumido líquido (saída − volta)
                if m["amount_cc"] < 0:
                    t[1] = m["id"]                        # último consumo deste lote
            for lot_id, (net, _) in sorted(taken.items(), key=lambda kv: -kv[1][1]):
                if left <= 0:
                    break
                give = min(left, net)
                if give <= 0:
                    continue
                self._move(wid, lot_id, entry_id, hold_id, give)
                left -= give
                if lot_id:
                    self._reclose(wid, lot_id)
        if left > 0:
            lid = new_id("lot")
            self.db.conn.execute(
                "INSERT INTO credit_lots(id, workspace_id, origin, amount_cc, remaining_cc, expires_at, entry_id, source,"
                " created_at) VALUES (?,?,?,?,0,NULL,?,?,?)", (lid, wid, "topup", left, entry_id, "return:legacy", now()))
            self._move(wid, lid, entry_id, hold_id, left)

    def _reclose(self, wid: str, lot_id: str) -> None:
        """Devolução caiu num lote que já venceu ou foi estornado: baixa o que voltou na hora."""
        lot = self.db.conn.execute("SELECT * FROM credit_lots WHERE id=?", (lot_id,)).fetchone()
        if lot is None or lot["remaining_cc"] <= 0:
            return
        expired = lot["expires_at"] is not None and lot["expires_at"] <= now()
        if expired or lot["closed_at"]:
            kind = "expire" if expired else "reversal"
            self._insert(workspace_id=wid, kind=kind, amount_cc=-int(lot["remaining_cc"]), lot_id=lot_id,
                         origin=lot["origin"], payment_id=lot["payment_id"],
                         note="devolução de lote vencido" if expired else "devolução de lote estornado")

    def _expire_due(self, wid: str) -> int:
        """Baixa os lotes de plano vencidos (lançamento `expire` com o que restou). Idempotente; devolve centésimos."""
        t = now()
        total = 0
        for lot in self.db.conn.execute("SELECT * FROM credit_lots WHERE workspace_id=? AND closed_at IS NULL"
                                        " AND expires_at IS NOT NULL AND expires_at<=?", (wid, t)).fetchall():
            if lot["remaining_cc"] > 0:
                self._insert(workspace_id=wid, kind="expire", amount_cc=-int(lot["remaining_cc"]), lot_id=lot["id"],
                             origin=lot["origin"], note="créditos do plano não usados no ciclo")
                total += int(lot["remaining_cc"])
            self.db.conn.execute("UPDATE credit_lots SET closed_at=? WHERE id=?", (t, lot["id"]))
        return total

    def expire_due(self, wid: str) -> int:
        with self._txn():
            return self._expire_due(wid)

    def add(self, wid: str, credits_cc: int, *, kind: str = "grant", note: str = "", ext_ref: str | None = None,
            by: str | None = None, origin: str | None = None, expires_at: str | None = None,
            payment_id: str | None = None) -> str:
        """Entrada (liberação, compra avulsa, crédito do plano, bônus, ajuste). Cada entrada positiva vira um lote da
        origem da espécie (ou `origin`); plano leva `expires_at`. Mesmo ext_ref = mesmo lançamento (idempotente)."""
        if kind not in KINDS_IN:
            raise ValueError("tipo de lançamento inválido")
        if kind != "adjust" and credits_cc <= 0:
            raise ValueError("a quantidade precisa ser positiva")
        if origin is not None and origin not in LOT_ORIGINS:
            raise ValueError("origem inválida")
        with self._txn():
            if ext_ref:
                row = self.db.conn.execute("SELECT id FROM credit_entries WHERE ext_ref=?", (ext_ref,)).fetchone()
                if row:
                    return row[0]
            self._expire_due(wid)
            f = dict(workspace_id=wid, kind=kind, amount_cc=int(credits_cc), note=note[:300], ext_ref=ext_ref, created_by=by)
            if payment_id:
                f["payment_id"] = payment_id
            if credits_cc > 0:
                f["origin"] = origin or ORIGIN_OF_KIND.get(kind, "topup")
            return self._insert(expires_at=expires_at, **f)

    def revoke_lot(self, lot_id: str, target_cc: int, *, note: str, close: bool = False) -> int:
        """Reembolso/contestação: leva o total já estornado deste lote até `target_cc`, tirando SÓ o que ainda não foi
        usado (o saldo não fica negativo). Idempotente (evento repetido não tira de novo). `close` baixa o lote (o que
        voltar depois para ele também sai). Devolve os centésimos tirados agora."""
        with self._txn():
            lot = self.db.conn.execute("SELECT * FROM credit_lots WHERE id=?", (lot_id,)).fetchone()
            if lot is None:
                return 0
            done = self.db.conn.execute(
                "SELECT COALESCE(-SUM(m.amount_cc),0) FROM credit_lot_moves m JOIN credit_entries e ON e.id=m.entry_id"
                " WHERE m.lot_id=? AND e.kind='reversal'", (lot_id,)).fetchone()[0]
            take = max(min(int(target_cc) - int(done), int(lot["remaining_cc"])), 0)
            if take:
                self._insert(workspace_id=lot["workspace_id"], kind="reversal", amount_cc=-take, lot_id=lot_id,
                             origin=lot["origin"], payment_id=lot["payment_id"], note=note[:300])
            if close and lot["closed_at"] is None:
                self.db.conn.execute("UPDATE credit_lots SET closed_at=? WHERE id=?", (now(), lot_id))
        return take

    def hold(self, wid: str, pid: str, usd: float, stage: str) -> str | None:
        """Reserva antes de uma chamada paga. Sem saldo → InsufficientCredits (nada é reservado)."""
        cc = to_cc(usd)
        if cc <= 0:
            return None
        hid = new_id("hold")
        with self._txn():   # saldo lido e reserva gravada sob o mesmo lock: o saldo nunca fica negativo
            bal = self.balance(wid)
            if not self.exempt(wid) and bal < cc:
                raise InsufficientCredits(bal, cc)
            self._insert(workspace_id=wid, kind="reserve", amount_cc=-cc, usd=usd, hold_id=hid, production_id=pid,
                         stage=stage, ext_ref=f"reserve:{hid}")
        return hid

    def attach(self, hid: str | None, attempt_id: str) -> None:
        if hid:
            self.db.conn.execute("UPDATE credit_entries SET attempt_id=? WHERE hold_id=? AND kind='reserve'", (attempt_id, hid))

    def release(self, hid: str | None, note: str = "") -> None:
        """Devolve a reserva sem cobrar (chamada não aconteceu ou foi recusada sem custo)."""
        if not hid:
            return
        with self._txn():
            r = self.db.conn.execute("SELECT * FROM credit_entries WHERE hold_id=? AND kind='reserve'", (hid,)).fetchone()
            if r is None or self.db.conn.execute("SELECT 1 FROM credit_entries WHERE ext_ref=?", (f"release:{hid}",)).fetchone():
                return
            self._insert(workspace_id=r["workspace_id"], kind="release", amount_cc=-r["amount_cc"], hold_id=hid,
                         production_id=r["production_id"], attempt_id=r["attempt_id"], stage=r["stage"], note=note[:300],
                         ext_ref=f"release:{hid}")

    def close_direct(self, hid: str | None, usd: float, note: str = "") -> None:
        """Fecha uma reserva sem produção (teste de treinamento): devolve a reserva e cobra o custo real."""
        if not hid:
            return
        with self._txn():   # liberação e débito juntos: nunca fica só um dos dois
            r = self.db.conn.execute("SELECT * FROM credit_entries WHERE hold_id=? AND kind='reserve'", (hid,)).fetchone()
            self.release(hid, note)
            charge = to_cc(usd)
            if r is not None and charge:
                self._insert(workspace_id=r["workspace_id"], kind="debit", amount_cc=-charge, usd=usd, hold_id=hid, production_id=None,
                             stage=r["stage"], ext_ref=f"debit:{hid}", note=note[:300])

    def settle(self, pid: str) -> int:
        """Fecha as reservas cujas tentativas terminaram. Idempotente; devolve quantas fechou."""
        open_holds = self.db.conn.execute(
            "SELECT r.* FROM credit_entries r WHERE r.production_id=? AND r.kind='reserve'"
            " AND COALESCE(r.stage,'')<>'prebudget'"   # o pré-orçamento tem acerto próprio (settle_pool/close_pool)
            " AND NOT EXISTS (SELECT 1 FROM credit_entries x WHERE x.hold_id=r.hold_id AND x.kind='release')",
            (pid,)).fetchall()
        closed = 0
        stale = (datetime.now(timezone.utc) - timedelta(minutes=ORPHAN_MINUTES)).isoformat(timespec="seconds")
        for r in open_holds:
            hid = r["hold_id"]
            if not r["attempt_id"]:
                if r["created_at"] < stale:
                    self.release(hid, "reserva sem chamada (processo interrompido)")
                    closed += 1
                continue
            att = self.db.attempt(r["attempt_id"])
            if att is None or att["status"] not in ("succeeded", "failed"):
                continue
            usd = attempt_cost_usd(att)
            charge = 0 if att["status"] == "failed" else to_cc(usd)   # falha técnica: estorna, não cobra
            with self._txn():
                if self.db.conn.execute("SELECT 1 FROM credit_entries WHERE ext_ref=?", (f"release:{hid}",)).fetchone():
                    continue
                self._insert(workspace_id=r["workspace_id"], kind="release", amount_cc=-r["amount_cc"], hold_id=hid,
                             production_id=pid, attempt_id=att["id"], stage=r["stage"], ext_ref=f"release:{hid}",
                             note="" if charge else ("falha técnica: sem custo" if att["status"] == "failed"
                                                     else "recusado sem custo"))
                if charge:
                    self._insert(workspace_id=r["workspace_id"], kind="debit", amount_cc=-charge, usd=usd, hold_id=hid,
                                 production_id=pid, attempt_id=att["id"], stage=r["stage"], ext_ref=f"debit:{hid}",
                                 note=f"{att['kind']} #{att['attempt_no']}")
            closed += 1
        return closed

    # ------------------------------------------------- pré-orçamento da produção (saldo do cliente)
    @staticmethod
    def pool_id(pid: str) -> str:
        return f"pool_{pid}"

    def can_reserve(self, wid: str, cc: int) -> None:
        """Checagem antecipada (antes de receber fotos/criar a produção). Sem saldo → InsufficientCredits."""
        bal = self.balance(wid)
        if cc > 0 and not self.exempt(wid) and bal < cc:
            raise InsufficientCredits(bal, cc)

    def reserve_pool(self, wid: str, pid: str, cc: int, *, ref: str, usd: float | None = None, note: str = "") -> bool:
        """Reserva (parte do) pré-orçamento da produção. `ref` torna a reserva idempotente (base, extra:N...).
        Devolve False se a mesma reserva já existia. Sem saldo → InsufficientCredits (nada é reservado)."""
        if cc <= 0:
            return False
        hid = self.pool_id(pid)
        with self._txn():
            if self.db.conn.execute("SELECT 1 FROM credit_entries WHERE ext_ref=?", (f"pool:{pid}:{ref}",)).fetchone():
                return False
            if self.db.conn.execute("SELECT 1 FROM credit_entries WHERE ext_ref=?", (f"release:{hid}",)).fetchone():
                raise ValueError("o pré-orçamento desta produção já foi encerrado")
            bal = self.balance(wid)
            if not self.exempt(wid) and bal < cc:
                raise InsufficientCredits(bal, cc)
            self._insert(workspace_id=wid, kind="reserve", amount_cc=-int(cc), usd=usd, hold_id=hid, production_id=pid,
                         stage="prebudget", ext_ref=f"pool:{pid}:{ref}", note=note[:300])
        return True

    def pool_state(self, pid: str) -> dict:
        hid = self.pool_id(pid)
        rows = self.db.conn.execute("SELECT kind, amount_cc FROM credit_entries WHERE hold_id=?", (hid,)).fetchall()
        reserved = sum(-r["amount_cc"] for r in rows if r["kind"] == "reserve")
        drawn = sum(r["amount_cc"] for r in rows if r["kind"] == "drawdown")
        closed = any(r["kind"] == "release" for r in rows)
        return {"reserved_cc": reserved, "used_cc": drawn, "remaining_cc": max(reserved - drawn, 0), "closed": closed}

    def settle_pool(self, pid: str, wid: str) -> int:
        """Acerta com o cliente cada tentativa terminada da produção (uma decisão por tentativa, idempotente):
        sucesso → uso tirado do pré-orçamento (até o que foi reservado; acima disso o Kiroo absorve);
        falha técnica (erro do provedor, tempo esgotado) → nada sai do pré-orçamento."""
        rows = self.db.conn.execute(
            "SELECT * FROM attempts a WHERE a.production_id=? AND a.status IN ('succeeded','failed')"
            " AND NOT EXISTS (SELECT 1 FROM production_charges c WHERE c.attempt_id=a.id) ORDER BY a.created_at, a.rowid",
            (pid,)).fetchall()
        done = 0
        for att in rows:
            usd = attempt_cost_usd(att)
            with self._txn():
                if self.db.conn.execute("SELECT 1 FROM production_charges WHERE attempt_id=?", (att["id"],)).fetchone():
                    continue
                state = self.pool_state(pid)
                if att["status"] == "failed":
                    decision, charge = "technical_failure", 0
                else:
                    # pacote fal.ai: preço FIXO em créditos (catálogo), nunca o custo real convertido
                    cost = _fixed_price_cc() if att["kind"] == "workflow" else to_cc(usd)
                    charge = 0 if state["closed"] else min(cost, state["remaining_cc"])
                    decision = "charged" if charge == cost else "absorbed"   # absorbed: o Kiroo paga a diferença
                if charge > 0:
                    hid = self.pool_id(pid)
                    self._insert(workspace_id=wid, kind="drawdown", amount_cc=charge, hold_id=hid, production_id=pid,
                                 attempt_id=att["id"], stage=att["kind"], ext_ref=f"draw:{att['id']}")
                    self._insert(workspace_id=wid, kind="debit", amount_cc=-charge, usd=usd, hold_id=hid,
                                 production_id=pid, attempt_id=att["id"], stage=att["kind"], ext_ref=f"debit:{att['id']}",
                                 note=f"{att['kind']} #{att['attempt_no']}")
                self.db.conn.execute(
                    "INSERT INTO production_charges(attempt_id, production_id, workspace_id, scene_idx, operation, provider,"
                    " model, cost_usd, charged_cc, decision, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (att["id"], pid, wid, att["scene_idx"], att["kind"], att["provider"], att["model"], usd, charge,
                     decision, now()))
            done += 1
        return done

    def close_pool(self, pid: str, note: str = "produção encerrada: devolve o que sobrou do pré-orçamento") -> int:
        """Devolve ao saldo o que não foi usado do pré-orçamento. Idempotente. Devolve os centésimos liberados."""
        hid = self.pool_id(pid)
        with self._txn():
            if self.db.conn.execute("SELECT 1 FROM credit_entries WHERE ext_ref=?", (f"release:{hid}",)).fetchone():
                return 0
            row = self.db.conn.execute("SELECT workspace_id FROM credit_entries WHERE hold_id=? AND kind='reserve'",
                                       (hid,)).fetchone()
            if row is None:
                return 0
            back = self.pool_state(pid)["remaining_cc"]
            self._insert(workspace_id=row["workspace_id"], kind="release", amount_cc=back, hold_id=hid, production_id=pid,
                         stage="prebudget", ext_ref=f"release:{hid}", note=note[:300])
        return back

    def charges(self, pid: str) -> list[dict]:
        """Registro por produção, cena, operação e provedor (o que custou ao Kiroo e o que saiu do cliente)."""
        return [dict(r) for r in self.db.conn.execute(
            "SELECT * FROM production_charges WHERE production_id=? ORDER BY created_at, rowid", (pid,))]


def _fixed_price_cc() -> int:
    from .catalog import video_price_cc
    return video_price_cc()


def attempt_cost_usd(att) -> float:
    """Mesma regra do orçamento: custo confirmado pelo provedor quando houver (e não simulado), senão o estimado."""
    if not att["simulated"] and att["confirmed_cost_usd"] is not None:
        return att["confirmed_cost_usd"]
    return att["estimated_cost_usd"] or 0.0


def _title(product_json: str | None) -> str:
    if not product_json:
        return ""
    import json
    try:
        return (json.loads(product_json).get("name") or "")[:80]
    except ValueError:
        return ""
