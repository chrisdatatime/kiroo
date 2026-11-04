"""Perfis versionados (apresentadora, direção de arte, formato).

Na criação de uma produção, os perfis escolhidos são congelados (snapshot com hash)
no banco. Alterar o arquivo de perfil depois não muda produções já iniciadas.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

KINDS = ("presenter", "art_direction", "format")


class ProfileError(Exception):
    pass


def _canonical_hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def available_versions(profiles_dir: Path, kind: str, profile_id: str) -> list[str]:
    d = profiles_dir / kind / profile_id
    if not d.is_dir():
        return []
    return sorted((p.stem for p in d.glob("v*.json")), key=lambda v: int(v[1:]) if v[1:].isdigit() else 0)


def load_profile(profiles_dir: Path, kind: str, profile_id: str, version: str | None = None) -> dict:
    if kind not in KINDS:
        raise ProfileError(f"tipo de perfil desconhecido: {kind}")
    if not profile_id.replace("_", "").replace("-", "").isalnum():
        raise ProfileError(f"id de perfil inválido: {profile_id}")
    versions = available_versions(profiles_dir, kind, profile_id)
    if not versions:
        raise ProfileError(f"perfil {kind}/{profile_id} não encontrado em {profiles_dir}")
    version = version or versions[-1]
    if version not in versions:
        raise ProfileError(f"versão {version} não existe para {kind}/{profile_id} (há: {', '.join(versions)})")
    data = json.loads((profiles_dir / kind / profile_id / f"{version}.json").read_text(encoding="utf-8"))
    return data


def snapshot(profiles_dir: Path, selection: dict[str, str]) -> dict:
    """selection: {"presenter": "bia", "art_direction": "cozinha_sp_alto_padrao@v1", "format": "..."}"""
    snap = {}
    for kind in KINDS:
        if kind not in selection:
            raise ProfileError(f"perfil '{kind}' não informado")
        ref = selection[kind]
        pid, _, version = ref.partition("@")
        data = load_profile(profiles_dir, kind, pid, version or None)
        snap[kind] = {"id": pid, "version": data.get("version"), "sha256": _canonical_hash(data), "data": data}
    return snap
