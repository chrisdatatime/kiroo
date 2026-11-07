# Kiroo — Docker (Fase 3)

Imagem multi-stage que traz a arte licenciada (LimeZu) de um **pacote privado no Cloudflare R2**, sem nunca gravar credenciais nem o ZIP em camadas.

> **Status da validação:** o downloader, o Dockerfile (lido por testes estáticos), o `.dockerignore` e o check de Git têm testes automáticos com dados fictícios. O build real foi feito e conferido manualmente por Christian (ver "Evidências do build real"). O roteiro de verificação foi executado por Christian no Docker local (ver "Resultados da execução local"); todas as verificações passaram, incluindo `2a-fs` após a correção. A sessão de desenvolvimento não tem Docker. Para isso há `scripts/verify_phase3.sh` e `scripts/verify_image_layers.py` (seção abaixo).

## Visão geral

| Stage | Base | Faz |
|---|---|---|
| `assets` | `python:3.12-slim` + boto3 (lockfile com hashes) | Baixa `kiroo-licensed-assets-2026-11-06.zip` do R2 via API S3, confere o SHA256 do `assets.lock`, extrai com segurança, confere o `MANIFEST.txt` e os arquivos exigidos pelo código, apaga o ZIP. Tudo num único `RUN` com os secrets montados. |
| `frontend` | `node:22-bookworm-slim` | `npm ci`, recebe os assets preparados e roda `npm run build` (o Vite embute personagens e tilesets no bundle). |
| `runtime` | `python:3.12-slim` | `ffmpeg`, `fonts-dejavu-core`, `tini`, usuário não-root `kiroo` (uid 10001), dependências do `docker/requirements.lock` (extras `real` e `chat`), `frontend/dist`, mapas, `profiles/` e as licenças. |

O servidor Python só serve o `frontend/dist`. As folhas de personagens e os tilesets **não ficam soltos** na imagem de runtime; vão dentro do bundle. A pasta `/app/licenses` acompanha a imagem.

### Variáveis fixadas na imagem

| Variável | Valor | Por quê |
|---|---|---|
| `STUDIO_DATA_DIR` | `/data` | Volume persistente (banco SQLite, produções, uploads, `studio.lock`). Pertence ao usuário `kiroo`. |
| `STUDIO_ASSETS_DIR` | `/app/assets` | Assets imutáveis da imagem (mapas; biblioteca de música, se houver). |
| `STUDIO_PROFILES_DIR` | `/app/profiles` | Perfis versionados. |
| `STUDIO_REFERENCE_DIR` | `/reference` | **Referência pessoal** (foto da apresentadora), por volume, separada dos assets (ver abaixo). |
| `STUDIO_FONT_FILE` | `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` | Texto sobreposto no vídeo. |
| `STUDIO_HOST` | `0.0.0.0` | Escuta em todas as interfaces do contêiner. |

A porta vem de `PORT` (ou `STUDIO_PORT`); sem nenhuma, `8765`. `STUDIO_PORT` não é fixada na imagem justamente para não anular o `PORT` da plataforma. O código roda de `/app/src` (`PYTHONPATH`), porque `PROJECT_ROOT` e o caminho do `frontend/dist` são derivados do local do código.

## Pré-requisitos

- Docker com BuildKit (Docker Desktop, ou Docker Engine 23+ com buildx). Para o Compose: Docker Compose v2.24+.
- Uma chave R2 **somente de leitura** no bucket `kiroo-assets` (token S3 com permissão "Object Read only"). Nunca use o token de escrita.
- Os três valores: ID da conta, Access Key ID e Secret Access Key.

## Fornecer as credenciais pelo terminal (sem chat, sem arquivo)

As credenciais viram variáveis de ambiente **só da sessão do terminal** e o Docker as injeta como *secrets* de build. Não ficam em `ARG`, `ENV`, imagem, `.env` nem histórico.

**PowerShell**

```powershell
$env:R2_ACCOUNT_ID        = Read-Host "R2 account id"
$env:R2_ACCESS_KEY_ID     = Read-Host "R2 access key id"
$env:R2_SECRET_ACCESS_KEY = [System.Net.NetworkCredential]::new("", (Read-Host "R2 secret access key" -AsSecureString)).Password
```

**Linux / macOS (bash/zsh)**

```bash
read -r -p "R2 account id: " R2_ACCOUNT_ID
read -r -p "R2 access key id: " R2_ACCESS_KEY_ID
read -r -s -p "R2 secret access key: " R2_SECRET_ACCESS_KEY; echo
export R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY
```

Ao terminar, limpe a sessão:

```powershell
Remove-Item Env:R2_ACCOUNT_ID, Env:R2_ACCESS_KEY_ID, Env:R2_SECRET_ACCESS_KEY
```

```bash
unset R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY
```

## Build

Com o Compose (usa os secrets do ambiente):

```bash
docker compose build
```

Ou direto, com `docker build` (um comando, funciona igual no PowerShell e no bash):

```bash
docker build --secret id=r2_account_id,env=R2_ACCOUNT_ID --secret id=r2_access_key_id,env=R2_ACCESS_KEY_ID --secret id=r2_secret_access_key,env=R2_SECRET_ACCESS_KEY --build-arg "GIT_COMMIT=$(git rev-parse HEAD)" -t kiroo:local .
```

`GIT_COMMIT` grava o commit no rótulo `org.opencontainers.image.revision` (não é segredo). Confira com
`docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' kiroo:local`.
No `docker compose build`, exporte antes `GIT_COMMIT` (bash: `export GIT_COMMIT=$(git rev-parse HEAD)`;
PowerShell: `$env:GIT_COMMIT = git rev-parse HEAD`); sem ela o rótulo fica `desconhecido`.

Se faltar algum secret, o build falha cedo e diz qual (`secrets de build ausentes ou vazios: ...`), sem tentar a rede. Se o SHA256 do pacote não bater com `assets.lock`, falha antes de abrir o ZIP.

## Rodar localmente

```bash
cp .env.docker.example .env.docker      # PowerShell: Copy-Item .env.docker.example .env.docker
docker compose up -d
docker compose logs -f kiroo
```

Abra <http://localhost:8765>. O cadastro vem **fechado**: crie o administrador pela CLI dentro do contêiner (pede a senha no terminal):

```bash
docker compose exec kiroo python -m studio admin create-user --email voce@exemplo.com --name "Seu Nome" --admin
```

Diagnóstico (mostra ffmpeg, fonte, pastas e a referência pessoal):

```bash
docker compose exec kiroo python -m studio doctor
```

### Referência pessoal por volume

A foto da apresentadora (`bia/PERFIL BIA.jpg`) **não entra na imagem**. O Compose monta `./reference` em `/reference` (somente leitura):

```text
reference/
  bia/
    PERFIL BIA.jpg
```

Em `docker run`, o equivalente é `-v "$PWD/reference:/reference:ro"`. O volume de dados (`/data`) e os assets da imagem (`/app/assets`) ficam intactos: a referência tem a própria variável (`STUDIO_REFERENCE_DIR`). Sem `STUDIO_REFERENCE_DIR`, o aplicativo usa `STUDIO_ASSETS_DIR` (comportamento local de sempre). Quando a foto falta, o `doctor` mostra `referência Bia: AUSENTE em /reference/bia/PERFIL BIA.jpg (monte o volume ...)` e a preparação do produto marca a referência como indisponível.

O volume nomeado `kiroo-data` herda o dono `kiroo` na primeira montagem. Com *bind mount* em `/data`, ajuste o dono: `sudo chown -R 10001:10001 <pasta>`.

## Trocar o pacote de assets e o hash

1. Envie o novo ZIP ao R2 (com a ferramenta de escrita que você já usa; o repositório não tem upload).
2. Calcule o SHA256: PowerShell `Get-FileHash .\pacote.zip -Algorithm SHA256`; Linux `sha256sum pacote.zip`.
3. Edite `assets.lock` (`object` e `sha256`) e commite.
4. Se o pacote passar a ter outros arquivos, ajuste `REQUIRED`/`ALLOWED_DIRS` em `docker/fetch_assets.py` (o teste `test_lista_de_obrigatorios_cobre_mapa_e_sprites_do_repositorio` acusa divergência com o mapa e os sprites) e rode `pytest tests/test_docker_assets.py`.
5. `docker compose build`. A mudança no `assets.lock` invalida o cache da camada de download.

O pacote deve manter o layout: `assets/characters/`, `assets/tilesets/`, `frontend/src/assets/home/`, `licenses/`, `README.txt`, `MANIFEST.txt` (SHA256 por arquivo). Qualquer arquivo fora desses caminhos, absoluto, com `..`, symlink, duplicado ou fora do `MANIFEST.txt` derruba o build. Limites: 200 arquivos, 64 MiB descompactados, 32 MiB por arquivo, 128 MiB de ZIP.

### Regenerar os lockfiles Python

`docker/requirements.lock` (Python 3.12, Linux, com hashes) e `docker/requirements-assets.lock` (boto3):

```bash
pip install uv
uv pip compile pyproject.toml --extra real --extra chat --constraint docker/constraints.txt --python-version 3.12 --python-platform linux --generate-hashes -o docker/requirements.lock
uv pip compile docker/requirements-assets.in --python-version 3.12 --python-platform linux --generate-hashes -o docker/requirements-assets.lock
```

`docker/constraints.txt` fixa `google-genai`, `pydantic` e `python-dotenv` nas versões já exercitadas pela suíte local. O `anthropic` (2.6.0) não estava instalado no ambiente de desenvolvimento, então o caminho com a API real dele não foi exercitado nos testes locais.

## Registro privado

A imagem contém arte sob licença que **proíbe redistribuir**. Nunca publique em registro público (Docker Hub público, `ghcr.io` público).

- Use um registro privado (GitHub Container Registry privado, ECR, GAR, Docker Hub privado) e restrinja quem pode fazer *pull*.
- Faça o push só depois de conferir a imagem (seção seguinte). Exemplo: `docker tag kiroo:local ghcr.io/ORG/kiroo:2026-11-06` e `docker push ...` depois de `docker login`.
- Se a CI construir a imagem, guarde as credenciais de leitura do R2 como secrets da CI e repasse com `--secret id=...,env=...`; nunca com `--build-arg`.
- A hospedagem precisa de credencial de *pull* do registro privado.

## Conferências depois do build real

Nada abaixo foi executado ainda. Rode depois do primeiro build.

**1. Sem credenciais e sem o ZIP nas camadas**

```bash
docker history --no-trunc kiroo:local | grep -i -E "r2_|secret|AKIA|\.zip" || echo "history limpo"
docker save kiroo:local -o kiroo-image.tar
mkdir kiroo-layers && tar -xf kiroo-image.tar -C kiroo-layers
find kiroo-layers -name "*.zip" -o -name "package.zip" ; echo "(nenhum .zip acima = ok; o stage assets não é exportado)"
```

Para procurar o valor real das credenciais sem imprimi-lo (bash):

```bash
for v in "$R2_ACCOUNT_ID" "$R2_ACCESS_KEY_ID" "$R2_SECRET_ACCESS_KEY"; do
  grep -r -F -l -- "$v" kiroo-layers >/dev/null 2>&1 && echo "ENCONTRADO em camada: FALHA" || echo "ok"
done
docker inspect kiroo:local --format '{{json .Config.Env}}' | grep -i -E "R2_|ACCESS_KEY" || echo "env limpo"
rm -rf kiroo-layers kiroo-image.tar
```

**2. Aplicativo, assets, créditos e licenças**

```bash
docker run --rm kiroo:local id                                   # uid=10001(kiroo)
docker run --rm kiroo:local python -m studio doctor              # ffmpeg, fonte, pastas; referência AUSENTE sem volume
docker run --rm kiroo:local ls /app/licenses                     # licenças LimeZu + PACOTE-README/MANIFEST
docker run --rm kiroo:local sh -c 'ls /app/frontend/dist/assets | grep -c -i -E "nina|theo|iris|rui|lia|beto|voce|Room_Builder|Modern_Office|interiors_atlas|sede"'
docker run --rm kiroo:local sh -c 'grep -rl "limezu.itch.io" /app/frontend/dist | head'   # crédito LimeZu presente
docker run --rm kiroo:local sh -c 'ls /app/assets; test ! -e /app/assets/bia && echo "sem foto pessoal na imagem"'
```

Os personagens e tilesets aparecem no `dist/assets` com hash no nome. Se o `grep -c` der zero, o build saiu sem os visuais (o Vite não falha quando faltam). No navegador: o escritório mostra os personagens (não "feijões"), a home mostra a sede, e "Sobre e créditos" e o rodapé da home citam LimeZu.

**3. Produção simulada** (cadastro fechado, cookie seguro, só leitura):

```bash
docker run -d --name kiroo-prod --read-only --tmpfs /tmp -p 127.0.0.1:8765:8765 \
  -v kiroo-prod-data:/data -v "$PWD/reference:/reference:ro" \
  -e STUDIO_MODE=simulated -e STUDIO_SIGNUP=closed -e STUDIO_SECURE_COOKIE=1 \
  -e STUDIO_PUBLIC_HOST=app.exemplo.test -e STUDIO_ALLOWED_HOSTS=app.exemplo.test -e STUDIO_TRUST_PROXY=forwarded \
  --init kiroo:local
curl -s http://127.0.0.1:8765/healthz                                           # {"status":"ok"}
curl -s -o /dev/null -w "%{http_code}\n" -H "Host: errado.test" http://127.0.0.1:8765/api/config   # 403
curl -s -H "Host: app.exemplo.test" http://127.0.0.1:8765/api/config            # "signup":"closed"
curl -s -X POST -H "Host: app.exemplo.test" -H "Content-Type: application/json" -d "{}" http://127.0.0.1:8765/api/auth/signup -o /dev/null -w "%{http_code}\n"   # 403
time docker stop kiroo-prod                                                      # SIGTERM: sai em segundos (limite STUDIO_SHUTDOWN_GRACE_S + 2 + STUDIO_SHUTDOWN_SETTLE_S)
docker rm kiroo-prod
```

Depois crie o admin, entre pela interface e rode uma produção no modo simulado (sem custo). Confirme que `/data` guarda o banco (`docker run --rm -v kiroo-prod-data:/data kiroo:local ls -la /data`).

## Evidências do build real

**Verificado manualmente por Christian em 2026-11-06, fora desta sessão** (a sessão de desenvolvimento não tem Docker e não repetiu estes passos):

- build real concluído, com o pacote baixado do R2;
- escritório exibido com os assets licenciados;
- login funcionando;
- produção simulada concluída;
- MP4 baixado e reproduzido;
- crédito ao LimeZu visível.

Observação registrada na sessão: a primeira abertura mostrou o escritório antigo porque o código tinha o renderizador antigo como padrão (flag no frontend), e não por problema da imagem, do mapa ou do pacote. Corrigido nos commits `a558404` e `8e76b82`; o novo (Phaser) é o único mundo.

Dados da imagem **não informados** nesta sessão e a preencher por quem rodou o build (nenhum é segredo):

| Item | Como obter | Valor |
|---|---|---|
| ID/digest da imagem | `docker image inspect kiroo:local --format '{{.Id}}'` | _a preencher_ |
| Python | `docker run --rm kiroo:local python --version` | _a preencher_ (base declarada no Dockerfile: `python:3.12-slim`) |
| ffmpeg | `docker run --rm kiroo:local ffmpeg -version` (1ª linha) | _a preencher_ (instalado por apt, sem versão fixa) |
| Node (build do frontend) | `docker run --rm node:22-bookworm-slim node --version` | _a preencher_ (base declarada: `node:22-bookworm-slim`) |

## Roteiro automatizado de verificação

`scripts/verify_image_layers.py` varre todas as camadas de `docker save` procurando o nome do ZIP, qualquer `*.zip`, caminhos de assets fora do esperado e os valores reais das variáveis `R2_*` (lidos do ambiente; imprime só `True/False`). Tem testes com imagem sintética (`tests/test_verify_image_layers.py`).

`scripts/verify_phase3.sh [a|b|c|d|all]` (Git Bash/Linux, com o Compose rodando) cobre: **a** camadas e `Config.Env` sem `R2_*`; **b** usuário não-root e permissões de escrita; **c** backup do volume (confere que abre) e persistência após `down` (sem `-v`) + `up --force-recreate`, comparando contagens, `integrity_check` e checksums da mídia; **d** o e2e de desligamento/retomada (`scripts/e2e_shutdown.py`) em contêiner descartável com dados próprios, e SIGTERM no serviço real. O script nunca usa `down -v`, `volume rm` nem `prune`. Foi executado por Christian no Docker local, com todas as verificações aprovadas (ver abaixo); a sessão de desenvolvimento só checou a sintaxe com `bash -n` e testou a lógica de `2a-fs` com um `docker` simulado. SIGKILL no serviço real e o `/readyz` 503 durante o desligamento ficam para verificação manual.

### Resultados da execução local (evidência fornecida por Christian)

**Fonte:** relatos de Christian, que rodou `scripts/verify_phase3.sh` no Docker local em 2026-11-06 e repetiu `2a-fs` depois da correção. A sessão de desenvolvimento não tem Docker e **não reproduziu** estes resultados; só recebeu o texto abaixo.

- Primeira execução: todas as verificações do roteiro foram executadas e passaram, exceto `2a-fs`, que terminou com `rc=2` e `NAO_VERIFICADO`.
- Segunda execução, só `2a-fs`, depois da correção (evidência executada por Christian):

```text
[PASS] 2a-fs — nenhum *.zip; 3 licença(s) LimeZu em /app/licenses; sem /app/assets/bia nem /reference/bia na imagem
RESUMO: PASS=1 FAIL=0 NAO_VERIFICADO=0
```

- **Fechamento: todas as verificações locais do roteiro passaram** (soma das duas execuções, segundo Christian). Isso fecha a validação da imagem no Docker local. Não substitui CI, a confirmação de licença para SaaS nem a definição do build de produção (ver `DEPLOY-DIAGNOSTICO.md`).

**Causa do `rc=2` em `2a-fs`** (diagnosticada na sessão pelo código): o script do contêiner terminava com `ls -d /app/assets/bia /reference/bia`, e `ls` sai com 2 quando os caminhos **não existem**, que é o resultado desejado. O `docker run` herdava esse código e a verificação o tratava como falha de execução. Correção (commit `05536cd`): o script do contêiner fecha com um marcador `---END`; `rc` diferente de 0, ou falta de `---LIC`/`---END`, continua sendo `NAO_VERIFICADO`; `.zip` ou `bia` na imagem continuam sendo `FAIL`. Para repetir só esta verificação:

```powershell
& "C:\Program Files\Git\bin\bash.exe" -lc "cd '/c/Users/chris/OneDrive/Documentos/Projetos/shopee-video-studio' && bash scripts/verify_phase3.sh --only 2a-fs"
```

Dados da imagem (ID, versões de Python, ffmpeg e Node): **não foram fornecidos** a esta sessão e seguem como _a preencher_ na tabela acima. Não são inferidos aqui.

## Arquivos desta fase

`Dockerfile`, `.dockerignore`, `docker-compose.yml`, `assets.lock`, `docker/fetch_assets.py`, `docker/requirements*.lock|.in`, `docker/constraints.txt`, `scripts/check_licensed_files.py` (check de Git; roda na CI), `.env.example` e `.env.docker.example`, `tests/test_docker_assets.py`.

O `.dockerignore` mantém fora do contexto: `.env` e variantes (exceto os exemplos), `data/`, bancos, `*.zip`, `node_modules/`, `.git/`, `assets/bia/`, a pasta de terceiros e as pastas de arte licenciada locais (assim a imagem só recebe arte pelo pacote verificado, nunca por uma cópia local esquecida).

## Licença da arte

Modern Interiors e Modern Office (LimeZu): uso comercial e edição permitidos; **proibido revender ou distribuir o asset a terceiros**; Modern Interiors exige crédito (<https://limezu.itch.io/moderninteriors>). O crédito está em "Sobre e créditos" e no rodapé da home. Os PNGs seguem para o navegador do usuário dentro do bundle; confirme com a LimeZu que isso cabe na licença para um SaaS (pendência já registrada no diagnóstico, item 5).
