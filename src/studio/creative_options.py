"""Escolhas criativas em linguagem simples → instruções técnicas.

Na etapa Direção o usuário escolhe apenas o formato (presentation) e, se quiser, escreve um pedido livre
(details_text). Ambiente, proposta, tom e ajustes são PADRÕES FIXOS do servidor (ambiente neutro e limpo, tom
natural, sem ajustes). Nada é inferido do nome, da categoria ou das fotos. Produções antigas que salvaram
outras escolhas continuam válidas. Escolhas criativas nunca viram fatos do produto: os blocos em inglês só
descrevem cena e movimento.
"""

from __future__ import annotations

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

DEFAULT_ENVIRONMENT = "neutro"
DEFAULT_PROPOSAL = "details"
DEFAULT_TONE = "natural"

ENVIRONMENTS = {
    "neutro": {"label": "Ambiente neutro e limpo", "art": "ambiente_neutro",
               "desc": "Superfície clara, fundo discreto e luz suave."},
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

def details_for(presentation: str, environment: str) -> list[str]:
    return [k for k, d in DETAILS.items()
            if environment in d.get("envs", [environment]) and presentation in d.get("presentations", [presentation])]


def resolve(choices: CreativeChoices, name: str = "", category: str | None = None) -> CreativeChoices:
    """Troca "auto" pela proposta padrão e remove detalhes incompatíveis (name/category mantidos por compatibilidade)."""
    proposal = DEFAULT_PROPOSAL if choices.proposal == "auto" else choices.proposal
    allowed = details_for(choices.presentation, choices.environment)
    details = [d for d in dict.fromkeys(choices.details) if d in allowed]
    return choices.model_copy(update={"proposal": proposal, "details": details})


def summary_pt(choices: CreativeChoices) -> str:
    prop = {"practice": "Vídeo de demonstração, com o produto sendo manuseado",
            "details": "Vídeo de detalhes, com foco no que aparece nas fotos",
            "routine": "Vídeo de rotina, com o produto num momento comum do dia",
            "auto": "Vídeo de detalhes, com foco no que aparece nas fotos"}[choices.proposal]
    who = {"hands_only": "mostrado só pelas mãos da Bia",
           "product_only": "só o produto em cena, com movimentos de câmera",
           "presenter": "com a Bia aparecendo, sem falar"}[choices.presentation]
    env = (choices.environment_custom.strip() if choices.environment == "outro" and choices.environment_custom.strip()
           else ENVIRONMENTS[choices.environment]["label"].lower())
    text = f"{prop}, {who}, em {env}."
    if choices.tone != DEFAULT_TONE:  # só aparece em produções antigas que salvaram outro tom
        text += f" Tom {TONES[choices.tone]['label'].lower()}."
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


def ideas(name: str = "", category: str | None = None, presenter_available: bool = True) -> dict:
    """Escolha inicial fixa. name/category não são usados: nada é inferido do produto."""
    c = resolve(CreativeChoices(presentation="hands_only", proposal=DEFAULT_PROPOSAL, environment=DEFAULT_ENVIRONMENT,
                                tone=DEFAULT_TONE), name, category)
    return {
        "category": "geral",
        "suggested_environments": [DEFAULT_ENVIRONMENT],
        "recommended_proposal": DEFAULT_PROPOSAL,
        "proposal_reason": "Padrão fixo do estúdio: mostra só o que aparece nas fotos, sem sugerir usos ou benefícios.",
        "presentation_reason": "Formato inicial padrão: mãos da Bia, sem rosto e sem fala.",
        "tone_reason": "Aparência de gravação por celular, como no perfil de direção salvo.",
        "presenter_available": presenter_available,
        "ideas": [{"choices": c.model_dump(), "summary": summary_pt(c)}],
        "basis": "Direção padrão do estúdio. Não é sugerida a partir do nome, da categoria ou das fotos, que não foram analisadas.",
    }


def catalogue() -> dict:
    def strip(d):
        return {k: {kk: vv for kk, vv in v.items() if not kk.endswith("en")} for k, v in d.items()}
    return {"presentations": strip(PRESENTATIONS), "proposals": strip(PROPOSALS), "environments": ENVIRONMENTS,
            "tones": strip(TONES), "details": strip(DETAILS)}
