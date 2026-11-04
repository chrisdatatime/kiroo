"""Escolhas criativas em linguagem simples → instruções técnicas.

A sugestão inicial é feita por REGRAS a partir de dados textuais (nome, categoria) e dos
perfis salvos. Não há análise das fotos aqui. Escolhas criativas (ambiente, tom, proposta)
nunca viram fatos do produto: os blocos em inglês só descrevem cena e movimento.
"""

from __future__ import annotations

import unicodedata

from .models import CreativeChoices

PRESENTATIONS = {
    "hands_only": {
        "label": "Somente mãos",
        "desc": "As mãos da Bia seguram e mostram o produto. Sem rosto e sem fala.",
        "format": "maos_3cenas_15s",
    },
    "product_only": {
        "label": "Produto em destaque",
        "desc": "Só o produto em cena; o movimento vem da câmera. Sem pessoas.",
        "format": "produto_3cenas_15s",
    },
    "presenter": {
        "label": "Com apresentadora",
        "desc": "A Bia aparece segurando o produto, sem falar. Experimental: o rosto pode variar entre cenas.",
        "format": "bia_3cenas_15s",
    },
}

PROPOSALS = {
    "practice": {
        "label": "Mostrar na prática",
        "desc": "O produto é manuseado em gestos do dia a dia: segurar, levantar, apoiar.",
        "en": "Show the product being handled in natural everyday gestures (holding, lifting, setting it down). "
              "Do not demonstrate performance claims such as temperature, leak-proofing, durability or capacity.",
        "product_only_en": "Show the product as part of an everyday moment, with gentle camera movement. Do not "
                           "demonstrate performance claims such as temperature, leak-proofing, durability or capacity.",
    },
    "details": {
        "label": "Apresentar detalhes",
        "desc": "Planos próximos do que aparece nas fotos: tampa, alça, acabamento.",
        "en": "Emphasize close views of the details that are visible in the reference photos (lid, handle, finish, "
              "accessories, inscriptions), exactly as they appear.",
    },
    "routine": {
        "label": "Mostrar em uma rotina",
        "desc": "O produto aparece num momento comum do dia, sem contar história de uso.",
        "en": "Place the product in a believable everyday moment of the chosen setting, as a natural part of the "
              "scene. No story of personal use and no testimonial.",
    },
}

ENVIRONMENTS = {
    "cozinha": {"label": "Cozinha com luz natural", "art": "cozinha_sp_alto_padrao",
                "desc": "Bancada clara, armários de madeira natural e luz suave de janela; casa habitada."},
    "mesa_trabalho": {"label": "Mesa de trabalho organizada", "art": "mesa_trabalho_clara",
                      "desc": "Mesa de madeira clara, notebook fechado ao fundo e luz de janela."},
    "treino": {"label": "Rotina de treino", "art": "rotina_treino",
               "desc": "Canto de treino em casa: tapete de yoga, halteres ao fundo e luz da manhã."},
    "sala": {"label": "Sala de estar clara", "art": "sala_estar_clara",
             "desc": "Mesa lateral de madeira, sofá de linho desfocado e luz natural."},
    "outro": {"label": "Outro ambiente", "art": "ambiente_personalizado",
              "desc": "Descreva o lugar em poucas palavras."},
}

TONES = {
    "natural": {"label": "Natural e próximo", "en": "Look like a real smartphone recording at home: natural colors, "
                                                     "no studio polish."},
    "sofisticado": {"label": "Sofisticado e calmo", "en": "Calm, refined composition with soft contrast and slow "
                                                          "movements; still realistic, not a 3D render."},
    "leve": {"label": "Leve e luminoso", "en": "Bright, airy light and soft shadows; still realistic."},
}

DETAILS = {
    "luz_natural": {"label": "Luz natural", "en": "Soft natural daylight."},
    "fundo_organizado": {"label": "Fundo organizado", "en": "Tidy, uncluttered background."},
    "mostrar_detalhes": {"label": "Mostrar os detalhes", "en": "Make the visible details easy to see."},
    "movimentos_suaves": {"label": "Movimentos suaves", "en": "Slow, smooth movements."},
    "enquadramento_proximo": {"label": "Enquadramento próximo", "en": "Keep the framing close to the product."},
    "superficie_clara": {"label": "Superfície clara", "en": "Light-colored surface under the product.",
                         "envs": ["cozinha", "mesa_trabalho", "sala", "outro"]},
    "unhas_cuidadas": {"label": "Unhas bem cuidadas", "en": "Well-groomed nails as defined in the hands profile.",
                       "presentations": ["hands_only", "presenter"]},
}

# Categoria inferida por palavras do nome/categoria (sem olhar as fotos).
_CATEGORIES = [
    ("bebidas", ["copo", "garrafa", "squeeze", "caneca", "termica", "galao", "tumbler", "xicara", "cantil", "garrafinha"],
     ["cozinha", "mesa_trabalho", "treino"], "practice",
     "Copos e garrafas são entendidos mais rápido quando aparecem sendo segurados no dia a dia."),
    ("casa", ["panela", "pote", "utensilio", "organizador", "cozinha", "tabua", "prato", "talher", "vela", "decor"],
     ["cozinha", "sala", "mesa_trabalho"], "practice",
     "Itens de casa ficam mais claros quando aparecem no próprio ambiente de uso."),
    ("escritorio", ["caderno", "caneta", "mouse", "teclado", "suporte", "luminaria", "agenda", "fone"],
     ["mesa_trabalho", "sala", "cozinha"], "details",
     "Para acessórios de mesa, os detalhes visíveis dizem mais do que uma cena de uso."),
]
_FALLBACK = ("geral", ["sala", "mesa_trabalho", "cozinha"], "details",
             "Sem categoria reconhecida, mostrar os detalhes visíveis é o caminho mais seguro: não sugere usos nem "
             "benefícios.")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def infer_category(name: str, category: str | None) -> tuple[str, list[str], str, str]:
    haystack = _norm(f"{name} {category or ''}")
    for cat, words, envs, proposal, reason in _CATEGORIES:
        if any(w in haystack for w in words):
            return cat, envs, proposal, reason
    return _FALLBACK


def details_for(presentation: str, environment: str) -> list[str]:
    return [k for k, d in DETAILS.items()
            if environment in d.get("envs", [environment]) and presentation in d.get("presentations", [presentation])]


def resolve(choices: CreativeChoices, name: str = "", category: str | None = None) -> CreativeChoices:
    """Troca "você decide" pela proposta recomendada e remove detalhes incompatíveis."""
    proposal = choices.proposal
    if proposal == "auto":
        proposal = infer_category(name, category)[2]
    allowed = details_for(choices.presentation, choices.environment)
    details = [d for d in dict.fromkeys(choices.details) if d in allowed]
    return choices.model_copy(update={"proposal": proposal, "details": details})


def summary_pt(choices: CreativeChoices) -> str:
    prop = {"practice": "um vídeo de demonstração, com o produto sendo manuseado",
            "details": "um vídeo de detalhes, com foco no que aparece nas fotos",
            "routine": "um vídeo de rotina, com o produto num momento comum do dia",
            "auto": "um vídeo com a proposta que recomendamos"}[choices.proposal]
    who = {"hands_only": "mostrado só pelas mãos da Bia",
           "product_only": "só o produto em cena, com movimentos de câmera",
           "presenter": "com a Bia aparecendo, sem falar"}[choices.presentation]
    env = (choices.environment_custom.strip() if choices.environment == "outro" and choices.environment_custom.strip()
           else ENVIRONMENTS[choices.environment]["label"].lower())
    tone = TONES[choices.tone]["label"].lower()
    text = f"{prop[0].upper()}{prop[1:]}, {who}, em {env}. Tom {tone}."
    if choices.details:
        text += " Detalhes: " + ", ".join(DETAILS[d]["label"].lower() for d in choices.details if d in DETAILS) + "."
    return text


def compose_direction(choices: CreativeChoices) -> str:
    """Bloco técnico (inglês) acrescentado a todas as instruções de cena."""
    if choices.manual_direction and choices.manual_direction.strip():
        return choices.manual_direction.strip()
    lines = ["CREATIVE DIRECTION (chosen by the operator; never overrides product fidelity, the references or the "
             "rules above; never add on-screen text or product claims):"]
    prop = PROPOSALS.get(choices.proposal)
    if prop:
        key = "product_only_en" if choices.presentation == "product_only" and "product_only_en" in prop else "en"
        lines.append("- " + prop[key])
    lines.append("- " + TONES[choices.tone]["en"])
    for d in choices.details:
        if d in DETAILS:
            lines.append("- " + DETAILS[d]["en"])
    if choices.details_text.strip():
        lines.append("- Operator notes (may be written in Portuguese): " + choices.details_text.strip())
    return "\n".join(lines)


def environment_override(choices: CreativeChoices) -> str | None:
    if choices.environment == "outro" and choices.environment_custom.strip():
        return ("SETTING (described by the operator, may be written in Portuguese): " + choices.environment_custom.strip()
                + ". Realistic, tidy and lived-in; not a showroom.")
    return None


def profile_ids(choices: CreativeChoices) -> dict:
    return {"format": PRESENTATIONS[choices.presentation]["format"],
            "art_direction": ENVIRONMENTS[choices.environment]["art"], "presenter": "bia"}


def ideas(name: str, category: str | None, presenter_available: bool) -> dict:
    """Ideia recomendada + alternativas (para "Sugerir outra ideia"), todas por regras."""
    cat, envs, proposal, reason = infer_category(name, category)
    alt_props = [proposal] + [p for p in ("details", "routine", "practice") if p != proposal]
    tones = ["natural", "sofisticado", "leve"]
    out = []
    for i, env in enumerate(envs):
        c = CreativeChoices(presentation="hands_only", proposal=alt_props[i % len(alt_props)], environment=env,
                            tone=tones[i % len(tones)], details=["luz_natural", "movimentos_suaves"])
        c = resolve(c, name, category)
        out.append({"choices": c.model_dump(), "summary": summary_pt(c)})
    return {
        "category": cat,
        "suggested_environments": envs,
        "recommended_proposal": proposal,
        "proposal_reason": reason,
        "presentation_reason": "Formato definido no seu histórico: mãos da Bia, sem rosto e sem fala.",
        "tone_reason": "Aparência de gravação por celular, como no perfil de direção salvo.",
        "presenter_available": presenter_available,
        "ideas": out,
        "basis": "Sugestão por regras a partir do nome e da categoria do produto. As fotos não foram analisadas.",
    }


def catalogue() -> dict:
    def strip(d):
        return {k: {kk: vv for kk, vv in v.items() if not kk.endswith("en")} for k, v in d.items()}
    return {"presentations": strip(PRESENTATIONS), "proposals": strip(PROPOSALS), "environments": ENVIRONMENTS,
            "tones": strip(TONES), "details": strip(DETAILS)}
