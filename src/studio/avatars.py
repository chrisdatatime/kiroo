"""Avatar da conta: sempre um kiroo (o mesmo boneco em pixel art do escritório).

O servidor guarda só o id (`users.avatar_kiroo`); a aparência de cada id (cor e acessório) mora no frontend
(`frontend/src/ui/avatar.js`, mesma lista). Regra:
  * conta nova: sorteado UMA vez na criação (`random_kiroo`);
  * conta antiga sem valor: escolhido de forma determinística a partir do id do usuário (`kiroo_for`) e salvo no
    primeiro acesso (`Accounts.avatar_of`). Nunca muda a cada login.
"""

from __future__ import annotations

import hashlib
import secrets

# Ids estáveis: só acrescente no fim (mudar a ordem troca o avatar de contas antigas ainda sem valor salvo).
AVATAR_KIROOS: tuple[str, ...] = tuple(f"k{i:02d}" for i in range(1, 13))


def random_kiroo() -> str:
    return secrets.choice(AVATAR_KIROOS)


def kiroo_for(user_id: str) -> str:
    h = int.from_bytes(hashlib.sha256((user_id or "").encode()).digest()[:8], "big")
    return AVATAR_KIROOS[h % len(AVATAR_KIROOS)]


def valid(kiroo: str | None) -> bool:
    return kiroo in AVATAR_KIROOS
