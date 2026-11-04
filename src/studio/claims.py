"""Guarda determinística contra alegações comerciais não comprovadas.

Procura termos de risco (capacidade, material, térmico, certificações, depoimentos…)
em textos que vão para o público (legenda, textos de tela). Cada ocorrência precisa
estar coberta por uma informação VERIFICADA da ficha. É uma rede de segurança
conservadora, não um verificador semântico completo.
"""

from __future__ import annotations

import re
import unicodedata

from .models import ClaimKind, ProductSheet

RISK_PATTERNS = [
    r"\d+[\.,]?\d*\s?(ml|l|litros?|°c|graus|horas?|h|g|kg|cm|mm|w|mah)\b",
    r"capacidade",
    r"termic\w*|quente por|gelad\w* por|conserva\w*",
    r"vedac\w*|hermetic\w*|a prova d|nao vaza|antivazamento",
    r"inquebr\w*|resistent\w*|durave\w*|durabilidade",
    r"aco inox\w*|inox|vidro|silicone|plastico|bpa|ceramica|aluminio|material",
    r"certificad\w*|inmetro|anvisa|homologad\w*|garantia",
    r"testad\w*|comprovad\w*|aprovad\w* por",
    r"eu uso|uso todo dia|amei|recomendo|minha experiencia|melhor (copo|produto|compra)",
]


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def find_unsupported_claims(text: str, sheet: ProductSheet, allow_seller_claims: bool = False) -> list[str]:
    allowed_kinds = {ClaimKind.VERIFIED} | ({ClaimKind.SELLER_CLAIM} if allow_seller_claims else set())
    support = " || ".join(_norm(f"{c.field} {c.text}") for c in sheet.product.claims if c.kind in allowed_kinds)
    normalized = _norm(text)
    problems = []
    for pattern in RISK_PATTERNS:
        for match in re.finditer(pattern, normalized):
            snippet = match.group(0).strip()
            if snippet and snippet not in support:
                problems.append(snippet)
    return sorted(set(problems))
