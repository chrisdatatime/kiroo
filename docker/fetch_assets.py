"""Baixa e prepara o pacote privado de assets licenciados (stage `assets` do Dockerfile).

Uso (dentro do RUN, com os BuildKit secrets montados):

    python fetch_assets.py --lock assets.lock --out /out [--map assets/maps/office.tmj]

Credenciais de LEITURA do R2 chegam só como arquivos de secret (padrão /run/secrets/<id>):
r2_account_id, r2_access_key_id, r2_secret_access_key. O script nunca as imprime, nunca as
grava e nunca as repassa por ARG/ENV. Ordem: baixar -> conferir SHA256 -> extrair com
segurança -> conferir MANIFEST e arquivos exigidos -> apagar o ZIP (no mesmo RUN).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import zipfile
import zlib
from pathlib import Path, PurePosixPath

SECRET_IDS = ("r2_account_id", "r2_access_key_id", "r2_secret_access_key")

# Limites de extração (o pacote atual tem 25 arquivos e ~2,4 MB descompactados).
MAX_FILES = 200
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_ZIP_BYTES = 128 * 1024 * 1024

# Caminhos tratados explicitamente (relativos à raiz do repositório). Qualquer outra coisa é recusada.
ALLOWED_DIRS = ("assets/characters/", "assets/tilesets/", "frontend/src/assets/home/", "licenses/")
ALLOWED_ROOT_FILES = ("README.txt", "MANIFEST.txt")
UNLISTED_OK = ("README.txt", "MANIFEST.txt")  # não constam no MANIFEST (que não lista a si mesmo)

# Exigidos pelo código:
#  - characters: frontend/src/game/phaser/sprites.js (CHARACTER_SHEETS)
#  - tilesets: imagens do assets/maps/office.tmj (conferidas também por --map)
#  - home: frontend/src/landing/art.js (uma imagem por agente + sede.webp)
#  - licenses: texto da licença que acompanha a imagem final
REQUIRED = tuple(
    [f"assets/characters/{n}.png" for n in ("nina", "theo", "iris", "rui", "lia", "beto", "voce")]
    + [f"assets/tilesets/{n}" for n in ("Room_Builder_32x32.png", "Modern_Office_32x32.png",
                                         "Room_Builder_Office_32x32.png", "interiors_atlas.png")]
    + [f"frontend/src/assets/home/{n}.png" for n in ("nina", "theo", "iris", "rui", "lia", "beto")]
    + ["frontend/src/assets/home/sede.webp"]
    + ["licenses/LIMEZU-Modern-Interiors-LICENSE.txt", "licenses/LIMEZU-Modern-Office-LICENSE.txt"]
    + list(ALLOWED_ROOT_FILES)
)


class AssetError(Exception):
    """Falha de download, hash, extração ou conferência. A mensagem nunca contém segredos."""


# --------------------------------------------------------------------------- lock e segredos

def read_lock(path: Path) -> dict:
    try:
        lock = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AssetError(f"assets.lock ilegível: {exc}") from None
    for key in ("bucket", "object", "sha256"):
        if not isinstance(lock.get(key), str) or not lock[key]:
            raise AssetError(f"assets.lock sem o campo '{key}'")
    if not re.fullmatch(r"[0-9a-f]{64}", lock["sha256"]):
        raise AssetError("assets.lock: sha256 deve ter 64 caracteres hexadecimais minúsculos")
    return lock


def read_credentials(secrets_dir: Path) -> dict[str, str]:
    creds: dict[str, str] = {}
    missing = []
    for sid in SECRET_IDS:
        f = Path(secrets_dir) / sid
        try:
            value = f.read_text(encoding="utf-8").strip()
        except OSError:
            value = ""
        if not value:
            missing.append(sid)
        creds[sid] = value
    if missing:
        raise AssetError("secrets de build ausentes ou vazios: " + ", ".join(missing)
                         + ". Monte-os com --secret id=<nome>,env=<VARIAVEL> (ver docs/DOCKER.md).")
    return creds


# --------------------------------------------------------------------------- download

def make_r2_client(creds: dict[str, str]):  # pragma: no cover - exige boto3 e rede
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=f"https://{creds['r2_account_id']}.r2.cloudflarestorage.com",
        aws_access_key_id=creds["r2_access_key_id"],
        aws_secret_access_key=creds["r2_secret_access_key"],
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
    )


def download(client, bucket: str, key: str, dest: Path) -> None:
    """Baixa para `dest`, recusando objeto acima de MAX_ZIP_BYTES. Erros do SDK perdem o contexto (podem citar a chave)."""
    try:
        head = client.head_object(Bucket=bucket, Key=key)
        size = int(head.get("ContentLength", 0))
        if size > MAX_ZIP_BYTES:
            raise AssetError(f"objeto grande demais ({size} bytes; limite {MAX_ZIP_BYTES})")
        client.download_file(bucket, key, str(dest))
    except AssetError:
        raise
    except Exception as exc:  # noqa: BLE001 - mensagem de SDK pode ecoar parâmetros da requisição
        raise AssetError(f"falha ao baixar s3://{bucket}/{key} ({type(exc).__name__})") from None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if actual != expected.lower():
        raise AssetError(f"SHA256 do pacote não confere (esperado {expected}, obtido {actual})")


# --------------------------------------------------------------------------- extração segura

def _check_name(name: str) -> str:
    if not name or "\x00" in name or "\\" in name:
        raise AssetError(f"nome de entrada inválido: {name!r}")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise AssetError(f"caminho absoluto recusado: {name!r}")
    parts = PurePosixPath(name).parts
    if any(p in ("..", "") for p in parts):
        raise AssetError(f"travessia de diretório recusada: {name!r}")
    return name


def _allowed(name: str) -> bool:
    return name in ALLOWED_ROOT_FILES or any(name.startswith(d) and len(name) > len(d) for d in ALLOWED_DIRS)


def safe_extract(zip_path: Path, dest: Path) -> list[str]:
    """Extrai só caminhos permitidos. Recusa absolutos, `..`, symlinks, duplicatas e excesso de tamanho/quantidade."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise AssetError("o arquivo baixado não é um ZIP válido") from None
    written: list[str] = []
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILES:
            raise AssetError(f"arquivos demais no ZIP ({len(infos)}; limite {MAX_FILES})")
        # 1ª passada: valida tudo antes de gravar qualquer byte
        seen: set[str] = set()
        total = 0
        for info in infos:
            name = _check_name(info.filename.rstrip("/") if info.is_dir() else info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise AssetError(f"symlink recusado: {name!r}")
            if stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise AssetError(f"tipo de entrada não permitido: {name!r}")
            if info.is_dir():
                continue
            if not _allowed(name):
                raise AssetError(f"caminho fora dos permitidos: {name!r}")
            if name in seen:
                raise AssetError(f"entrada duplicada: {name!r}")
            seen.add(name)
            if info.file_size > MAX_FILE_BYTES:
                raise AssetError(f"arquivo grande demais: {name!r} ({info.file_size} bytes)")
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise AssetError(f"tamanho descompactado acima do limite ({MAX_TOTAL_BYTES} bytes)")
        # 2ª passada: grava, contando bytes reais (o tamanho declarado no cabeçalho pode mentir)
        try:
            _write_all(zf, infos, root, written)
        except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
            raise AssetError(f"ZIP corrompido ou com cabeçalho inconsistente ({type(exc).__name__})") from None
    return written


def _write_all(zf: zipfile.ZipFile, infos, root: Path, written: list[str]) -> None:
    real_total = 0
    for info in infos:
        if info.is_dir():
            continue
        target = (root / info.filename).resolve()
        if root not in target.parents:
            raise AssetError(f"destino fora da pasta de extração: {info.filename!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            written_file = 0
            for chunk in iter(lambda: src.read(1 << 16), b""):
                written_file += len(chunk)
                real_total += len(chunk)
                if written_file > MAX_FILE_BYTES or real_total > MAX_TOTAL_BYTES:
                    raise AssetError("tamanho descompactado real acima do limite")
                out.write(chunk)
        written.append(info.filename)


def parse_manifest(text: str) -> dict[str, tuple[str, int]]:
    out: dict[str, tuple[str, int]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 2)
        if len(parts) != 3 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]) or not parts[1].isdigit():
            raise AssetError(f"linha inválida no MANIFEST.txt: {line[:80]!r}")
        out[_check_name(parts[2])] = (parts[0], int(parts[1]))
    return out


def tileset_images_from_map(tmj: Path) -> list[str]:
    data = json.loads(Path(tmj).read_text(encoding="utf-8"))
    return sorted({PurePosixPath(ts["image"]).name for ts in data.get("tilesets", []) if ts.get("image")})


def verify_package(out: Path, map_file: Path | None = None) -> None:
    out = Path(out)
    manifest_path = out / "MANIFEST.txt"
    if not manifest_path.is_file():
        raise AssetError("MANIFEST.txt ausente no pacote")
    manifest = parse_manifest(manifest_path.read_text(encoding="utf-8"))
    present = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    for name, (digest, size) in manifest.items():
        f = out / name
        if not f.is_file():
            raise AssetError(f"arquivo do MANIFEST ausente: {name}")
        if f.stat().st_size != size or sha256_file(f) != digest:
            raise AssetError(f"arquivo não confere com o MANIFEST: {name}")
    extra = sorted(present - set(manifest) - set(UNLISTED_OK))
    if extra:
        raise AssetError("arquivos fora do MANIFEST: " + ", ".join(extra))
    required = list(REQUIRED)
    if map_file is not None:
        required += [f"assets/tilesets/{n}" for n in tileset_images_from_map(map_file)]
    missing = sorted({r for r in required if not (out / r).is_file() or (out / r).stat().st_size == 0})
    if missing:
        raise AssetError("arquivos exigidos pelo código ausentes no pacote: " + ", ".join(missing))


# --------------------------------------------------------------------------- orquestração

def prepare(lock_path: Path, out: Path, *, secrets_dir: Path, work: Path, map_file: Path | None = None,
            client_factory=make_r2_client) -> None:
    lock = read_lock(lock_path)
    creds = read_credentials(secrets_dir)  # falha cedo, antes de qualquer rede
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    zip_path = work / "package.zip"
    staging = work / "extract"
    try:
        download(client_factory(creds), lock["bucket"], lock["object"], zip_path)
        verify_sha256(zip_path, lock["sha256"])  # antes de abrir o ZIP
        if staging.exists():
            shutil.rmtree(staging)
        safe_extract(zip_path, staging)
        verify_package(staging, map_file)
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        for p in sorted(staging.rglob("*")):
            if p.is_file():
                dst = out / p.relative_to(staging)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), dst)
    finally:
        zip_path.unlink(missing_ok=True)  # o ZIP nunca sobrevive ao RUN, nem em caso de erro
        shutil.rmtree(staging, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lock", default="assets.lock")
    ap.add_argument("--out", required=True)
    ap.add_argument("--map", default=None, help="office.tmj: exige também os tilesets que o mapa referencia")
    ap.add_argument("--secrets-dir", default=os.environ.get("ASSETS_SECRETS_DIR", "/run/secrets"))
    ap.add_argument("--work", default="/tmp/kiroo-assets")
    args = ap.parse_args(argv)
    try:
        prepare(Path(args.lock), Path(args.out), secrets_dir=Path(args.secrets_dir), work=Path(args.work),
                map_file=Path(args.map) if args.map else None)
    except AssetError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    n = sum(1 for p in Path(args.out).rglob("*") if p.is_file())
    print(f"assets licenciados prontos: {n} arquivos em {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
