"""Direção criativa: roteiro por cena a partir do formato, perfis e ficha validada.

1. Monta um rascunho determinístico a partir do template do formato (com rastreio de origem).
2. O planner (IA ou simulado) pode refinar campos textuais.
3. O código valida o resultado antes de qualquer geração.
"""

from __future__ import annotations

import re
from string import Template

from . import craft
from ..claims import find_unsupported_claims
from ..models import PresenterMode, ProductSheet, SceneSpec, Script, TextOverlay


def summary_pt(choices) -> str:
    from ..creative_options import summary_pt as _s
    return _s(choices)


def product_block(sheet: ProductSheet) -> str:
    p = sheet.product
    attrs = "; ".join(f"{k}: {v}" for k, v in p.visual_attributes.items())
    variant = f"; variant: \"{p.variant.strip()}\"" if p.variant.strip() else ""
    lines = [
        f"PRODUCT: faithfully reproduce the exact product shown in the official reference photos "
        f"(listing name: \"{p.name}\"{variant}).",
    ]
    if attrs:
        lines.append(f"Visible attributes to preserve exactly: {attrs}.")
    lines.append("Keep color, variant, shape, proportions, lid, handle, finish and accessories identical to the "
                 "references. Do not add straws, logos, brand marks, inscriptions or accessories that are not "
                 "visible in the references.")
    return " ".join(lines)


def build_draft(sheet: ProductSheet, profiles: dict) -> Script:
    fmt = profiles["format"]["data"]
    art = profiles["art_direction"]["data"]
    presenter = profiles["presenter"]["data"]
    mode = PresenterMode(fmt["presenter_mode"])
    mode_cfg = presenter["modes"][mode.value]
    hands = mode_cfg["prompt_block_en"] + (" " + mode_cfg["gesture_en"] if mode_cfg.get("gesture_en") else "")
    values = {
        "product_block": product_block(sheet),
        "environment": art["environment_en"],
        "lighting": art["lighting_en"],
        "camera": art["camera_en"],
        "negative": art["negative_en"],
        "hands": hands,
    }
    direction = ""
    creative = sheet.product.creative
    if creative is not None:
        from ..creative_options import compose_direction, environment_override, resolve
        creative = resolve(creative, sheet.product.name, sheet.product.category)
        values["environment"] = environment_override(creative) or values["environment"]
        direction = "\n\n" + compose_direction(creative)
    elif sheet.product.video_context.strip():
        direction = ("\n\nOPERATOR CREATIVE DIRECTION (may be written in Portuguese; follow it unless it conflicts with "
                     "product fidelity, the references or the rules above; never add on-screen text or claims): "
                     + sheet.product.video_context.strip())
    scenes = []
    for bp in fmt["scenes"]:
        # manual dos especialistas (agents/craft.py) entre o template e a direção do operador, que vem por último
        shot = craft.shot_of(bp, bp["index"], len(fmt["scenes"]))
        img_craft = "\n\n" + craft.image_craft(shot, sheet, mode)
        mot_craft = "\n\n" + craft.motion_craft(shot, bp["target_duration_s"], mode)
        scenes.append(SceneSpec(
            index=bp["index"], title=bp["title"], objective=bp["objective"], framing=bp["framing"],
            presenter_mode=mode, references=bp["references"],
            image_prompt=Template(bp["image_prompt"]).safe_substitute(values) + img_craft + direction,
            animation_prompt=Template(bp["animation_prompt"]).safe_substitute(values) + mot_craft + direction,
            motion=bp["motion"], target_duration_s=bp["target_duration_s"],
            constraints=bp.get("constraints", []), approval_criteria=bp.get("approval_criteria", []),
        ))
    overlays = [TextOverlay(**o) for o in fmt.get("overlays", [])]
    return Script(format_id=fmt["id"], aspect_ratio=fmt["aspect_ratio"], total_target_s=fmt["total_target_s"],
                  scenes=scenes, overlays=overlays, audio=fmt.get("audio", "silent"))


VALID_REF_PREFIXES = ("product:", "presenter:", "scene:")
# Instrução POSITIVA de mão/pessoa (não a negação "no hands"): bloco HANDS do perfil, mão segurando/ajustando etc.
_HAND_ACTION = re.compile(r"\bHANDS:|\bPRESENTER:|\b(right|left|her|his|a|the|two|one)\s+hands?\b(?!\s*,)|"
                          r"\bhands?\s+(hold|holds|holding|grip|grips|gripping|adjust|adjusts|lift|lifts|enter|enters|"
                          r"reach|reaches|touch|touches|pick|picks|place|places|rotate|rotates|turn|turns)\b|"
                          r"\bfingers?\s+(press|presses|tap|taps|touch|touches)\b", re.I)
_PLACEHOLDER = re.compile(r"\$\{?(product_block|environment|lighting|camera|negative|hands)")


def validate_script(script: Script, profiles: dict, sheet: ProductSheet) -> list[str]:
    fmt = profiles["format"]["data"]
    errors = []
    if len(script.scenes) != len(fmt["scenes"]):
        errors.append(f"roteiro tem {len(script.scenes)} cenas; formato exige {len(fmt['scenes'])}")
    indices = [s.index for s in script.scenes]
    if indices != list(range(1, len(script.scenes) + 1)):
        errors.append(f"índices de cena inválidos: {indices}")
    total = sum(s.target_duration_s for s in script.scenes)
    if abs(total - fmt["total_target_s"]) > fmt.get("duration_tolerance_s", 1.0):
        errors.append(f"duração somada {total:.1f}s fora de {fmt['total_target_s']}±{fmt.get('duration_tolerance_s')}s")
    for s in script.scenes:
        tag = f"cena {s.index}"
        if not s.image_prompt.strip() or not s.animation_prompt.strip():
            errors.append(f"{tag}: prompt vazio")
        if _PLACEHOLDER.search(s.image_prompt) or _PLACEHOLDER.search(s.animation_prompt):
            errors.append(f"{tag}: placeholder não resolvido no prompt")
        if not 2.0 <= s.target_duration_s <= 10.0:
            errors.append(f"{tag}: duração útil {s.target_duration_s}s fora de 2–10s")
        for ref in s.references:
            if not ref.startswith(VALID_REF_PREFIXES):
                errors.append(f"{tag}: referência desconhecida {ref}")
        for dep in s.image_dependencies():
            if dep >= s.index:
                errors.append(f"{tag}: depende da cena {dep}, que não é anterior")
        if not any(r.startswith("product:") for r in s.references):
            errors.append(f"{tag}: sem referência oficial do produto")
    if fmt.get("presenter_mode") == PresenterMode.PRODUCT_ONLY.value:
        # "Produto em destaque": o bloqueio de pessoas tem de sobreviver ao planejador e nenhuma instrução de mão entra
        no_people = (profiles.get("presenter", {}).get("data", {}).get("modes", {}).get("product_only", {})
                     .get("prompt_block_en") or "No people, no hands")
        for s in script.scenes:
            tag = f"cena {s.index}"
            if str(s.presenter_mode) != PresenterMode.PRODUCT_ONLY.value:
                errors.append(f"{tag}: modo {s.presenter_mode} num formato só de produto")
            if no_people not in s.image_prompt:
                errors.append(f"{tag}: prompt de imagem perdeu o bloqueio de pessoas/mãos")
            if "no people" not in s.animation_prompt.lower():
                errors.append(f"{tag}: prompt de animação perdeu o bloqueio de pessoas/mãos")
            if _HAND_ACTION.search(s.image_prompt) or _HAND_ACTION.search(s.animation_prompt):
                errors.append(f"{tag}: instrução de mão/pessoa num formato só de produto")
    for ov in script.overlays:
        bad = find_unsupported_claims(ov.text, sheet)
        if bad:
            errors.append(f"texto de tela com alegação não comprovada {bad}: {ov.text!r}")
    return errors


def render_markdown(script: Script, sheet: ProductSheet, simulated: bool) -> str:
    p = sheet.product
    out = []
    if simulated:
        out.append("> **MODO SIMULADO** — roteiro gerado por template, sem refinamento por IA.\n")
    out += [
        f"# Roteiro — {p.name}" + (f" ({p.variant.strip()})" if p.variant.strip() else ""), "",
        f"- Formato: `{script.format_id}` · {script.aspect_ratio} · ~{script.total_target_s:.0f}s · áudio: {script.audio}",
        f"- Planejamento: {script.planner or 'template'}",
        *([f"- Link de afiliado (preservado): {p.affiliate_link}"] if p.affiliate_link.strip() else []),
        f"- Contexto do vídeo (operador): {p.video_context or '—'}",
        *([f"- Ideia do vídeo: {summary_pt(p.creative)}"] if p.creative else []), "",
        "Esteira por cena: referências oficiais → imagem estática aprovada → animação dessa imagem → montagem.", "",
    ]
    for s in script.scenes:
        out += [
            f"## Cena {s.index} — {s.title}", "",
            f"- **Objetivo:** {s.objective}",
            f"- **Enquadramento:** {s.framing}",
            f"- **Modo de apresentação:** {s.presenter_mode}",
            f"- **Referências:** {', '.join(s.references)}",
            f"- **Movimento:** {s.motion}",
            f"- **Duração útil:** {s.target_duration_s:.1f}s",
            f"- **Restrições:** {'; '.join(s.constraints)}",
            "- **Critérios de aprovação:**", *[f"  - {c}" for c in s.approval_criteria], "",
            "**Prompt de imagem**", "", "```text", s.image_prompt, "```", "",
            "**Prompt de animação**", "", "```text", s.animation_prompt, "```", "",
        ]
    if script.overlays:
        out += ["## Textos de tela", ""] + [f"- {o.start_s:.1f}–{o.end_s:.1f}s ({o.position}): {o.text}" for o in script.overlays]
    return "\n".join(out) + "\n"
