"""Downloader de assets privados (docker/fetch_assets.py), referência pessoal, check de Git e higiene do Dockerfile.

Tudo com dados e credenciais fictícios: nenhuma rede, nenhum R2 real.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import stat
import subprocess
import sys
import warnings
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fa = _load("fetch_assets", ROOT / "docker" / "fetch_assets.py")
chk = _load("check_licensed_files", ROOT / "scripts" / "check_licensed_files.py")

FAKE_SECRETS = {"r2_account_id": "acct-fake-123", "r2_access_key_id": "AKIAFAKEFAKE", "r2_secret_access_key": "fake/secret+KEY"}


def package_files(skip: tuple[str, ...] = ()) -> dict[str, bytes]:
    files = {name: f"conteudo de {name}".encode() for name in fa.REQUIRED if name not in fa.UNLISTED_OK}
    files["licenses/THIRD-PARTY-TOOLS.txt"] = b"ferramentas"
    for s in skip:
        files.pop(s, None)
    return files


def build_zip(path: Path, files: dict[str, bytes], *, manifest: bool = True, extra=None) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", "leia-me")
        if manifest:
            lines = ["# manifest"] + [f"{hashlib.sha256(b).hexdigest()}  {len(b)}  {n}" for n, b in files.items()]
            z.writestr("MANIFEST.txt", "\n".join(lines) + "\n")
        for n, b in files.items():
            z.writestr(n, b)
        for fn in extra or []:
            fn(z)


class FakeClient:
    def __init__(self, zip_path: Path | None, size: int | None = None, fail: bool = False):
        self.zip_path, self.size, self.fail = zip_path, size, fail
        self.calls: list[tuple] = []

    def head_object(self, Bucket, Key):
        self.calls.append(("head", Bucket, Key))
        if self.fail:
            raise RuntimeError(f"AccessDenied Key={Key} secret=fake/secret+KEY")
        return {"ContentLength": self.size if self.size is not None else self.zip_path.stat().st_size}

    def download_file(self, Bucket, Key, Filename):
        self.calls.append(("get", Bucket, Key))
        Path(Filename).write_bytes(self.zip_path.read_bytes())


@pytest.fixture
def secrets_dir(tmp_path):
    d = tmp_path / "secrets"
    d.mkdir()
    for k, v in FAKE_SECRETS.items():
        (d / k).write_text(v + "\n")
    return d


def make_lock(tmp_path: Path, zip_path: Path, sha: str | None = None) -> Path:
    lock = tmp_path / "assets.lock"
    lock.write_text(json.dumps({"bucket": "kiroo-assets", "object": "pacote.zip",
                                "sha256": sha or hashlib.sha256(zip_path.read_bytes()).hexdigest()}))
    return lock


def run(tmp_path, secrets_dir, zip_path, *, lock=None, client=None, map_file=None, env=None):
    out, work = tmp_path / "out", tmp_path / "work"
    # env={} por padrão: o caminho ARG (R2_* no ambiente) não pode interferir nos testes do caminho secret,
    # mesmo numa máquina que tenha as credenciais reais exportadas.
    fa.prepare(lock or make_lock(tmp_path, zip_path), out, secrets_dir=secrets_dir, work=work, map_file=map_file,
               client_factory=lambda creds: client or FakeClient(zip_path), env={} if env is None else env)
    return out, work


# ------------------------------------------------------------------ caminho feliz e hash

def test_hash_correto_extrai_preserva_caminhos_e_apaga_zip(tmp_path, secrets_dir):
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    client = FakeClient(z)
    out, work = run(tmp_path, secrets_dir, z, client=client)
    assert (out / "assets/characters/nina.png").read_bytes() == b"conteudo de assets/characters/nina.png"
    assert (out / "frontend/src/assets/home/sede.webp").is_file()
    assert (out / "licenses/LIMEZU-Modern-Interiors-LICENSE.txt").is_file()
    assert (out / "README.txt").is_file() and (out / "MANIFEST.txt").is_file()
    assert not (work / "package.zip").exists()  # o ZIP não sobrevive
    assert ("get", "kiroo-assets", "pacote.zip") in client.calls


def test_hash_incorreto_recusa_antes_de_extrair_e_apaga_zip(tmp_path, secrets_dir):
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    lock = make_lock(tmp_path, z, sha="0" * 64)
    with pytest.raises(fa.AssetError, match="SHA256"):
        run(tmp_path, secrets_dir, z, lock=lock)
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").rglob("*.png"))
    assert not (tmp_path / "work" / "package.zip").exists()
    assert not (tmp_path / "work" / "extract").exists()


def test_lock_invalido(tmp_path):
    p = tmp_path / "assets.lock"
    p.write_text(json.dumps({"bucket": "b", "object": "o", "sha256": "xyz"}))
    with pytest.raises(fa.AssetError, match="sha256"):
        fa.read_lock(p)
    p.write_text("{}")
    with pytest.raises(fa.AssetError, match="bucket"):
        fa.read_lock(p)


def test_assets_lock_do_repositorio_tem_os_valores_combinados():
    lock = fa.read_lock(ROOT / "assets.lock")
    assert lock == {"bucket": "kiroo-assets", "object": "kiroo-licensed-assets-2026-11-06.zip",
                    "sha256": "40ad7413abf00e22b4d134f5afaa918f0663dd5e9e6e89a84be214a1dbd602c5"}


# ------------------------------------------------------------------ segredos

@pytest.mark.parametrize("missing", fa.SECRET_IDS)
def test_secret_ausente_falha_cedo_sem_rede(tmp_path, secrets_dir, missing):
    (secrets_dir / missing).unlink()
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    client = FakeClient(z)
    with pytest.raises(fa.AssetError, match=missing):
        run(tmp_path, secrets_dir, z, client=client)
    assert client.calls == []


def test_secret_vazio_conta_como_ausente(tmp_path, secrets_dir):
    (secrets_dir / "r2_account_id").write_text("  \n")
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    with pytest.raises(fa.AssetError, match="r2_account_id"):
        run(tmp_path, secrets_dir, z)


# --- caminho 2: ARG do estágio `assets` (plataforma sem BuildKit secrets, ex. Railway) ---

def _only_args(secrets_dir):
    for sid in fa.SECRET_IDS:
        (secrets_dir / sid).unlink()
    return {fa.ENV_FOR_SECRET[s]: FAKE_SECRETS[s] for s in fa.SECRET_IDS}


def test_arg_supre_secret_ausente(tmp_path, secrets_dir):
    env = _only_args(secrets_dir)
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    client = FakeClient(z)
    out, _ = run(tmp_path, secrets_dir, z, client=client, env=env)
    assert (out / "assets/characters/nina.png").is_file()
    assert client.calls                                                  # baixou: as credenciais do ARG valeram


@pytest.mark.parametrize("missing", fa.SECRET_IDS)
def test_arg_parcial_falha_fechado(tmp_path, secrets_dir, missing):
    env = _only_args(secrets_dir)
    env.pop(fa.ENV_FOR_SECRET[missing])
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    client = FakeClient(z)
    with pytest.raises(fa.AssetError, match=fa.ENV_FOR_SECRET[missing]):
        run(tmp_path, secrets_dir, z, client=client, env=env)
    assert client.calls == []                                            # nem tentou a rede


def test_sem_secret_e_sem_arg_falha_fechado_citando_os_dois_caminhos(tmp_path, secrets_dir):
    _only_args(secrets_dir)
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    client = FakeClient(z)
    with pytest.raises(fa.AssetError) as exc:
        run(tmp_path, secrets_dir, z, client=client, env={})
    msg = str(exc.value)
    assert client.calls == []
    for sid in fa.SECRET_IDS:
        assert sid in msg and fa.ENV_FOR_SECRET[sid] in msg              # diz os dois caminhos possíveis
    assert "--secret" in msg and "--build-arg" in msg
    assert not any(v in msg for v in FAKE_SECRETS.values())              # só nomes, nunca valores


def test_arg_vazio_ou_em_branco_conta_como_ausente(tmp_path, secrets_dir):
    _only_args(secrets_dir)
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    for valor in ("", "   \n"):
        env = {fa.ENV_FOR_SECRET[s]: FAKE_SECRETS[s] for s in fa.SECRET_IDS}
        env["R2_SECRET_ACCESS_KEY"] = valor
        with pytest.raises(fa.AssetError, match="R2_SECRET_ACCESS_KEY"):
            run(tmp_path, secrets_dir, z, env=env)


def test_secret_tem_precedencia_sobre_arg(tmp_path, secrets_dir):
    """Com os dois caminhos presentes vale o secret: a plataforma não sobrescreve o build local por acidente."""
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    visto = {}
    env = {fa.ENV_FOR_SECRET[s]: "valor-do-arg-" + s for s in fa.SECRET_IDS}
    out, work = tmp_path / "out", tmp_path / "work"
    fa.prepare(make_lock(tmp_path, z), out, secrets_dir=secrets_dir, work=work, env=env,
               client_factory=lambda creds: (visto.update(creds), FakeClient(z))[1])
    assert visto == FAKE_SECRETS                                         # os valores vieram dos arquivos de secret


def test_read_credentials_nao_imprime_valores(secrets_dir, capsys):
    fa.read_credentials(secrets_dir, {})
    saida = capsys.readouterr().out
    assert "3 via secret, 0 via ARG" in saida
    assert not any(v in saida for v in FAKE_SECRETS.values())


def test_erro_do_sdk_nao_vaza_credencial_nem_chave(tmp_path, secrets_dir):
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    with pytest.raises(fa.AssetError) as exc:
        run(tmp_path, secrets_dir, z, client=FakeClient(z, fail=True))
    msg = str(exc.value)
    assert "RuntimeError" in msg and "fake/secret+KEY" not in msg and "AccessDenied" not in msg


def test_main_sem_secrets_sai_com_erro_claro(tmp_path, capsys):
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    rc = fa.main(["--lock", str(make_lock(tmp_path, z)), "--out", str(tmp_path / "o"),
                  "--secrets-dir", str(tmp_path / "nao-existe"), "--work", str(tmp_path / "w")])
    err = capsys.readouterr().err
    assert rc == 1 and "r2_account_id" in err and "docs/DOCKER.md" in err


# ------------------------------------------------------------------ ZIP inseguro

def _unsafe(tmp_path, secrets_dir, extra, match=""):
    z = tmp_path / "p.zip"
    build_zip(z, package_files(), extra=extra)
    with pytest.raises(fa.AssetError, match=match):
        run(tmp_path, secrets_dir, z)
    assert not (tmp_path / "work" / "package.zip").exists()


def test_zip_com_caminho_absoluto(tmp_path, secrets_dir):
    _unsafe(tmp_path, secrets_dir, [lambda z: z.writestr("/etc/evil", "x")], match="absoluto")


def test_zip_com_unidade_windows(tmp_path, secrets_dir):
    _unsafe(tmp_path, secrets_dir, [lambda z: z.writestr("C:/evil.txt", "x")], match="absoluto")


def test_zip_com_travessia(tmp_path, secrets_dir):
    _unsafe(tmp_path, secrets_dir, [lambda z: z.writestr("assets/characters/../../../evil.png", "x")], match="travessia")


def test_nome_com_barra_invertida_ou_nulo():
    # (testado direto: o zipfile do Windows normaliza "\\" ao ler/escrever, o do Linux não)
    for bad in ("assets" + chr(92) + "x.png", "assets/x" + chr(0) + ".png", ""):
        with pytest.raises(fa.AssetError, match="inválido"):
            fa._check_name(bad)


def test_zip_com_symlink(tmp_path, secrets_dir):
    def add(z):
        info = zipfile.ZipInfo("assets/characters/link.png")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, "/etc/passwd")
    _unsafe(tmp_path, secrets_dir, [add], match="symlink")
    assert not (tmp_path / "out" / "assets").exists()  # validação antes de gravar qualquer byte


def test_zip_com_caminho_fora_dos_permitidos(tmp_path, secrets_dir):
    _unsafe(tmp_path, secrets_dir, [lambda z: z.writestr("assets/bia/PERFIL BIA.jpg", "foto")], match="fora dos permitidos")


def test_zip_com_entrada_duplicada(tmp_path, secrets_dir):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _unsafe(tmp_path, secrets_dir, [lambda z: z.writestr("assets/characters/nina.png", "outra")], match="duplicada")


def test_zip_com_arquivos_demais(tmp_path, secrets_dir, monkeypatch):
    monkeypatch.setattr(fa, "MAX_FILES", 5)
    _unsafe(tmp_path, secrets_dir, [], match="demais")


def test_zip_acima_do_limite_descompactado(tmp_path, secrets_dir, monkeypatch):
    monkeypatch.setattr(fa, "MAX_TOTAL_BYTES", 100)
    _unsafe(tmp_path, secrets_dir, [], match="limite")


def test_zip_com_cabecalho_mentiroso_ou_corrompido(tmp_path, secrets_dir, monkeypatch):
    # tamanho declarado menor que o real: a leitura falha (CRC) e vira AssetError, sem vazar traceback
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    real_infolist = zipfile.ZipFile.infolist

    def liar(self):
        infos = real_infolist(self)
        for i in infos:
            i.file_size = 1
        return infos

    monkeypatch.setattr(zipfile.ZipFile, "infolist", liar)
    with pytest.raises(fa.AssetError, match="corrompido"):
        run(tmp_path, secrets_dir, z)


def test_limite_de_bytes_reais_na_extracao(tmp_path, monkeypatch):
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    monkeypatch.setattr(fa, "MAX_FILE_BYTES", 10)
    with zipfile.ZipFile(z) as zf:
        infos = [i for i in zf.infolist() if i.filename == "assets/characters/nina.png"]
        with pytest.raises(fa.AssetError, match="real acima do limite"):
            fa._write_all(zf, infos, (tmp_path / "x").resolve(), [])


def test_objeto_grande_demais_nao_e_baixado(tmp_path, secrets_dir):
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    client = FakeClient(z, size=fa.MAX_ZIP_BYTES + 1)
    with pytest.raises(fa.AssetError, match="grande demais"):
        run(tmp_path, secrets_dir, z, client=client)
    assert ("get", "kiroo-assets", "pacote.zip") not in client.calls


def test_nao_zip(tmp_path, secrets_dir):
    z = tmp_path / "p.zip"
    z.write_bytes(b"isto nao e um zip")
    with pytest.raises(fa.AssetError, match="ZIP válido"):
        run(tmp_path, secrets_dir, z)


# ------------------------------------------------------------------ obrigatórios e manifest

@pytest.mark.parametrize("missing", ["assets/characters/voce.png", "assets/tilesets/interiors_atlas.png",
                                      "frontend/src/assets/home/sede.webp", "licenses/LIMEZU-Modern-Interiors-LICENSE.txt"])
def test_arquivo_obrigatorio_ausente(tmp_path, secrets_dir, missing):
    z = tmp_path / "p.zip"
    build_zip(z, package_files(skip=(missing,)))
    with pytest.raises(fa.AssetError, match="ausentes") as exc:
        run(tmp_path, secrets_dir, z)
    assert missing in str(exc.value)


def test_arquivo_obrigatorio_vazio(tmp_path, secrets_dir):
    files = package_files()
    files["assets/characters/nina.png"] = b""
    z = tmp_path / "p.zip"
    build_zip(z, files)
    with pytest.raises(fa.AssetError, match="ausentes"):
        run(tmp_path, secrets_dir, z)


def test_manifest_ausente(tmp_path, secrets_dir):
    z = tmp_path / "p.zip"
    build_zip(z, package_files(), manifest=False)
    with pytest.raises(fa.AssetError, match="MANIFEST"):
        run(tmp_path, secrets_dir, z)


def test_arquivo_adulterado_nao_confere_com_manifest(tmp_path, secrets_dir):
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(z) as src, zipfile.ZipFile(bad, "w") as dst:
        for i in src.infolist():
            dst.writestr(i.filename, b"ADULTERADO" if i.filename == "assets/characters/rui.png" else src.read(i.filename))
    with pytest.raises(fa.AssetError, match="MANIFEST"):
        run(tmp_path, secrets_dir, bad)


def test_arquivo_fora_do_manifest(tmp_path, secrets_dir):
    z = tmp_path / "p.zip"
    build_zip(z, package_files(), extra=[lambda zz: zz.writestr("assets/characters/extra.png", "x")])
    with pytest.raises(fa.AssetError, match="fora do MANIFEST"):
        run(tmp_path, secrets_dir, z)


def test_mapa_exige_os_tilesets_que_referencia(tmp_path, secrets_dir):
    tmj = tmp_path / "m.tmj"
    tmj.write_text(json.dumps({"tilesets": [{"image": "../tilesets/Novo_Tileset.png"}]}))
    z = tmp_path / "p.zip"
    build_zip(z, package_files())
    with pytest.raises(fa.AssetError, match="Novo_Tileset.png"):
        run(tmp_path, secrets_dir, z, map_file=tmj)


def test_lista_de_obrigatorios_cobre_mapa_e_sprites_do_repositorio():
    tilesets = set(fa.tileset_images_from_map(ROOT / "assets/maps/office.tmj"))
    assert {Path(r).name for r in fa.REQUIRED if r.startswith("assets/tilesets/")} == tilesets
    sprites = (ROOT / "frontend/src/game/phaser/sprites.js").read_text(encoding="utf-8")
    body = re.search(r"CHARACTER_SHEETS = \{(.*?)\}", sprites, re.S).group(1)
    sheets = set(re.findall(r":\s*'(\w+)'", body))
    assert {f"assets/characters/{v}.png" for v in sheets} == {r for r in fa.REQUIRED if r.startswith("assets/characters/")}


# ------------------------------------------------------------------ referência pessoal

def test_reference_root_segue_assets_dir_por_padrao(settings):
    assert settings.reference_dir is None and settings.reference_root == settings.assets_dir


def test_reference_dir_separado_dos_assets(tmp_path, monkeypatch):
    from studio.config import load_settings
    monkeypatch.setenv("STUDIO_REFERENCE_DIR", str(tmp_path / "ref"))
    s = load_settings(env_file=tmp_path / "none.env", assets_dir=tmp_path / "assets", data_dir=tmp_path / "d")
    assert s.reference_root == (tmp_path / "ref").resolve() and s.assets_dir == tmp_path / "assets"


def test_doctor_informa_referencia_ausente(tmp_path, monkeypatch, capsys):
    from studio.cli import main
    monkeypatch.setenv("STUDIO_REFERENCE_DIR", str(tmp_path / "ref"))
    monkeypatch.setenv("STUDIO_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("STUDIO_ASSETS_DIR", str(tmp_path / "a"))
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "referência Bia: AUSENTE" in out and "docs/DOCKER.md" in out and str((tmp_path / "ref").resolve()) in out
    (tmp_path / "ref" / "bia").mkdir(parents=True)
    (tmp_path / "ref" / "bia" / "PERFIL BIA.jpg").write_bytes(b"x")
    main(["doctor"])
    assert "referência Bia: ok" in capsys.readouterr().out


# ------------------------------------------------------------------ Git e Dockerfile

def test_check_git_detecta_arquivos_licenciados_rastreados(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for rel in ("assets/characters/x.png", "assets/maps/ok.tmj", "pacote.zip", "frontend/src/assets/home/a.png", "assets/bia/f.jpg"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    bad = {f for f, _ in chk.violations(chk.tracked_files(tmp_path))}
    assert bad == {"assets/characters/x.png", "pacote.zip", "frontend/src/assets/home/a.png", "assets/bia/f.jpg"}
    assert chk.main(["--repo", str(tmp_path)]) == 1


def test_repositorio_nao_rastreia_arquivos_licenciados():
    if not (ROOT / ".git").exists():
        pytest.skip("sem repositório Git")
    assert chk.violations(chk.tracked_files(ROOT)) == []


def dockerfile_stages(code: str) -> dict[str, str]:
    """Nome do estágio -> corpo (as linhas até o próximo FROM). Estágio sem AS recebe um nome sintético."""
    stages: dict[str, str] = {}
    name, buf = None, []
    for line in code.splitlines():
        m = re.match(r"^\s*FROM\s+\S+(?:\s+AS\s+(\S+))?\s*$", line, re.I)
        if m:
            if name is not None:
                stages[name] = "\n".join(buf)
            name, buf = m.group(1) or f"_sem_nome_{len(stages)}", []
            continue
        buf.append(line)
    if name is not None:
        stages[name] = "\n".join(buf)
    return stages


def test_dockerfile_nao_carrega_credenciais():
    """ENV com credencial: proibido em qualquer estágio. ARG de credencial: só no estágio `assets`.

    ENV persiste na imagem (aparece em `docker inspect`); ARG num estágio intermediário não é herdado pelo
    estágio final. A prova com docker de verdade está em scripts/verify_build_args.py.
    """
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    cred = r"R2_|SECRET|ACCESS_KEY"
    assert not re.search(rf"^\s*ENV\b[^\n]*({cred})", code, re.I | re.M)
    stages = dockerfile_stages(code)
    assert {"assets", "frontend", "litestream", "runtime"} <= set(stages), sorted(stages)
    for nome, corpo in stages.items():
        args = [a for a in re.findall(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)", corpo, re.M) if re.search(cred, a, re.I)]
        esperado = sorted(fa.ENV_FOR_SECRET.values()) if nome == "assets" else []
        assert sorted(args) == esperado, (nome, args)
        # qualquer estágio que use o `assets` só pode copiar de /out (nunca /tmp, /w ou o ZIP)
        for origem in re.findall(r"^\s*COPY\s+--from=assets\s+(\S+)", corpo, re.M):
            assert origem.startswith("/out/"), (nome, origem)
    # o estágio final não declara ARG de credencial, logo não entra no history nem no Config.Env da imagem
    assert "runtime" in stages and not re.search(rf"^\s*ARG\s+\S*({cred})", stages["runtime"], re.I | re.M)
    assert code.count("type=secret") == 3
    block = re.search(r"RUN --mount=type=secret.*?fetch_assets\.py[^\n]*", code, re.S).group(0)
    assert all(f"id={s}" in block for s in fa.SECRET_IDS)  # os 3 secrets só neste RUN
    assert "USER kiroo" in code and "STUDIO_DATA_DIR=/data" in code and "STUDIO_REFERENCE_DIR=/reference" in code
    assert "assets/bia" not in code


def test_dockerignore_exclui_o_que_deve():
    lines = {l.strip() for l in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
    for want in (".env", ".env.*", "data/", "**/node_modules/", "*-office/", ".git/", "assets/bia/", "*.zip", "*.sqlite3",
                 "assets/characters/", "assets/tilesets/", "frontend/src/assets/home/", "!.env.example"):
        assert want in lines, want


def test_lockfiles_com_versoes_exatas():
    for name in ("requirements.lock", "requirements-assets.lock"):
        reqs = [l for l in (ROOT / "docker" / name).read_text(encoding="utf-8").splitlines() if l and not l.startswith(("#", " "))]
        assert reqs and all(re.match(r"^[A-Za-z0-9_.\-]+==\S+ \\$", l) for l in reqs), name
    main = (ROOT / "docker/requirements.lock").read_text(encoding="utf-8")
    for pkg in ("google-genai==", "anthropic==", "pydantic==", "python-dotenv=="):
        assert pkg in main
