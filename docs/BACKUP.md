# Kiroo — Dados, migrações e backup (Fase 4)

Status: **implementado e testado com bancos, volumes, `rclone` e `litestream` descartáveis/falsos**. Nada aqui foi executado contra o R2 real nem contra o volume real `kiroo_kiroo-data`. A seção "O que você precisa executar" lista o que falta.

## 1. Schema versionado (`src/studio/migrations.py`)

- Lista ordenada e numerada (`MIGRATIONS`), versão em `PRAGMA user_version`. Hoje: **1 = schema completo**.
- Todas as pendentes rodam numa só transação `BEGIN IMMEDIATE` (DDL do SQLite é transacional): ou o banco chega à versão final, ou nada muda. O lock de escrita também serializa processos subindo juntos (testado com 4 processos).
- `Database()` chama `migrate()` a cada conexão; com o banco em dia isso é só um `PRAGMA user_version`. O servidor também migra uma vez no boot (`serve()`, depois do lock de instância) e **não sobe** se a migração falhar.
- **Banco anterior ao versionamento** (`user_version=0` com tabelas): a migração 1 cria o que falta (`IF NOT EXISTS`), acrescenta as colunas que faltam com os mesmos preenchimentos dos `ALTER` antigos (`credits_exempt` para o dono da plataforma, `email_verified_at = created_at`), **valida** tabelas, colunas e índices contra o schema esperado, roda `quick_check` e só então marca a versão 1. Se não der para completar (ex.: coluna obrigatória ausente numa tabela que não pode ser alterada), levanta `MigrationError`, faz rollback e o banco fica **intacto e sem versão**.
- Banco com versão **maior** que a do código é recusado.
- Para evoluir o schema: acrescente `Migration(2, "...", fn)` ao fim da lista. Nunca edite uma migração já publicada.
- Os `CREATE TABLE`/`ALTER TABLE` antes espalhados em `db.py`, `accounts.py`, `credits.py`, `music.py`, `training.py` e `agent_chat.py` saíram dos construtores.

## 2. Créditos sob concorrência

`Ledger` (`credits.py`) faz toda escrita (`add`, `hold`, `release`, `close_direct`, `settle`) dentro de `BEGIN IMMEDIATE`: o saldo é lido e a reserva gravada sob o lock de escrita do arquivo, então o saldo **nunca fica negativo** (exceto workspace isento, por definição). O `RLock` em memória continua apenas para threads que compartilham uma mesma conexão (o orquestrador usa uma); a exclusão entre conexões e processos vem do SQLite. Testado com 24 threads de conexões independentes e com 4 processos separados (`tests/test_credits_concurrency.py`).

## 3. Conexões

`db.connect()`: WAL, `synchronous=NORMAL`, `busy_timeout=30000`, `foreign_keys=ON`, uma conexão por requisição. Checkpoint: `wal_autocheckpoint` padrão do SQLite mais um checkpoint `PASSIVE` a cada `STUDIO_WAL_CHECKPOINT_S` (padrão 300 s; `0` desliga). `PASSIVE` nunca bloqueia nem atrapalha o Litestream. Com `synchronous=NORMAL`, uma queda de energia/SO pode perder as últimas transações já confirmadas, mas não corrompe o banco.

## 4. Variáveis

| Variável | Onde | Secreta | Função |
|---|---|---|---|
| `STUDIO_ENV` | ambiente | não | `dev` (padrão) \| `staging` \| `production`. Define o prefixo no bucket e liga o aviso de backup ausente. |
| `BACKUP_R2_ENDPOINT` | ambiente | não | `https://<ID_DA_CONTA>.r2.cloudflarestorage.com` |
| `BACKUP_R2_ACCESS_KEY_ID` | ambiente | sim | Chave com leitura/escrita **restrita a `kiroo-backups`** |
| `BACKUP_R2_SECRET_ACCESS_KEY` | ambiente | sim | idem |
| `BACKUP_BUCKET` | ambiente | não | Padrão `kiroo-backups` |
| `BACKUP_R2_PREFIX` | ambiente | não | Prefixo no bucket (`<prefixo>/db`, `<prefixo>/media`). Padrão: o valor de `STUDIO_ENV`. O ensaio usa `ensaio` |
| `LITESTREAM_CONFIG` | ambiente | não | Configuração usada pelo `restore.sh`. Padrão `/etc/litestream.yml` (imagem); sem ele, `./litestream.yml` do repositório |
| `STUDIO_ALLOW_NO_BACKUP` | ambiente | não | `1`: permite subir em `production` sem `BACKUP_R2_*` (então `/readyz` = 503). Só para emergência. |
| `STUDIO_RESTORE_ON_EMPTY` | ambiente | não | `1`: se o volume não tiver banco e existir réplica, restaura antes de subir (nunca sobrescreve). Padrão desligado. |
| `STUDIO_WAL_CHECKPOINT_S` | ambiente | não | Intervalo do checkpoint PASSIVE. |

Nenhuma credencial é gravada em arquivo versionado, em `litestream.yml` (usa `${VAR}`), em log, em `/readyz` ou em mensagens de erro (os avisos citam só **nomes** de variáveis). `rclone` recebe as chaves por variáveis `RCLONE_CONFIG_KBK_*`, não por linha de comando.

Layout do bucket `kiroo-backups`:

```
<ambiente>/db/...                       réplica do Litestream (snapshots + WAL)
<ambiente>/media/current/<pasta>/...    espelho mais recente da mídia
<ambiente>/media/archive/<data>/...     versões substituídas/removidas (nunca apagadas pelo script)
<ambiente>/media/manifests/<data>.json  tamanhos/contagens por execução
```

## 5. Banco: Litestream

- `litestream.yml` replica `${STUDIO_DATA_DIR}/studio.sqlite3` para `s3://kiroo-backups/<STUDIO_ENV>/db` (endpoint do R2, `sync-interval: 1s`, snapshot a cada 6 h, retenção 168 h).
- `docker/entrypoint.sh` (ENTRYPOINT `tini -- kiroo-entrypoint`) executa `litestream replicate -exec "<servidor>"`. O Litestream repassa SIGTERM ao servidor e faz a última sincronização ao sair (o `stop_grace_period: 40s` do compose continua válido).
- **Sem as variáveis de backup (`BACKUP_R2_*`):**
  - `dev`: sobe direto.
  - `staging`: sobe **com aviso alto** (stderr do entrypoint, `CRITICAL` no log, `event=backup_missing`) e `"warnings": ["backup_not_configured"]` em `/readyz` (continua `200`; monitore o campo).
  - `production`: o servidor **recusa subir** (`SystemExit` com a lista dos nomes que faltam, antes de abrir a porta). Exceção deliberada: `STUDIO_ALLOW_NO_BACKUP=1` (só o valor `1`); aí sobe com `CRITICAL` e `/readyz` responde **`503`** com o warning, até o backup ser configurado.
  - O entrypoint do contêiner só avisa; quem decide recusar é o servidor, que roda logo em seguida.
- A imagem instala o Litestream pelo `docker/litestream.lock` (versão + SHA-256). O hash está **PENDING de propósito**: o build falha até você fixá-lo (abaixo). Não foi inventado nenhum hash.

### Fixar o hash do Litestream
1. Baixe `litestream-v0.3.13-linux-amd64.tar.gz` da release oficial `benbjohnson/litestream` e calcule o SHA-256 (`sha256sum arquivo.tar.gz` / `Get-FileHash`).
2. Confira com o hash publicado na página da release (ou outra fonte independente).
3. Coloque em `docker/litestream.lock` (campo `sha256`). Se escolher outra versão, troque `version` e `url`.

### Ordem de parada (SIGTERM) com Litestream
Cadeia: plataforma → `tini` (PID 1) → `kiroo-entrypoint` faz `exec litestream replicate -exec "<servidor>"` (o `exec` troca o shell pelo Litestream; não sobra shell no meio) → o Litestream roda o servidor como filho.
1. `tini` repassa o SIGTERM ao Litestream (seu único filho).
2. O Litestream repassa o sinal ao servidor e **espera ele terminar** (comportamento do `-exec` do Litestream 0.3.x, conforme a documentação; **não verificado aqui com o binário real**: ver passo de verificação).
3. O servidor passa a responder `503` em `/readyz`, recusa novas produções, deixa terminar a etapa em curso até `STUDIO_SHUTDOWN_GRACE_S` (25 s), marca o resto como `interrupted` e sai. Ou seja, **o servidor para de escrever antes** de qualquer encerramento do Litestream.
4. Só depois que o filho sai, o Litestream faz a **última sincronização** do WAL para o R2 e encerra com o código do filho.
5. O tempo total precisa caber na tolerância da plataforma: `stop_grace_period: 40s` no compose (25 s de drenagem + sincronização final); em outro orquestrador, configure ≥ 40 s. SIGKILL no meio perde no máximo o que ainda não foi sincronizado (≈ `sync-interval`).
Checkpoints: o código da aplicação só executa `PRAGMA wal_checkpoint(PASSIVE)` (`db.checkpoint`); não há `TRUNCATE`/`RESTART` (teste `test_app_only_runs_passive_checkpoints`). O SQLite faz seus checkpoints automáticos também `PASSIVE`, e o Litestream mantém uma leitura aberta que impede o reinício/truncamento do WAL por terceiros.
**Verificação real (a executar):** num volume descartável com backup configurado, `docker stop` e leia `docker logs`: o log do servidor mostra o `SIGTERM`/drenagem antes de qualquer mensagem de encerramento do Litestream, e o Litestream registra o fechamento/última sincronização; depois `restore.sh` deve trazer a última escrita feita antes do `stop`.

## 6. Mídia: `scripts/backup_media.sh`

`rclone sync` de `productions`, `uploads`, `workspaces`, `music` e `training` (mais `agents.json`) para `…/media/current/`, com `--backup-dir …/archive/<data>/<pasta>`: o que seria sobrescrito ou apagado é **movido** para o arquivo datado, nunca destruído. O script não usa `delete`/`purge`/`--delete-excluded`. Recusa (código 3) origem vazia (volume desmontado/errado), usa lock contra execuções sobrepostas, aceita `--dry-run` e grava um manifesto por execução. `sound_cache`, `sim_ops`, `demo_inputs` e `logs` ficam de fora (regeneráveis/efêmeros). *Acréscimo deliberado:* `music` e `training` guardam arquivos do usuário e não estavam na lista original.

```bash
STUDIO_ENV=production STUDIO_DATA_DIR=/data bash scripts/backup_media.sh
```

Agendamento diário: como o volume só se monta no serviço do app, a tarefa precisa rodar **onde o volume está montado** (cron no host/VPS, ou um agendador que execute o comando dentro do contêiner; `rclone` e o script já estão na imagem em `/app/scripts`). Isso é decisão da Fase 7 (Railway); aqui só o script está pronto. A retirada de versões antigas de `archive/` é decisão separada: use uma regra de ciclo de vida do bucket (ex.: expirar `*/media/archive/` após 90 dias) — o script nunca faz isso.

## 7. Restauração: `scripts/restore.sh`

```bash
STUDIO_ENV=staging bash scripts/restore.sh --dest /caminho/NOVO [--timestamp 2026-11-06T12:00:00Z] [--hash]
```

- **Nunca sobrescreve**: o destino precisa ser novo/vazio (não há `--force`); recusa destino igual a, dentro de, ou contendo `STUDIO_DATA_DIR`.
- Restaura o banco (`litestream restore`, opcionalmente em ponto no tempo) e o espelho `media/current` (`rclone copy`, nunca `sync`), e roda `scripts/verify_restore.py`: `integrity_check`, chaves estrangeiras, versão do schema, contagem de registros, e para cada tentativa concluída se o arquivo existe (e, com `--hash`, se o SHA-256 bate). Não imprime e-mails nem senhas.
- Saídas: `0` ok · `1` validação falhou · `2` uso · `3` destino recusado · `4` falha ao restaurar · `5` banco íntegro, mídia incompleta.
- Ensaio sem R2: `--local-db arquivo.sqlite3 --local-media pasta` (é o que os testes usam).
- Para abrir o restaurado sem tocar no real: `STUDIO_DATA_DIR=<dest> STUDIO_PORT=8799 STUDIO_MODE=simulated python -m studio ui --no-browser`.

### Alinhar banco e mídia (frequências diferentes)
O banco é replicado a cada ~1 s; a mídia é um espelho diário. Depois de um restore:
1. **Banco mais novo que a mídia** (o caso normal): tentativas concluídas depois do último backup de mídia apontam para arquivos que não existem na cópia. O `verify_restore` lista as **produções afetadas** (código `5`). Opções: reexecutar/regenerar essas produções, ou, se o disco original ainda existe, copiar os arquivos delas.
2. **Quer um estado consistente num instante T:** restaure o banco com `--timestamp T` onde T ≤ hora do último manifesto de mídia (`…/media/manifests/`). Então todo arquivo citado pelo banco já estava no espelho.
3. **Arquivo apagado/sobrescrito por engano depois:** a versão anterior está em `…/media/archive/<data>/`; recupere com `rclone copy` apontando para o arquivo.
4. Mídia mais nova que o banco só deixa arquivos órfãos (inofensivos).

## 8. RPO e RTO — **metas, ainda não medidas**

| | Meta | Base | Medido? |
|---|---|---|---|
| RPO do banco | segundos a 1 min | `sync-interval: 1s` do Litestream | **Não** |
| RPO da mídia | até 24 h | backup diário | **Não** |
| RTO | até 1 h (banco pequeno; mídia depende do tamanho e da banda) | tempo de `litestream restore` + `rclone copy` + validação | **Não** |

Só viram números oficiais depois de um restore real cronometrado (passo 4 abaixo). Anote ali data, tamanho do banco/mídia, tempo de cada etapa e o resultado do `verify_restore`.

## 9. Escritas fora de `STUDIO_DATA_DIR`

Auditoria: dados **persistentes** do app (banco, lock, logs, `sound_cache`, `sim_ops`, `demo_inputs`, produções, uploads, música, treinamento, workspaces, `agents.json`) derivam de `STUDIO_DATA_DIR`. O código não usa `tempfile`/`/tmp` (teste estático em `tests/test_backup_tools.py`). Temporários e escritas que **ficam fora** por necessidade:

| O quê | Onde | Por quê |
|---|---|---|
| Temporários do `ffmpeg`/Python/rclone | `/tmp` do contêiner (ou `TMPDIR`) | Do próprio processo, descartáveis. Se o contêiner tiver sistema de arquivos só-leitura, monte um `tmpfs` em `/tmp`. |
| Pasta `.<db>-litestream` (shadow do Litestream) | ao lado do banco, **dentro** de `STUDIO_DATA_DIR` | Fica no volume (não é mídia; não entra no backup de mídia). |
| `STUDIO_REFERENCE_DIR` (`/reference`) | volume só-leitura | Entrada (foto da apresentadora), nunca gravada. |
| Bytecode Python | desligado na imagem (`PYTHONDONTWRITEBYTECODE=1`) | — |
| `studio publish`/CLI locais (cloudflared etc.) | máquina do desenvolvedor | Não rodam no servidor. |

## O que foi implementado e testado (sem R2, sem Docker, sem volume real)

- Migrações, idempotência, banco antigo completo e parcial, recusa segura com rollback, 4 processos subindo juntos: `tests/test_migrations.py`.
- Créditos: threads com conexões independentes e processos distintos: `tests/test_credits_concurrency.py`.
- `verify_restore`, `restore.sh` (modo local; recusa sobrescrever e volume real), `backup_media.sh` e `entrypoint.sh` com `rclone`/`litestream` falsos, aviso de backup em `/readyz`, ausência de credenciais em `litestream.yml`, hash PENDING falhando fechado, exportador idempotente: `tests/test_backup_tools.py`.
- Suíte completa do backend no Python 3.12 do Windows (veja o resumo do HANDOFF para a contagem).

## O que você precisa executar (não verificado)

Credenciais **somente no terminal, nunca no chat**. PowerShell:

```powershell
$env:STUDIO_ENV = "staging"          # use staging/dev para ensaiar; NÃO use production
$env:BACKUP_R2_ENDPOINT = "https://<ID_DA_CONTA>.r2.cloudflarestorage.com"
$env:BACKUP_R2_ACCESS_KEY_ID = Read-Host "access key id (kiroo-backups)"
$env:BACKUP_R2_SECRET_ACCESS_KEY = [System.Net.NetworkCredential]::new("", (Read-Host "secret" -AsSecureString)).Password
# ao terminar:
Remove-Item Env:BACKUP_R2_ENDPOINT, Env:BACKUP_R2_ACCESS_KEY_ID, Env:BACKUP_R2_SECRET_ACCESS_KEY
```

1. **Fixar o hash do Litestream** (seção 5) e construir a imagem (`docker compose build`, com as credenciais de LEITURA do `kiroo-assets` como na Fase 3).
2. **Replicação real num volume descartável** (nunca no `kiroo_kiroo-data`): suba com um volume novo (`docker compose -p kiroo-bk-teste up` com `STUDIO_ENV=staging` e as variáveis acima exportadas), crie um usuário/produção simulada e confirme em `…/staging/db/` no bucket que apareceram objetos.
3. **Backup de mídia real**: `STUDIO_ENV=staging STUDIO_DATA_DIR=<pasta descartável> bash scripts/backup_media.sh --dry-run`, depois sem `--dry-run`; altere/apague um arquivo e repita para ver a versão antiga em `archive/`.
4. **Restore real e cronometrado** numa pasta nova: `STUDIO_ENV=staging bash scripts/restore.sh --dest <pasta nova> --hash`; abra com `STUDIO_DATA_DIR=<pasta nova> STUDIO_PORT=8799`. Registre os tempos para substituir as metas da seção 8.
5. Confirmar que `litestream.yml` funciona com o R2 (endpoint, `force-path-style`, assinatura): se o Litestream reclamar de assinatura/payload, a mensagem indica o ajuste (ex.: `sign-payload`).
6. Conferir `/readyz` com `STUDIO_ENV=staging` e **sem** as variáveis (200 + `warnings`), e que `STUDIO_ENV=production` sem elas **não sobe** (e, com `STUDIO_ALLOW_NO_BACKUP=1`, sobe com `/readyz` 503).
6b. Verificar a ordem de parada (final da seção 5).
7. Tarefa agendada diária do `backup_media.sh` e regra de ciclo de vida de `archive/` (Fase 7).
8. Calendário: repetir o restore antes do beta e todo mês.

## Pendências e decisões

- **Exportador de dados locais** (`scripts/export_local_data.py`): pronto e testado, **opcional**; a decisão de migrar os dados de hoje continua em aberto. Se migrar: `export` na origem (leitura), copiar à mão `data/productions/<id>/` das produções listadas, `import --dry-run` e depois `import` no destino. O bundle contém e-mails e hashes de senha.
- Litestream/rclone na imagem (hash PENDING, `rclone` do Debian) ainda não foram construídos nem exercitados em Docker.
