# syntax=docker/dockerfile:1.7
#
# Kiroo — imagem de produção/teste. Veja docs/DOCKER.md.
#
# Build (credenciais de LEITURA do R2 vêm de BuildKit secrets, nunca de ARG/ENV):
#   docker build \
#     --secret id=r2_account_id,env=R2_ACCOUNT_ID \
#     --secret id=r2_access_key_id,env=R2_ACCESS_KEY_ID \
#     --secret id=r2_secret_access_key,env=R2_SECRET_ACCESS_KEY \
#     --build-arg GIT_COMMIT=$(git rev-parse HEAD) \
#     -t kiroo:local .
# GIT_COMMIT vira o rótulo org.opencontainers.image.revision (não é segredo; o ensaio compara com o HEAD).
#
# A imagem resultante contém arte licenciada (LimeZu): só para registro PRIVADO.

# ---------------------------------------------------------------- 1) assets licenciados
FROM python:3.12-slim AS assets
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /w
COPY docker/requirements-assets.lock ./
RUN pip install --require-hashes -r requirements-assets.lock
COPY docker/fetch_assets.py assets.lock ./
COPY assets/maps/office.tmj ./office.tmj
# Download, SHA256, extração segura e remoção do ZIP acontecem neste único RUN, com os secrets montados só nele.
RUN --mount=type=secret,id=r2_account_id \
    --mount=type=secret,id=r2_access_key_id \
    --mount=type=secret,id=r2_secret_access_key \
    python fetch_assets.py --lock assets.lock --map office.tmj --out /out --work /tmp/kiroo-assets

# ---------------------------------------------------------------- 2) frontend
FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
COPY assets/maps/ /app/assets/maps/
# arte licenciada entra aqui, antes do build (vite embute as folhas e os tilesets no bundle)
COPY --from=assets /out/assets/ /app/assets/
COPY --from=assets /out/frontend/src/assets/home/ ./src/assets/home/
RUN npm run build

# ---------------------------------------------------------------- 2b) Litestream (backup contínuo do SQLite)
# Versão e SHA-256 fixados em docker/litestream.lock. O build FALHA se o hash estiver "PENDING" ou não bater.
FROM python:3.12-slim AS litestream
WORKDIR /w
COPY docker/litestream.lock docker/fetch_litestream.py ./
RUN python fetch_litestream.py --lock litestream.lock --out /out/litestream

# ---------------------------------------------------------------- 3) runtime
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core tini rclone \
 && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 kiroo \
 && useradd --system --uid 10001 --gid kiroo --home-dir /nonexistent --shell /usr/sbin/nologin kiroo \
 && mkdir -p /data /reference \
 && chown kiroo:kiroo /data /reference

WORKDIR /app
# dependências exatas (Python 3.12/Linux, com hashes): core + extras real e chat (anthropic)
COPY docker/requirements.lock ./docker/requirements.lock
RUN pip install --require-hashes -r docker/requirements.lock
# O código roda direto de /app/src: config.PROJECT_ROOT = /app e GAME_DIST = /app/frontend/dist (derivados do caminho do código).
COPY src/ ./src/
COPY profiles/ ./profiles/
# backup/restauração: Litestream (banco) + rclone (mídia) + roteiros
COPY --from=litestream /out/litestream /usr/local/bin/litestream
COPY litestream.yml /etc/litestream.yml
COPY docker/entrypoint.sh /usr/local/bin/kiroo-entrypoint
COPY scripts/backup_media.sh scripts/restore.sh scripts/verify_restore.py ./scripts/
RUN chmod 0755 /usr/local/bin/kiroo-entrypoint /usr/local/bin/litestream ./scripts/*.sh
COPY assets/maps/ ./assets/maps/
COPY --from=frontend /app/frontend/dist ./frontend/dist
# licenças do pacote acompanham a imagem
COPY --from=assets /out/licenses/ ./licenses/
COPY --from=assets /out/README.txt ./licenses/PACOTE-README.txt
COPY --from=assets /out/MANIFEST.txt ./licenses/PACOTE-MANIFEST.txt

ENV PYTHONPATH=/app/src \
    STUDIO_DATA_DIR=/data \
    STUDIO_ASSETS_DIR=/app/assets \
    STUDIO_PROFILES_DIR=/app/profiles \
    STUDIO_REFERENCE_DIR=/reference \
    STUDIO_FONT_FILE=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf \
    STUDIO_HOST=0.0.0.0 \
    STUDIO_LOG_FORMAT=json
# A porta vem de PORT (ou STUDIO_PORT); sem nenhuma, 8765. Não fixamos STUDIO_PORT aqui para não anular o PORT da plataforma.

USER kiroo
VOLUME ["/data"]
EXPOSE 8765
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/healthz' % (os.environ.get('STUDIO_PORT') or os.environ.get('PORT') or '8765'), timeout=4)"]
ENTRYPOINT ["tini", "--", "kiroo-entrypoint"]
CMD ["python", "-m", "studio", "ui", "--no-browser"]
# Commit de origem, por último: mudar o commit não invalida o cache das camadas acima.
ARG GIT_COMMIT=desconhecido
LABEL org.opencontainers.image.revision=$GIT_COMMIT

