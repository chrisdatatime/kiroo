"""Fidelidade ao produto: ficha técnica visual, prompt negativo padrão, correções acumulativas e gravidade da revisão.

Motivação (prod_233c9227ba, mouse gamer, formato "Somente mãos"): a cena 1 foi reprovada 4 vezes alternando erro de mão
e erro de produto. Causas no código de então: (1) o prompt só dizia "reproduza o produto das fotos" — nada de botões,
lado esquerdo/direito, cabo ou logo por escrito; (2) a correção de cada nova tentativa SUBSTITUÍA a anterior, então
consertar a mão desfazia o conserto do produto e vice-versa; (3) qualquer defeito, inclusive estético de mão, reprovava.

Aqui ficam as peças determinísticas (sem custo): o que vai no prompt, o que o revisor recebe e como a decisão é tomada.
A extração da ficha (chamada multimodal) fica no provedor (`describe_product`) e é orquestrada em orchestrator.py.
"""

from __future__ import annotations

import re

from ..models import ProductButton, ProductFacts, ProductSheet, ReviewDecision, ReviewResult

# ------------------------------------------------------------------ prompt negativo padrão
DEFAULT_NEGATIVE_EN = (
    "AVOID (always): extra, missing, fused or duplicated fingers; a third hand; hands merging into the product; "
    "invented buttons, ports, wheels, lights, cables, straps, stickers or parts not visible in the official photos; "
    "a mirrored or left/right-swapped product layout; changed, invented or misspelled logos and text; warped or "
    "rescaled proportions; a different color, finish or variant."
)
# "Produto em destaque": o negativo padrão fala de dedos e mãos, o que PUXA o modelo para pôr mãos em cena.
# Aqui a regra é ausência total de pessoas, e o resto (fidelidade do produto) continua igual.
PRODUCT_ONLY_NEGATIVE_EN = (
    "AVOID (always): any person or body part in the frame — no hands, fingers, arms, faces, legs, silhouettes, "
    "reflections or shadows of people; invented buttons, ports, wheels, lights, cables, straps, stickers or parts not "
    "visible in the official photos; a mirrored or left/right-swapped product layout; changed, invented or misspelled "
    "logos and text; warped or rescaled proportions; a different color, finish or variant."
)
PRODUCT_ONLY_LOCK_EN = (
    "FINAL RULE (overrides anything above, including corrections and notes): PRODUCT ONLY. No hands, fingers, arms, "
    "people or any human body part may appear at any moment, not even partially at the frame edge. Movement comes "
    "only from the camera."
)


def negative_for(presenter_mode: str) -> str:
    return PRODUCT_ONLY_NEGATIVE_EN if str(presenter_mode) == "product_only" else DEFAULT_NEGATIVE_EN

# ------------------------------------------------------------------ ficha técnica
FACTS_INSTRUCTIONS = (
    "Você é técnico de catálogo. Descreva SOMENTE o que é visível nas fotos oficiais anexadas do produto, para que um "
    "gerador de imagens o reproduza sem erro. Não invente nada que não esteja visível; quando não der para ver, deixe "
    "vazio. Considere 'esquerdo/direito' com o produto visto de frente (ou de cima, se for um mouse/teclado: a parte "
    "mais próxima do usuário embaixo). Responda SOMENTE com JSON no formato "
    '{"summary_en":"one-paragraph visual description in English","colors":["..."],'
    '"buttons":[{"name":"","position":"","side":"left|right|center|top|bottom|front|back|unknown","color":""}],'
    '"button_count":0,"left_side":"","right_side":"","cable":"","logos":["text/logo and where"],'
    '"proportions":"","distinctive_parts":["..."],"asymmetric":false,"complexity":"simple|moderate|complex",'
    '"must_keep":["short English rules that must never change"]}. '
    "'asymmetric' = os lados esquerdo e direito são diferentes (ex.: botões laterais só de um lado, pegada destra). "
    "'complexity' = complex quando há muitos botões/partes pequenas, cabos, iluminação ou formas orgânicas."
)

# Palavras que indicam produto assimétrico ou com muitas partes (heurística gratuita, antes de qualquer chamada).
_COMPLEX_HINTS = re.compile(
    r"\b(mouse|teclado|keyboard|controle|joystick|gamepad|headset|fone|headphone|câmera|camera|drone|relógio|"
    r"smartwatch|furadeira|parafusadeira|ferramenta|secador|chapinha|máquina|liquidificador|batedeira|"
    r"gamer|rgb|ergonômic|ergonomic|canhot[oa]|destr[oa])\w*", re.I)


_SIDES = {"left", "right", "center", "top", "bottom", "front", "back", "unknown"}


def parse_facts(data: dict, *, source: str, simulated: bool = False) -> ProductFacts:
    """Valida a resposta do modelo campo a campo (dado externo): ignora o que não conhece, corta textos longos."""
    def s(v, n=300):
        return str(v or "").strip()[:n]

    def lst(v, n=12, size=200):
        return [s(x, size) for x in (v if isinstance(v, list) else []) if s(x, size)][:n]

    buttons = []
    for b in (data.get("buttons") if isinstance(data.get("buttons"), list) else [])[:20]:
        if not isinstance(b, dict):
            continue
        side = s(b.get("side"), 20).lower()
        buttons.append(ProductButton(name=s(b.get("name"), 80), position=s(b.get("position"), 120),
                                     side=side if side in _SIDES else "unknown",
                                     color=s(b.get("color"), 60)))
    count = data.get("button_count")
    count = int(count) if isinstance(count, (int, float)) and not isinstance(count, bool) and 0 <= count <= 60 else (
        len(buttons) or None)
    complexity = s(data.get("complexity"), 20).lower()
    return ProductFacts(
        summary_en=s(data.get("summary_en"), 900), colors=lst(data.get("colors"), 8, 60), buttons=buttons,
        button_count=count, left_side=s(data.get("left_side")), right_side=s(data.get("right_side")),
        cable=s(data.get("cable"), 200), logos=lst(data.get("logos"), 6), proportions=s(data.get("proportions")),
        distinctive_parts=lst(data.get("distinctive_parts")), asymmetric=bool(data.get("asymmetric")),
        complexity=complexity if complexity in ("simple", "moderate", "complex") else "simple",
        must_keep=lst(data.get("must_keep"), 12, 240), source=source, simulated=simulated)


def facts_from_operator(sheet: ProductSheet, *, simulated: bool = True) -> ProductFacts:
    """Sem IA (DEMO ou falha da chamada): a ficha vem só dos atributos que o operador digitou. Nunca supõe."""
    p = sheet.product
    attrs = p.visual_attributes
    colors = [v for k, v in attrs.items() if re.search(r"cor|color", k, re.I)]
    text = " ".join([p.name, p.category or "", " ".join(f"{k} {v}" for k, v in attrs.items())])
    complex_ = bool(_COMPLEX_HINTS.search(text))
    return ProductFacts(
        summary_en="", colors=colors[:4], must_keep=[f"{k}: {v}" for k, v in list(attrs.items())[:10]],
        asymmetric=complex_, complexity="complex" if complex_ else "simple",
        source="simulated" if simulated else "operator", simulated=simulated)


def facts_block(facts: ProductFacts | None) -> str:
    """Bloco em inglês para TODO prompt de imagem/vídeo. Vazio quando não há nada útil."""
    if facts is None:
        return ""
    lines = []
    if facts.summary_en:
        lines.append(f"Description: {facts.summary_en}")
    if facts.colors:
        lines.append("Colors (exact): " + ", ".join(facts.colors) + ".")
    if facts.button_count is not None or facts.buttons:
        n = facts.button_count if facts.button_count is not None else len(facts.buttons)
        detail = "; ".join(f"{b.name or 'button'} — {b.position or b.side}" + (f" ({b.color})" if b.color else "")
                           for b in facts.buttons)
        lines.append(f"Buttons/controls: exactly {n}" + (f": {detail}." if detail else ". No other buttons."))
    if facts.left_side:
        lines.append(f"LEFT side only: {facts.left_side}.")
    if facts.right_side:
        lines.append(f"RIGHT side only: {facts.right_side}.")
    if facts.asymmetric:
        lines.append("The product is ASYMMETRIC: never mirror it; keep the left/right layout exactly as in the photos.")
    if facts.cable:
        lines.append(f"Cable: {facts.cable}.")
    if facts.logos:
        lines.append("Logos/markings (only these, same place): " + "; ".join(facts.logos) + ".")
    if facts.proportions:
        lines.append(f"Proportions: {facts.proportions}.")
    if facts.distinctive_parts:
        lines.append("Distinctive parts: " + "; ".join(facts.distinctive_parts) + ".")
    for rule in facts.must_keep:
        lines.append(f"Must keep: {rule}.")
    if not lines:
        return ""
    return "PRODUCT SPEC SHEET (extracted from the official photos — every item must match exactly):\n- " + "\n- ".join(lines)


def critical_criteria(facts: ProductFacts | None) -> list[str]:
    """Critérios BLOQUEANTES do revisor (em português, como os do formato)."""
    out = ["CRÍTICO: produto igual às fotos oficiais (cor, forma, proporção, variante); nenhuma parte inventada"]
    if facts is None:
        return out
    if facts.button_count is not None:
        out.append(f"CRÍTICO: exatamente {facts.button_count} botões/controles visíveis, nas mesmas posições")
    if facts.asymmetric or facts.left_side or facts.right_side:
        out.append("CRÍTICO: lado esquerdo/direito do produto não pode estar trocado nem espelhado"
                   + (f" (esquerdo: {facts.left_side})" if facts.left_side else "")
                   + (f" (direito: {facts.right_side})" if facts.right_side else ""))
    if facts.cable:
        out.append(f"CRÍTICO: cabo conforme a ficha ({facts.cable})")
    if facts.logos:
        out.append("CRÍTICO: logos/inscrições só os da ficha, no mesmo lugar: " + "; ".join(facts.logos))
    if facts.colors:
        out.append("CRÍTICO: cores " + ", ".join(facts.colors))
    return out


def is_complex(facts: ProductFacts | None) -> bool:
    return bool(facts and (facts.asymmetric or facts.complexity == "complex"))


def looks_complex(name: str, category: str | None = "", attrs: dict | None = None) -> bool:
    """Heurística gratuita (antes de qualquer chamada paga): nome/categoria/atributos sugerem produto assimétrico."""
    text = " ".join([name or "", category or "", " ".join(f"{k} {v}" for k, v in (attrs or {}).items())])
    return bool(_COMPLEX_HINTS.search(text))


FORMAT_ADVICE = ("Produto assimétrico/complexo: recomendamos o formato \"Produto em destaque\" em vez de \"Somente "
                 "mãos\". Com mãos segurando, o gerador costuma errar a mão OU o produto (botões, lado, cabo).")

# ------------------------------------------------------------------ correções acumulativas
MAX_CORRECTIONS = 8


def add_correction(history: list[dict], text: str, *, source: str, attempt_no: int | None = None) -> list[dict]:
    """Acrescenta a correção nova sem perder as anteriores (sem repetir texto igual)."""
    text = (text or "").strip()
    out = [dict(h) for h in history]
    if text and not any(h["text"].strip().lower() == text.lower() for h in out):
        out.append({"text": text[:600], "source": source, "attempt": attempt_no})
    return out[-MAX_CORRECTIONS:]


def corrections_block(history: list[dict]) -> str:
    """As anteriores ficam como restrições JÁ RESOLVIDAS (não podem voltar); a última é a NOVA."""
    if not history:
        return ""
    *old, new = history
    lines = ["CORRECTIONS FROM PREVIOUS REVIEWS (cumulative — all of them apply at the same time):"]
    for h in old:
        lines.append(f"- ALREADY FIXED, KEEP IT FIXED: {h['text']}")
    lines.append(f"- NEW, APPLY STRICTLY: {new['text']}")
    lines.append("Do not undo an earlier fix while applying the new one.")
    return "\n".join(lines)


# ------------------------------------------------------------------ gravidade da revisão
REASONS = {
    "produto_cor": ("Cor do produto", r"\bcor\b|colou?r|tom\b|tonalidade"),
    "produto_botoes": ("Botões/controles", r"bot[aã]o|bot[õo]es|button|scroll|roda|clique|click|controle"),
    "produto_lado": ("Lado trocado/espelhado", r"espelh|mirror|lado (esquerdo|direito)|left|right|invertid|trocad"),
    "produto_cabo": ("Cabo", r"\bcabo\b|cable|fio\b|wire"),
    "produto_logo": ("Logo/inscrição", r"logo|marca|inscri|texto|text|lettering"),
    "produto_proporcao": ("Forma/proporção", r"propor|forma|formato|shape|tamanho|size|deform"),
    "produto_parte_inventada": ("Parte inventada", r"invent|acess[óo]rio|extra part|adicion|a mais|não existe"),
    "mao": ("Mãos", r"m[ãa]o|dedo|finger|hand|unha|polegar|anatom"),
}
CRITICAL_REASONS = {k for k in REASONS if k.startswith("produto_")} | {"pessoa_proibida"}
REASON_LABELS = {**{k: v[0] for k, v in REASONS.items()}, "produto_outro": "Produto (outro)", "estetica": "Estética",
                 "tecnico": "Técnico (proporção/duração)", "outro": "Outro",
                 "pessoa_proibida": "Mão/pessoa em 'Produto em destaque'"}


def reason_codes(texts: list[str]) -> list[str]:
    codes: list[str] = []
    for t in texts:
        hit = [k for k, (_, pat) in REASONS.items() if re.search(pat, t or "", re.I)]
        for k in hit or ["outro"]:
            if k not in codes:
                codes.append(k)
    return codes


def apply_severity(result: ReviewResult, hard_issues: list[str] | None = None) -> ReviewResult:
    """Regra de decisão: produto errado (ou falha técnica) BLOQUEIA; mão/estética vira AVISO.

    - O modelo informou `critical_issues` → reprova.
    - checks.produto == "problema" sem lista crítica → as `issues` viram críticas (seguro: reprova).
    - Reprovado só por questões estéticas (lista crítica vazia, checks.produto ok) → aprovado com avisos.
    - Resposta no formato antigo (sem classificação) → mantém a decisão do modelo.
    """
    r = result.model_copy(deep=True)
    hard = list(hard_issues or [])
    product_bad = (r.checks.get("produto") or "").lower() == "problema"
    classified = bool(r.critical_issues or r.warnings)
    if product_bad and not r.critical_issues:
        r.critical_issues = [i for i in r.issues if i not in r.warnings] or ["produto diferente das referências"]
        classified = True
    if hard:
        r.critical_issues = hard + r.critical_issues
    if r.critical_issues:
        r.decision = ReviewDecision.REJECTED
    elif classified and r.decision == ReviewDecision.REJECTED:
        r.decision = ReviewDecision.APPROVED   # só estética: segue, com aviso para o operador
    for i in r.critical_issues + r.warnings:
        if i not in r.issues:
            r.issues.append(i)
    codes = ["tecnico"] if hard else []
    model_critical = r.critical_issues[len(hard):]
    codes += [c if c in CRITICAL_REASONS else "produto_outro" for c in reason_codes(model_critical)] if model_critical else []
    codes += ["mao" if c == "mao" else "estetica" for c in reason_codes(r.warnings)]
    if r.decision == ReviewDecision.REJECTED and not codes:   # formato antigo: classifica pelo texto
        codes = reason_codes(r.issues)
    r.reason_codes = list(dict.fromkeys(codes))
    return r


# ------------------------------------------------------------------ "Produto em destaque": nenhuma pessoa em cena
PEOPLE_LABEL = "mão/pessoa em cena: 'Produto em destaque' não permite mãos nem pessoas"
PEOPLE_FIX_EN = ("Remove every hand, finger, arm and person from the frame; show only the product resting on the "
                 "surface; the camera alone provides the movement.")
_PEOPLE_RE = re.compile(r"m[ãa]os?\b|dedos?\b|polegar|unhas?\b|bra[çc]os?\b|pessoas?\b|rosto|corpo\b|pele\b|"
                        r"\bhands?\b|fingers?|thumbs?|nails?\b|\barms?\b|person|people|\bface\b|\bbody\b|skin\b", re.I)
_NEGATION_RE = re.compile(r"(\bsem\b|\bnenhum[a]?\b|\bn[ãa]o (h[áa]|aparece|tem)\b|aus[êe]ncia|\bausentes?\b|"
                          r"\bno\b|\bwithout\b|\bnone\b|\bfree of\b)[^.;]{0,25}$", re.I)
_PRESENT = {"problema", "presente", "presentes", "sim", "yes", "present", "visivel", "visível"}


def people_flagged(result: ReviewResult) -> list[str]:
    """Indícios de mão/pessoa na revisão: checagem marcada ou texto que cita mão/dedo/pessoa sem negar."""
    hits = [f"checagem {k}: {v}" for k, v in result.checks.items()
            if k.lower() in ("pessoas", "maos", "mãos", "people", "hands") and (v or "").strip().lower() in _PRESENT]
    for text in [*result.critical_issues, *result.warnings, *result.issues]:
        m = _PEOPLE_RE.search(text or "")
        if m and not _NEGATION_RE.search((text or "")[:m.start()]) and text != PEOPLE_LABEL:
            hits.append(text)
    return list(dict.fromkeys(hits))


def enforce_product_only(result: ReviewResult) -> ReviewResult:
    """Garantia dura de "Produto em destaque": qualquer indício de mão/pessoa REPROVA (não é aviso estético), com a
    correção certa para a próxima tentativa. A cena não chega ao vídeo com mão (nenhuma tentativa de vídeo é gasta)."""
    hits = people_flagged(result)
    if not hits:
        return result
    r = result.model_copy(deep=True)
    r.decision = ReviewDecision.REJECTED
    r.checks["pessoas"] = "problema"
    r.critical_issues = [PEOPLE_LABEL, *[c for c in r.critical_issues if c != PEOPLE_LABEL]]
    r.warnings = [w for w in r.warnings if w not in hits]
    if PEOPLE_LABEL not in r.issues:
        r.issues.insert(0, PEOPLE_LABEL)
    r.suggested_fix = PEOPLE_FIX_EN + (" " + r.suggested_fix if r.suggested_fix else "")
    r.reason_codes = list(dict.fromkeys(["pessoa_proibida", *[c for c in r.reason_codes if c not in ("mao", "estetica")]]))
    return r


def correction_text(result: ReviewResult) -> str:
    """O que vai para a próxima tentativa: a sugestão do revisor ou os problemas CRÍTICOS (não a estética)."""
    return (result.suggested_fix or "; ".join(result.critical_issues or result.issues)).strip()


__all__ = ["DEFAULT_NEGATIVE_EN", "PRODUCT_ONLY_NEGATIVE_EN", "PRODUCT_ONLY_LOCK_EN", "negative_for",
           "people_flagged", "enforce_product_only", "PEOPLE_LABEL", "FACTS_INSTRUCTIONS", "FORMAT_ADVICE", "parse_facts", "facts_from_operator",
           "facts_block", "critical_criteria", "is_complex", "looks_complex", "add_correction", "corrections_block",
           "apply_severity", "correction_text", "reason_codes", "REASON_LABELS", "CRITICAL_REASONS"]
