"""Tabela de preços usada para ESTIMATIVAS (o custo confirmado vem do provedor/fatura).

Cada preço registra fonte e data de consulta. Atualize antes de qualquer execução real.
"""

from __future__ import annotations

from dataclasses import dataclass

GEMINI_PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"
RETRIEVED = "2026-10-26"


@dataclass(frozen=True)
class Price:
    usd: float
    unit: str
    source: str
    retrieved_on: str
    confidence: str  # official | official_approx | third_party

    def label(self) -> str:
        return f"{self.source} (consultado em {self.retrieved_on}, {self.confidence})"


# Saída por imagem (Standard, pago). Fonte: página oficial de preços.
IMAGE_PRICES: dict[tuple[str, str], Price] = {
    ("gemini-nano-banana-2.1", "1K"): Price(0.0336, "imagem", GEMINI_PRICING_URL, RETRIEVED, "official_approx"),
    ("gemini-nano-banana-2.1", "2K"): Price(0.0504, "imagem", GEMINI_PRICING_URL, RETRIEVED, "official_approx"),
    ("gemini-nano-banana-2.1", "4K"): Price(0.113, "imagem", GEMINI_PRICING_URL, RETRIEVED, "official_approx"),
    ("gemini-3.1-flash-image", "1K"): Price(0.067, "imagem", GEMINI_PRICING_URL, RETRIEVED, "official"),
    ("gemini-3.1-flash-image", "2K"): Price(0.101, "imagem", GEMINI_PRICING_URL, RETRIEVED, "official"),
    ("gemini-3-pro-image", "1K"): Price(0.134, "imagem", GEMINI_PRICING_URL, RETRIEVED, "official"),
    ("gemini-3-pro-image", "2K"): Price(0.134, "imagem", GEMINI_PRICING_URL, RETRIEVED, "official"),
    ("gemini-3-pro-image", "4K"): Price(0.24, "imagem", GEMINI_PRICING_URL, RETRIEVED, "official"),
}
# Custo aproximado de entrada por imagem de referência (tokens). Conservador.
IMAGE_INPUT_PER_REFERENCE_USD = 0.002

# Vídeo por segundo gerado. Só 720p tem valor oficial (aprox.) para Omni Flash.
VIDEO_PRICES: dict[tuple[str, str], Price] = {
    ("gemini-omni-1.1-flash", "720p"): Price(0.10, "segundo", GEMINI_PRICING_URL, RETRIEVED, "official_approx"),
    ("gemini-omni-1.1-flash", "1080p"): Price(0.152, "segundo", "https://opper.ai/google/gemini-omni-1-1-flash", RETRIEVED, "third_party"),
}
# Duração assumida para estimativa quando o provedor não permite fixá-la.
VIDEO_ESTIMATE_SECONDS = 10.0

# Texto multimodal (planejamento/revisão), USD por 1M tokens (entrada, saída).
LLM_PRICES: dict[str, tuple[float, float, Price]] = {
    "gemini-3.8-flash": (0.75, 3.75, Price(0, "1M tokens", GEMINI_PRICING_URL, RETRIEVED, "official")),
    "gemini-3.5-flash-lite": (0.30, 2.50, Price(0, "1M tokens", GEMINI_PRICING_URL, RETRIEVED, "official")),
}


class UnknownPrice(Exception):
    pass


def image_cost(model: str, size: str, n_references: int) -> tuple[float, str]:
    price = IMAGE_PRICES.get((model, size))
    if price is None:
        raise UnknownPrice(f"sem preço cadastrado para imagem {model} @ {size}")
    return round(price.usd + n_references * IMAGE_INPUT_PER_REFERENCE_USD, 4), price.label()


def video_cost(model: str, resolution: str, seconds: float = VIDEO_ESTIMATE_SECONDS) -> tuple[float, str]:
    price = VIDEO_PRICES.get((model, resolution))
    if price is None:
        raise UnknownPrice(f"sem preço cadastrado para vídeo {model} @ {resolution}")
    return round(price.usd * seconds, 4), f"{price.label()}; {seconds:.0f}s assumidos"


def llm_cost(model: str, input_tokens: int, output_tokens: int) -> tuple[float, str]:
    entry = LLM_PRICES.get(model)
    if entry is None:
        raise UnknownPrice(f"sem preço cadastrado para modelo de texto {model}")
    pin, pout, price = entry
    return round(input_tokens / 1e6 * pin + output_tokens / 1e6 * pout, 5), price.label()
