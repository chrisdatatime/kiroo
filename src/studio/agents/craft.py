"""Manual dos especialistas: como a Iris (imagem) e a Lia (vídeo) escrevem prompts.

Regras de ofício acrescentadas a cada cena, conforme o tipo de plano (shot):
- Imagem (Gemini/Nano Banana): descrição narrativa e concreta em vez de lista de palavras-chave; ótica, luz e materiais
  explícitos; cor fiel às fotos oficiais (balanço de branco neutro); composição 9:16 respeitando a interface do app;
  realismo de mãos.
- Vídeo (imagem → vídeo): uma ação principal por plano, câmera dita explicitamente, linha do tempo em segundos dentro da
  parte que será usada do take, física com peso e inércia, gancho no primeiro segundo, final estável para a transição.
Nada aqui descreve atributos do produto: fidelidade continua vindo das fotos oficiais e da ficha.
"""

from __future__ import annotations

import re

from ..models import PresenterMode, ProductSheet

# Tipo de plano por cena: o formato pode declarar "shot"; sem isso, a posição define (abertura, detalhe, fechamento).
SHOTS = ("hero", "detail", "lifestyle", "closing")


def shot_of(bp: dict, index: int, total: int) -> str:
    shot = bp.get("shot")
    if shot in SHOTS:
        return shot
    if index == 1:
        return "hero"
    return "closing" if index == total else "detail"


_IMAGE_SHOT = {
    "hero": ("OPTICS: main camera of a recent flagship smartphone (about 24–26 mm equivalent), held at the height of the "
             "product's center, natural portrait-mode depth: product tack-sharp from front edge to back, background softly "
             "defocused but still readable as a real place."),
    "detail": ("OPTICS: smartphone 2×–3× telephoto lens (about 50–77 mm equivalent) at close focus. Shallow but controlled "
               "depth of field: the highlighted detail (edges, joints, texture, finish) is critically sharp; the rest of the "
               "product falls off gently. Fill most of the frame with the product."),
    "lifestyle": ("OPTICS: smartphone main camera at eye level, slightly wider framing that shows the product in real use "
                  "context; product remains the clear subject and the sharpest element."),
    "closing": ("OPTICS: smartphone main camera, clean and balanced packshot: product centered in the safe area, a little "
                "negative space around it, everything on the product sharp. This frame may become the video cover."),
}

_MOTION_SHOT = {
    "hero": ("CAMERA: locked-off (tripod-stable), no zoom. HOOK: movement starts within the first 0.3 s — no static "
             "intro — so the first second already shows the product in motion."),
    "detail": ("CAMERA: locked-off close-up with stable focus on the detail; at most a barely perceptible drift. "
               "The motion should reveal the detail through light catching the surface (a small rotation)."),
    "lifestyle": ("CAMERA: handheld-stable (very light natural sway, no shake), following the action without reframing "
                  "abruptly."),
    "closing": ("CAMERA: very slow, constant push-in (dolly-in, about 5% over the whole segment), no zoom pumping. "
                "The product ends centered, whole and still."),
}

_MATERIALS = [
    (r"vidro|glass|cristal", "transparent glass: crisp refraction, clean specular edges, background visible through it "
                             "without distortion artifacts"),
    (r"inox|a[çc]o|metal|alum[ií]nio|steel", "metal: controlled reflections with soft gradient highlights, no mirror "
                                              "reflection of a camera or person"),
    (r"pl[aá]stico|acr[ií]lico|plastic|pp\b|abs\b", "plastic: true matte/gloss level as in the photos, subtle "
                                                     "specular highlight, no waxy or 3D-render look"),
    (r"silicone|borracha|rubber", "silicone/rubber: soft satin sheen, slight micro-texture"),
    (r"tecido|algod[aã]o|fabric|pano|malha|poli[eé]ster", "fabric: visible weave and natural folds, no plastic sheen"),
    (r"madeira|bambu|wood", "wood: real grain continuity and warm natural tone"),
    (r"cer[aâ]mica|porcelana|ceramic", "ceramic: smooth glaze with soft highlights, true color"),
    (r"tela|display|led|eletr[oô]nic|bluetooth|usb", "electronics: screens off or showing a plain dark surface, no UI, "
                                                      "no text, LEDs only if visible in the references"),
]


def material_notes(sheet: ProductSheet) -> str:
    p = sheet.product
    text = " ".join([p.name, p.variant, p.category or "", " ".join(f"{k} {v}" for k, v in p.visual_attributes.items())])
    found = [note for pat, note in _MATERIALS if re.search(pat, text, re.I)]
    if not found:
        return ("MATERIAL RENDERING: reproduce the exact surface finish seen in the official photos (matte, satin or "
                "gloss) with physically plausible highlights; no plastic 3D-render look.")
    return "MATERIAL RENDERING: " + "; ".join(found[:3]) + "."


def image_craft(shot: str, sheet: ProductSheet, mode: PresenterMode | str) -> str:
    lines = [
        "PHOTOGRAPHY CRAFT (image specialist):",
        _IMAGE_SHOT.get(shot, _IMAGE_SHOT["hero"]),
        ("LIGHT: large soft key light from a window at about 45° to one side, gentle fill from the opposite side, a "
         "subtle rim light separating the product from the background; no harsh clipped highlights, no crushed "
         "shadows."),
        ("COLOR: neutral white balance (about 5200 K) so the product color matches the official photos exactly; "
         "natural contrast, no heavy filter or color cast."),
        material_notes(sheet),
        ("9:16 SAFE AREA: keep the product" + ("" if str(mode) == PresenterMode.PRODUCT_ONLY.value else " and the hands")
         + " inside the central area; the top 12% and the bottom 22% of the frame will be covered by app interface, "
         "so nothing important goes there."),
        ("REALISM: authentic everyday scene captured by a careful creator — tiny natural imperfections are fine; the "
         "product itself is clean and pristine."),
    ]
    if str(mode) != PresenterMode.PRODUCT_ONLY.value:  # mãos aparecem nos modos "só mãos" e "Bia"
        lines.append("HANDS: anatomically correct, five fingers each, natural knuckle creases and skin texture, relaxed "
                     "grip with believable pressure on the product; hands enter from the frame edge.")
    return "\n".join(lines)


# "Produto em destaque": o movimento é SÓ da câmera e o produto fica parado (o formato diz isso em cada cena).
_MOTION_SHOT_PRODUCT_ONLY = {
    "hero": ("CAMERA: smooth, gimbal-stable move exactly as described above (no zoom pumping). HOOK: the camera starts "
             "moving within the first 0.3 s, so the first second already has motion. The product itself never moves."),
    "detail": ("CAMERA: very slow, stable push toward the detail with constant focus; light gliding over the surface "
               "reveals texture and finish. The product itself never moves."),
    "lifestyle": ("CAMERA: slow, steady move exactly as described above; the product stays still and remains the "
                  "sharpest element."),
    "closing": ("CAMERA: very slow, constant move exactly as described above, no zoom pumping. The product ends centered, "
                "whole and still."),
}


def motion_craft(shot: str, used_s: float, mode: PresenterMode | str | None = None) -> str:
    used = max(used_s, 1.0)
    hold = 0.5 if used >= 3 else 0.3
    act_end = round(used - hold, 1)
    product_only = str(mode) == PresenterMode.PRODUCT_ONLY.value
    shots = _MOTION_SHOT_PRODUCT_ONLY if product_only else _MOTION_SHOT
    physics = ("PHYSICS: only the camera moves; the product stays perfectly still on the surface; consistent contact "
               "shadows; no person, hand or body part ever enters the frame." if product_only else
               "PHYSICS: one main action only; real weight and inertia; hands and product move together without sliding; "
               "consistent contact shadows.")
    return "\n".join([
        "MOTION CRAFT (video specialist):",
        f"TIMING: only the first {used:g} seconds of this take will be used. Start exactly on the provided frame, "
        f"complete the whole action between 0 s and {act_end:g} s with ease-in and ease-out, then hold the final pose "
        f"steady from {act_end:g} s to {used:g} s so the edit can transition on a stable frame. After that, keep "
        "everything still.",
        shots.get(shot, shots["hero"]),
        physics,
        ("STABILITY: product geometry, color, labels and proportions stay rigid and identical in every frame; constant "
         "exposure and white balance; no flicker, morphing, warping, melting edges, "
         + ("people, hands or new objects appearing." if product_only else "extra fingers or objects appearing.")),
    ])


__all__ = ["SHOTS", "shot_of", "image_craft", "motion_craft", "material_notes"]
