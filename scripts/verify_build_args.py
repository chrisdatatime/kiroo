"""Prova que as credenciais passadas por `--build-arg` ficam no estágio `assets` e não na imagem final.

Por que existe: o Railway não documenta BuildKit secrets, então o Dockerfile aceita as credenciais de
leitura do R2 também por três `ARG` do estágio `assets` (ver Dockerfile e docs/RAILWAY.md). `ARG` é
notoriamente vazável: fica em `docker history` e em `Config.Env` quando declarado no estágio final. Este
roteiro constrói DUAS imagens com o mesmo valor fictício e mostra a diferença, com docker de verdade:

  * controle NEGATIVO (`padrao-kiroo`): ARG só no estágio de assets, igual ao nosso Dockerfile.
    Esperado: valor AUSENTE das camadas, de Config.Env e do `docker history` da imagem final.
  * controle POSITIVO (`vazando`): o estágio final declara o ARG e o promove a ENV — o erro que queremos
    impedir. Esperado: valor PRESENTE (se não aparecer, a varredura está cega e o resultado não vale).

Os valores são aleatórios, gerados aqui, e NUNCA são impressos: a saída é só JSON com booleanos.
Nada da imagem real do Kiroo é usado; isto testa o mecanismo do `ARG`, não o conteúdo do pacote privado.

Uso:
    python scripts/verify_build_args.py            # exige docker; ~20 s (imagem base busybox)
    python scripts/verify_build_args.py --keep     # não apaga as imagens de teste

Saída: JSON. Código 0 = os dois controles deram o esperado; 1 = resultado inesperado (regressão);
3 = não foi possível rodar (sem docker, build falhou) -> trate como NAO_VERIFICADO.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "busybox:1.37.0-musl"          # imagem minúscula e fixada; só precisa de shell para o RUN
TAG_OK = "kiroo-buildarg-negativo:test"
TAG_LEAK = "kiroo-buildarg-positivo:test"

# Mesmo desenho do nosso Dockerfile: ARG apenas no estágio que usa a credencial; o estágio final só copia /out.
DOCKERFILE_OK = """
FROM {base} AS assets
ARG R2_ACCOUNT_ID=""
ARG R2_ACCESS_KEY_ID=""
ARG R2_SECRET_ACCESS_KEY=""
RUN test -n "$R2_SECRET_ACCESS_KEY" \\
 && mkdir -p /out \\
 && printf 'arte sem credencial\\n' > /out/arte.txt

FROM {base} AS runtime
COPY --from=assets /out/ /app/out/
"""

# O erro que queremos impedir: o estágio final conhece o ARG e o promove a ENV.
DOCKERFILE_LEAK = """
FROM {base} AS assets
ARG R2_SECRET_ACCESS_KEY=""
RUN mkdir -p /out && printf 'arte\\n' > /out/arte.txt

FROM {base} AS runtime
ARG R2_SECRET_ACCESS_KEY=""
ENV R2_SECRET_ACCESS_KEY=$R2_SECRET_ACCESS_KEY
COPY --from=assets /out/ /app/out/
RUN printf '%s\\n' "$R2_SECRET_ACCESS_KEY" > /app/out/vazou.txt
"""


class ProveError(Exception):
    """Não foi possível executar a prova (sem docker, build falhou). Nunca contém valores."""


def _load_scanner():
    path = ROOT / "scripts" / "verify_image_layers.py"
    spec = importlib.util.spec_from_file_location("verify_image_layers", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["verify_image_layers"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def build(context: Path, dockerfile: str, tag: str, creds: dict[str, str]) -> None:
    """Build com os valores em --build-arg. Passa o valor pelo AMBIENTE do docker (--build-arg NOME sem '='),
    para que ele não apareça na linha de comando (ps/auditoria do host)."""
    df = context / f"Dockerfile.{tag.split(':')[0]}"
    df.write_text(dockerfile.format(base=BASE), encoding="utf-8")
    cmd = ["docker", "build", "--file", str(df), "--tag", tag, "--progress", "plain"]
    for name in creds:
        cmd += ["--build-arg", name]
    cmd.append(str(context))
    env = {**os.environ, **creds, "DOCKER_BUILDKIT": "1"}
    p = _run(cmd, env=env)
    if p.returncode != 0:
        # A saída do build pode ecoar o valor do ARG: nunca repassamos stdout/stderr daqui.
        raise ProveError(f"build de {tag} falhou (código {p.returncode}); rode o comando à mão para ver o log")


def scan_image(scanner, tag: str, needles: dict[str, bytes]) -> dict:
    """`docker save` -> varredura de TODAS as camadas e de Config.Env, procurando os valores fictícios."""
    tmp = Path(tempfile.mkdtemp(prefix="kiroo-buildarg-"))
    try:
        tar = tmp / "img.tar"
        p = _run(["docker", "save", "-o", str(tar), tag])
        if p.returncode != 0 or not tar.exists() or tar.stat().st_size == 0:
            raise ProveError(f"docker save de {tag} falhou (código {p.returncode})")
        # zip_name inexistente: aqui só interessam os valores das credenciais.
        return scanner.scan(tar, "nenhum-zip-neste-teste.zip", needles)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def history_has(tag: str, needles: dict[str, bytes]) -> bool:
    """`docker history --no-trunc` da imagem final: o ARG do estágio final aparece aqui."""
    p = _run(["docker", "history", "--no-trunc", "--format", "{{.CreatedBy}}\t{{.Comment}}", tag])
    if p.returncode != 0:
        raise ProveError(f"docker history de {tag} falhou (código {p.returncode})")
    blob = p.stdout.encode("utf-8", "replace")
    return any(v and v in blob for v in needles.values())


def inspect_env_has(tag: str, needles: dict[str, bytes]) -> bool:
    """Config.Env da imagem final (o que `docker inspect` mostra a quem baixar a imagem)."""
    p = _run(["docker", "image", "inspect", tag, "--format", "{{json .Config.Env}}"])
    if p.returncode != 0:
        raise ProveError(f"docker inspect de {tag} falhou (código {p.returncode})")
    blob = p.stdout.encode("utf-8", "replace")
    return any(v and v in blob for v in needles.values())


def prove(keep: bool = False) -> dict:
    if not shutil.which("docker"):
        raise ProveError("docker não encontrado no PATH")
    if _run(["docker", "version", "--format", "{{.Server.Version}}"]).returncode != 0:
        raise ProveError("daemon do docker não respondeu")
    scanner = _load_scanner()
    # Valores fictícios, com cara de credencial, gerados agora. Nunca impressos.
    creds = {
        "R2_ACCOUNT_ID": "fake-acct-" + secrets.token_hex(8),
        "R2_ACCESS_KEY_ID": "FAKEAK" + secrets.token_hex(10).upper(),
        "R2_SECRET_ACCESS_KEY": "fake-sk-" + secrets.token_hex(20),
    }
    needles = {k: v.encode() for k, v in creds.items()}
    leak_needle = {"R2_SECRET_ACCESS_KEY": needles["R2_SECRET_ACCESS_KEY"]}
    ctx = Path(tempfile.mkdtemp(prefix="kiroo-buildarg-ctx-"))
    try:
        build(ctx, DOCKERFILE_OK, TAG_OK, creds)
        build(ctx, DOCKERFILE_LEAK, TAG_LEAK, {"R2_SECRET_ACCESS_KEY": creds["R2_SECRET_ACCESS_KEY"]})
        neg = scan_image(scanner, TAG_OK, needles)
        pos = scan_image(scanner, TAG_LEAK, leak_needle)
        res = {
            "base": BASE,
            "valores_procurados": len(needles),
            # controle NEGATIVO: o nosso desenho. Tudo abaixo precisa ser False/limpo.
            "negativo_padrao_kiroo": {
                "credencial_nas_camadas": any(neg["secret_in_content"].values()),
                "config_env_com_r2": neg["env_has_r2"],
                "credencial_no_history": history_has(TAG_OK, needles),
                "credencial_no_inspect_env": inspect_env_has(TAG_OK, needles),
                "camadas": neg["layers"],
                "arquivos_lidos": neg["files_scanned"],
            },
            # controle POSITIVO: o erro. Precisa ser detectado, senão a varredura não prova nada.
            "positivo_vazando": {
                "credencial_nas_camadas": any(pos["secret_in_content"].values()),
                "config_env_com_r2": pos["env_has_r2"],
                "credencial_no_history": history_has(TAG_LEAK, needles),
                "credencial_no_inspect_env": inspect_env_has(TAG_LEAK, needles),
            },
        }
        n, p = res["negativo_padrao_kiroo"], res["positivo_vazando"]
        res["negativo_limpo"] = not (n["credencial_nas_camadas"] or n["config_env_com_r2"]
                                     or n["credencial_no_history"] or n["credencial_no_inspect_env"])
        # Basta UM dos sinais do controle positivo para mostrar que a varredura vê o vazamento.
        res["positivo_detectado"] = bool(p["credencial_nas_camadas"] or p["config_env_com_r2"]
                                         or p["credencial_no_history"] or p["credencial_no_inspect_env"])
        res["ok"] = res["negativo_limpo"] and res["positivo_detectado"]
        return res
    finally:
        shutil.rmtree(ctx, ignore_errors=True)
        if not keep:
            _run(["docker", "image", "rm", "-f", TAG_OK, TAG_LEAK])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keep", action="store_true", help="não apaga as imagens de teste")
    args = ap.parse_args(argv)
    try:
        res = prove(keep=args.keep)
    except ProveError as exc:
        print(json.dumps({"erro_execucao": str(exc)}, ensure_ascii=False))
        return 3
    except Exception as exc:                      # noqa: BLE001 - nunca deixar traceback (pode ecoar comando/valor)
        print(json.dumps({"erro_execucao": type(exc).__name__}, ensure_ascii=False))
        return 3
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
