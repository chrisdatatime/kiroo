"""Biblioteca musical da Lia e do Beto.

A Lia sugere e guarda a escolha da produção; o Beto é o único que aplica a trilha, em `_edit` (uma só vez por montagem).
Três origens, sempre separadas: tendências (curadoria manual, só referência, nunca incorporadas), Biblioteca Pivoo
(sintetizada pelo estúdio ou licenciada em assets/music) e Minhas músicas (uploads privados do workspace, com autorização
confirmada pelo usuário).
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .agents import sound
from .db import Database

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
MAX_AUDIO = 40 * 1024 * 1024
MODES = ("auto", "pick", "mine", "none", "platform")
# Clima, gênero e energia da biblioteca sintetizada do estúdio
BUILTIN_META = {"batida_pop_120": {"genre": "pop eletrônico", "energy": "alta", "vocal": "instrumental", "tags": "demonstração cortes rápidos cozinha casa tecnologia"},
                "lofi_90": {"genre": "lo-fi", "energy": "baixa", "vocal": "instrumental", "tags": "calmo beleza casa decoração detalhe"}}
SCHEMA = """
CREATE TABLE IF NOT EXISTS music_tracks (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, title TEXT NOT NULL, file TEXT NOT NULL, duration_s REAL, bpm REAL, mood TEXT, genre TEXT, energy TEXT, vocal TEXT,
  collection TEXT, favorite INTEGER NOT NULL DEFAULT 0, start_s REAL NOT NULL DEFAULT 0, origin TEXT, usage_terms TEXT, authorized_at TEXT NOT NULL, reference_url TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS music_favorites (workspace_id TEXT NOT NULL, track_id TEXT NOT NULL, PRIMARY KEY (workspace_id, track_id));
"""


class MusicError(ValueError):
    pass


def default_choice() -> dict:
    return {"mode": "auto", "track_id": None, "start_s": 0.0, "volume_db": None, "fade_in_s": 0.3, "fade_out_s": 0.8, "beat_sync": True, "platform_title": None}


def clean_choice(raw: dict) -> dict:
    c = default_choice()
    mode = raw.get("mode")
    if mode not in MODES:
        raise MusicError("modo de trilha inválido")
    c["mode"] = mode
    c["track_id"] = str(raw["track_id"]) if raw.get("track_id") else None
    if mode in ("pick", "mine") and not c["track_id"]:
        raise MusicError("escolha uma trilha")
    def num(key, lo, hi, default):
        v = raw.get(key, default)
        if v is None:
            return None
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError) as exc:
            raise MusicError(f"valor inválido em {key}") from exc
    c["start_s"] = num("start_s", 0.0, 3600.0, 0.0)
    c["volume_db"] = num("volume_db", -30.0, 0.0, None)
    c["fade_in_s"] = num("fade_in_s", 0.0, 5.0, 0.3)
    c["fade_out_s"] = num("fade_out_s", 0.0, 5.0, 0.8)
    c["beat_sync"] = bool(raw.get("beat_sync", True))
    c["platform_title"] = str(raw.get("platform_title") or "")[:160] or None
    return c


class MusicLibrary:
    def __init__(self, db: Database, settings):
        self.db, self.s = db, settings
        db.conn.executescript(SCHEMA)

    def _dir(self, wid: str) -> Path:
        d = Path(self.s.data_dir) / "music" / wid
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------ catálogo
    def trends(self) -> dict:
        """Só o que estiver na curadoria manual (profiles/music/trends.json). Sem integração, nada é inventado."""
        path = Path(self.s.profiles_dir) / "music" / "trends.json"
        if not path.is_file():
            return {"source": "manual", "updated_at": None, "items": []}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"source": "manual", "updated_at": data.get("updated_at"), "curator": data.get("curator"),
                "items": [{"title": str(i.get("title", "")), "artist": str(i.get("artist", "")), "platform": str(i.get("platform", "")), "region": str(i.get("region", "")),
                           "source": str(i.get("source", "")), "checked_at": str(i.get("checked_at", data.get("updated_at") or "")), "embeddable": False} for i in data.get("items", [])]}

    def pivoo(self, wid: str) -> list[dict]:
        favs = {r["track_id"] for r in self.db.conn.execute("SELECT track_id FROM music_favorites WHERE workspace_id=?", (wid,))}
        out = []
        for t in sound.library(self.s.assets_dir):
            meta = BUILTIN_META.get(t["id"], {})
            out.append({"id": t["id"], "title": t["title"], "bpm": t.get("bpm"), "mood": t.get("mood"), "genre": meta.get("genre", t.get("genre") or "não informado"),
                        "energy": meta.get("energy", t.get("energy") or "não informada"), "vocal": meta.get("vocal", "não informado"), "duration_s": 32 if t.get("builtin") else t.get("duration_s"),
                        "license": t.get("license"), "origin": "Sintetizada pelo estúdio" if t.get("builtin") else "Biblioteca licenciada", "tags": meta.get("tags", ""), "favorite": t["id"] in favs, "source": "pivoo"})
        return out

    def mine(self, wid: str) -> list[dict]:
        return [{**dict(r), "favorite": bool(r["favorite"]), "source": "mine"} for r in
                self.db.conn.execute("SELECT * FROM music_tracks WHERE workspace_id=? ORDER BY created_at DESC", (wid,)).fetchall()]

    def track(self, wid: str, track_id: str) -> dict | None:
        for t in self.pivoo(wid):
            if t["id"] == track_id:
                return t
        row = self.db.conn.execute("SELECT * FROM music_tracks WHERE id=? AND workspace_id=?", (track_id, wid)).fetchone()
        return {**dict(row), "source": "mine"} if row else None

    def file_of(self, wid: str, track_id: str, ffmpeg) -> Path | None:
        """Arquivo só do próprio workspace (privado) ou da biblioteca."""
        row = self.db.conn.execute("SELECT file FROM music_tracks WHERE id=? AND workspace_id=?", (track_id, wid)).fetchone()
        if row:
            path = self._dir(wid) / row["file"]
            return path if path.is_file() else None
        lib = {t["id"]: t for t in sound.library(self.s.assets_dir)}
        if track_id in lib:
            return sound.track_file(ffmpeg, Path(self.s.data_dir) / "sound_cache", lib[track_id])
        return None

    # ------------------------------------------------------------ uploads
    def upload(self, wid: str, payload: dict, ffmpeg) -> dict:
        if not payload.get("authorized"):
            raise MusicError("confirme que você tem autorização para usar esta música")
        name, data = str(payload.get("name", "")), str(payload.get("data", ""))
        ext = Path(name).suffix.lower()
        if ext not in AUDIO_EXT:
            raise MusicError("envie MP3, WAV, M4A, AAC, OGG ou FLAC")
        try:
            raw = base64.b64decode(data.split(",", 1)[-1], validate=True)
        except Exception as exc:
            raise MusicError("arquivo inválido") from exc
        if not raw or len(raw) > MAX_AUDIO:
            raise MusicError("o arquivo precisa ter até 40 MB")
        tid = "mus_" + uuid.uuid4().hex[:12]
        path = self._dir(wid) / f"{tid}{ext}"
        path.write_bytes(raw)
        try:
            info = ffmpeg.probe(path)
            if not info.get("has_audio") or not info.get("duration_s"):
                raise ValueError("sem áudio")
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise MusicError("não foi possível ler áudio neste arquivo") from exc
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        bpm = payload.get("bpm")
        self.db.conn.execute(
            "INSERT INTO music_tracks(id, workspace_id, title, file, duration_s, bpm, mood, genre, energy, vocal, collection, origin, usage_terms, authorized_at, reference_url, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, wid, str(payload.get("title") or Path(name).stem)[:120], path.name, info["duration_s"], float(bpm) if bpm else None,
             str(payload.get("mood") or "")[:40], str(payload.get("genre") or "")[:40], str(payload.get("energy") or "")[:20], str(payload.get("vocal") or "")[:20],
             str(payload.get("collection") or "")[:60], str(payload.get("origin") or "Enviada pelo usuário")[:200], str(payload.get("usage_terms") or "Autorização declarada pelo usuário")[:300], now,
             str(payload.get("reference_url") or "")[:400], now))
        return self.track(wid, tid)

    def update(self, wid: str, tid: str, fields: dict) -> dict:
        allowed = {"title": 120, "collection": 60, "mood": 40, "genre": 40, "energy": 20, "vocal": 20}
        row = self.db.conn.execute("SELECT id FROM music_tracks WHERE id=? AND workspace_id=?", (tid, wid)).fetchone()
        if row is None:
            raise MusicError("música não encontrada")
        for k, limit in allowed.items():
            if k in fields:
                self.db.conn.execute(f"UPDATE music_tracks SET {k}=? WHERE id=?", (str(fields[k])[:limit], tid))
        if "start_s" in fields:
            self.db.conn.execute("UPDATE music_tracks SET start_s=? WHERE id=?", (max(0.0, float(fields["start_s"])), tid))
        if "bpm" in fields:
            self.db.conn.execute("UPDATE music_tracks SET bpm=? WHERE id=?", (float(fields["bpm"]) if fields["bpm"] else None, tid))
        return self.track(wid, tid)

    def favorite(self, wid: str, tid: str, on: bool) -> None:
        if self.db.conn.execute("SELECT 1 FROM music_tracks WHERE id=? AND workspace_id=?", (tid, wid)).fetchone():
            self.db.conn.execute("UPDATE music_tracks SET favorite=? WHERE id=?", (int(on), tid))
        elif on:
            self.db.conn.execute("INSERT OR IGNORE INTO music_favorites VALUES (?,?)", (wid, tid))
        else:
            self.db.conn.execute("DELETE FROM music_favorites WHERE workspace_id=? AND track_id=?", (wid, tid))

    def delete(self, wid: str, tid: str) -> None:
        row = self.db.conn.execute("SELECT file FROM music_tracks WHERE id=? AND workspace_id=?", (tid, wid)).fetchone()
        if row is None:
            raise MusicError("música não encontrada")
        (self._dir(wid) / row["file"]).unlink(missing_ok=True)
        self.db.conn.execute("DELETE FROM music_tracks WHERE id=?", (tid,))

    # ------------------------------------------------------------ sugestões
    def suggest(self, wid: str, *, category: str = "", name: str = "", style: str = "dinamico", prefs: dict | None = None, limit: int = 3) -> list[dict]:
        """Regras simples sobre o que se sabe de cada faixa. A explicação cita o motivo real da pontuação."""
        prefs = prefs or {}
        text = f"{category} {name}".lower()
        favorites = _words(prefs.get("favorites", "")); avoid = _words(prefs.get("avoid", ""))
        ranked = []
        for t in self.pivoo(wid) + self.mine(wid):
            hay = _words(" ".join(str(t.get(k) or "") for k in ("title", "mood", "genre", "tags", "collection")))
            if avoid & hay:
                continue
            score, why = 0.0, []
            want_fast = style == "dinamico"
            bpm = t.get("bpm") or 0
            if want_fast and (bpm >= 110 or t.get("energy") == "alta"):
                score += 2; why.append("combina com cortes rápidos")
            if style == "suave" and ((bpm and bpm < 100) or t.get("energy") == "baixa"):
                score += 2; why.append("acompanha fusões lentas")
            if favorites & hay:
                score += 3; why.append("segue seus estilos favoritos")
            if prefs.get("energy") not in (None, "tanto_faz") and t.get("energy") == {"media": "média"}.get(prefs["energy"], prefs["energy"]):
                score += 1.5; why.append("tem a intensidade que você pediu")
            if prefs.get("vocal") not in (None, "tanto_faz") and t.get("vocal") == prefs["vocal"]:
                score += 1
            if t.get("favorite"):
                score += 1.5; why.append("está nos seus favoritos")
            if any(w and w in text for w in str(t.get("tags") or "").split()):
                score += 1; why.append("costuma funcionar nessa categoria de produto")
            if bpm:
                why.append("permite cortes na batida")
            ranked.append({**t, "score": score, "reason": _sentence(why)})
        ranked.sort(key=lambda x: -x["score"])
        return ranked[:limit]

    def explain_choice(self, wid: str, choice: dict) -> dict:
        t = self.track(wid, choice["track_id"]) if choice.get("track_id") else None
        return {"choice": choice, "track": t}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-zà-ÿ0-9-]{3,}", str(text).lower()))


def _sentence(why: list[str]) -> str:
    if not why:
        return "Disponível para uso; sem indicação específica para este vídeo."
    return why[0][0].upper() + why[0][1:] + (" e " + why[1] if len(why) > 1 else "") + "."
