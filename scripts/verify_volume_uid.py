"""Prova que o entrypoint conserta um volume pertencente ao root e DESCE para o usuário do app.

Por que existe: o Railway monta o volume como root, mas a imagem roda como `kiroo` (uid 10001). O
entrypoint, quando começa como root (RAILWAY_RUN_UID=0), ajusta o dono de /data e troca de usuário com
`setpriv` antes de iniciar o Litestream e o servidor. Este roteiro verifica isso com docker de verdade,
num volume novo que forçamos a pertencer ao root — nunca no volume de produção.

Cenários (cada um num volume novo e descartável, apagado no fim):
  1. root + /data do root, vazio        -> o app roda como 10001, /data vira do 10001, escrita ok (o caso Railway).
  2. root + arquivo antigo do root       -> o dono é corrigido em profundidade e o app reescreve.
  3. root + KIROO_SKIP_PRIV_DROP=1       -> plano B: segue como root, com aviso no stderr.
  4. usuário do app + /data já correto   -> nada muda, continua 10001 (não regride Docker/compose).
  5. usuário do app + /data do root      -> escrita FALHA: é o problema que o cenário 1 resolve (controle positivo).

Nota de ambiente: no Docker Desktop (Windows/macOS) o dono de um volume nomeado NÃO sobrevive à troca de
contêiner — ele é reaplicado a partir da imagem. Por isso cada cenário força o dono de /data DENTRO do
mesmo contêiner, imediatamente antes de chamar o entrypoint, e o cenário "sem root" desce para o uid do app
com `setpriv` antes do entrypoint (o mesmo efeito do `USER kiroo` da imagem). O que se mede é o que o
entrypoint faz a partir do estado em que /data chega a ele, que é exatamente o que varia no Railway.

Uso:
    python scripts/verify_volume_uid.py [--image kiroo:local]

Saída: JSON com booleanos. Código 0 = todos os cenários como esperado; 1 = algum divergiu;
3 = não foi possível rodar (sem docker, imagem ausente) -> trate como NAO_VERIFICADO.
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "docker" / "entrypoint.sh"
# O comando "servidor": só relata quem é e tenta escrever no volume. Sem backup configurado não há Litestream,
# então nada de rede nem de credencial entra neste teste.
PROBE = (
    'echo "UID=$(id -u)";'
    'echo "GID=$(id -g)";'
    'echo "DATA=$(stat -c %u:%g /data)";'
    'if touch /data/escrita-$$ 2>/dev/null; then echo "ESCRITA=ok"; rm -f /data/escrita-$$; else echo "ESCRITA=falhou"; fi'
)
APP_UID = "10001"


class ProveError(Exception):
    """Não foi possível executar a prova. Nunca contém valores de credencial."""


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    p = _run(["docker", *args])
    if check and p.returncode != 0:
        raise ProveError(f"docker {args[0]} falhou (código {p.returncode}): {p.stderr.strip()[:200]}")
    return p


def scenario(image: str, vol: str, *, data_owner: str, as_root: bool, old_root_file: bool, skip_drop: bool) -> dict:
    """Volume novo; força o dono de /data; chama o entrypoint real (montado de fora) com o comando-sonda."""
    _docker("volume", "create", vol)
    # Prelúdio como root, no MESMO contêiner: deixa /data no estado em que a plataforma o entregaria.
    prelude = f"chown {data_owner} /data; chmod 0755 /data;"
    if old_root_file:
        prelude += " echo antigo > /data/antigo.txt; chown 0:0 /data/antigo.txt;"
    # `sh <arquivo>` em vez de executá-lo: não depende do bit de execução do bind mount.
    chamada = f"sh /usr/local/bin/kiroo-entrypoint-test sh -c '{PROBE}'"
    if not as_root:
        # equivale ao `USER kiroo` da imagem: o entrypoint já começa sem privilégio
        chamada = f"setpriv --reuid={APP_UID} --regid={APP_UID} --clear-groups -- {chamada}"
    cmd = ["run", "--rm", "--user", "0", "-v", f"{vol}:/data",
           "-v", f"{ENTRY.as_posix()}:/usr/local/bin/kiroo-entrypoint-test:ro",
           "-e", "STUDIO_ENV=dev", "-e", "STUDIO_DATA_DIR=/data"]
    if skip_drop:
        cmd += ["-e", "KIROO_SKIP_PRIV_DROP=1"]
    cmd += ["--entrypoint", "sh", image, "-c", f"{prelude} exec {chamada}"]
    p = _docker(*cmd, check=False)
    _docker("volume", "rm", "-f", vol, check=False)
    out = p.stdout + p.stderr
    campos = dict(l.split("=", 1) for l in p.stdout.splitlines() if "=" in l and l.split("=", 1)[0].isupper())
    return {"rc": p.returncode, "uid": campos.get("UID"), "data_dono": campos.get("DATA"),
            "escrita": campos.get("ESCRITA"), "aviso_root": "vai rodar como ROOT" in out,
            "ajustou_dono": "ajustando o dono" in out, "saida": out.strip()[-400:]}


def prove(image: str) -> dict:
    if not shutil.which("docker"):
        raise ProveError("docker não encontrado no PATH")
    if _docker("image", "inspect", image, check=False).returncode != 0:
        raise ProveError(f"imagem {image} não existe localmente (construa antes; ver docs/DOCKER.md)")
    if not ENTRY.is_file():
        raise ProveError(f"{ENTRY} não encontrado")
    s, sufixo = {}, secrets.token_hex(4)
    def rodar(nome, n, **kw):
        s[nome] = scenario(image, f"kiroo-uidtest-{n}-{sufixo}", **kw)

    rodar("1_root_data_do_root", 1, data_owner="0:0", as_root=True, old_root_file=False, skip_drop=False)
    rodar("2_root_arquivo_antigo_do_root", 2, data_owner="0:0", as_root=True, old_root_file=True, skip_drop=False)
    rodar("3_root_plano_b", 3, data_owner="0:0", as_root=True, old_root_file=False, skip_drop=True)
    rodar("4_app_data_correto", 4, data_owner=f"{APP_UID}:{APP_UID}", as_root=False, old_root_file=False, skip_drop=False)
    rodar("5_app_data_do_root", 5, data_owner="0:0", as_root=False, old_root_file=False, skip_drop=False)

    esperado = {
        # o caso Railway: desceu para o app, o volume virou do app e a escrita passou
        "1_desce_para_o_app": s["1_root_data_do_root"]["uid"] == APP_UID
                              and s["1_root_data_do_root"]["data_dono"] == f"{APP_UID}:{APP_UID}"
                              and s["1_root_data_do_root"]["escrita"] == "ok",
        "1_sem_aviso_de_root": not s["1_root_data_do_root"]["aviso_root"],
        # conteúdo antigo do root: corrigido em profundidade (chown -R) e regravável
        "2_corrige_conteudo_antigo": s["2_root_arquivo_antigo_do_root"]["ajustou_dono"]
                                     and s["2_root_arquivo_antigo_do_root"]["uid"] == APP_UID
                                     and s["2_root_arquivo_antigo_do_root"]["escrita"] == "ok",
        # plano B: fica root e avisa alto
        "3_plano_b_fica_root_com_aviso": s["3_root_plano_b"]["uid"] == "0" and s["3_root_plano_b"]["aviso_root"],
        # caminho Docker/compose de sempre: já entra como app e não mexe em nada
        "4_sem_root_continua_app": s["4_app_data_correto"]["uid"] == APP_UID
                                   and s["4_app_data_correto"]["escrita"] == "ok"
                                   and not s["4_app_data_correto"]["ajustou_dono"],
        # controle POSITIVO: sem o conserto, o app não escreve. Se isto der "ok", o teste não prova nada.
        "5_sem_conserto_a_escrita_falha": s["5_app_data_do_root"]["uid"] == APP_UID
                                          and s["5_app_data_do_root"]["escrita"] == "falhou",
    }
    return {"imagem": image, "cenarios": s, "conferencias": esperado, "ok": all(esperado.values())}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--image", default="kiroo:local")
    args = ap.parse_args(argv)
    try:
        res = prove(args.image)
    except ProveError as exc:
        print(json.dumps({"erro_execucao": str(exc)}, ensure_ascii=False))
        return 3
    except Exception as exc:                      # noqa: BLE001 - nunca deixar traceback
        print(json.dumps({"erro_execucao": type(exc).__name__}, ensure_ascii=False))
        return 3
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
