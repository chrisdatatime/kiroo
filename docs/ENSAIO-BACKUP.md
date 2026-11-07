# Ensaio de backup e restauração (staging, Windows)

Roteiro único para provar, na sua máquina, o backup do banco (Litestream), o backup da mídia (rclone) e a
restauração, contra o bucket real `kiroo-backups` no prefixo **`ensaio/`** (`BACKUP_R2_PREFIX=ensaio`, passado
aos containers pelo script), nunca em `staging/`. Tudo roda em PowerShell nativo pelo
[`scripts/ensaio_backup.ps1`](../scripts/ensaio_backup.ps1). Contexto técnico: [BACKUP.md](BACKUP.md).

**Estado deste documento:** o script foi escrito e checado só quanto à sintaxe e aos caminhos de recusa
(sem credenciais: passo 1 → `NAO_VERIFICADO`; `-Volume kiroo_kiroo-data` → recusado; passo 3 sem pasta →
`NAO_VERIFICADO`; a checagem de imagem detecta que a `kiroo:dados` de `523cacd` não tem `BACKUP_R2_PREFIX`). **Nenhum passo foi executado contra o R2 ou com containers.** Os resultados abaixo ficam
em branco até você rodar.

## Regras de segurança (embutidas no script)

| Regra | Como o script garante |
|---|---|
| Credenciais nunca impressas | Só imprime `NOME: presente/AUSENTE`. Vão para o container com `-e NOME` **sem valor**; dentro do container, scripts auxiliares (`<pasta>\sh\*.sh`) copiam `$BACKUP_R2_*` para as variáveis do rclone/Litestream. Nada de credencial em linha de comando nem em arquivo. |
| Só o volume do ensaio | Nome fixo `kiroo-ensaio-dados`, criado com o rótulo `kiroo.ensaio=backup`. Outro nome → recusado. Antes de usar/remover, confere o rótulo. |
| `kiroo_kiroo-data` intocado | Nunca montado. Só `docker volume inspect` (data de criação) e `docker system df -v` (tamanho), no passo 1 e no 6. |
| Containers descartáveis | Todos com `--label kiroo.ensaio=backup`; os temporários com `--rm --tmpfs /data` (sem volume anônimo). |
| Bucket só leitura no ensaio | Conferências usam `rclone lsf` / `rclone cat`. Escritas no bucket vêm apenas do próprio produto (Litestream e `backup_media.sh`) em `ensaio/`. Nada é apagado. |
| Prefixo exclusivo `ensaio/` | Fixo no script. O passo 1 lista `ensaio/db` e `ensaio/media`: aceita vazio ou sobras de ensaios anteriores (o prefixo só é usado pelo ensaio). O restore usa a geração mais recente do Litestream e o passo 4 só considera `archive/` posterior ao seu início. |
| Imagem com a correção | O passo 1 confere que `/etc/litestream.yml`, `restore.sh` e o entrypoint da imagem conhecem `BACKUP_R2_PREFIX`. Imagem antiga (que replicaria em `staging/`) → `NAO_VERIFICADO`. |

## Antes de começar

No **mesmo** terminal PowerShell (os valores vêm de onde você os guarda; não cole no chat):

```powershell
$env:STUDIO_ENV = 'staging'
$env:BACKUP_BUCKET = 'kiroo-backups'
# BACKUP_R2_ENDPOINT, BACKUP_R2_ACCESS_KEY_ID, BACKUP_R2_SECRET_ACCESS_KEY: defina sem ecoar
```

Pré-condições: Docker Desktop rodando e imagem `kiroo:dados` **reconstruída** a partir do `deploy/dados` atual
(com a correção do `restore.sh` e o `BACKUP_R2_PREFIX`). A imagem construída em `523cacd` é recusada pelo passo 1.
`STUDIO_ENV` continua `staging` (comportamento do servidor); só o prefixo no bucket muda.

Pasta do ensaio: `%TEMP%\kiroo-ensaio` (troque com `-Pasta`). Ela recebe `estado.json` (resultados e ids, sem
credenciais), os scripts auxiliares, os restores e o log do passo 3. Porta do container: `127.0.0.1:8799`.

Cada passo imprime `RESULTADO passo N: PASS|FAIL|NAO_VERIFICADO`. `NAO_VERIFICADO` = a verificação nem rodou
(falta pré-requisito). Para rodar tudo em sequência (para no primeiro não-PASS): `-Passo todos`.

---

## Passo 1 — Pré-requisitos

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 1
```

Faz: confere `STUDIO_ENV=staging`, as 4 variáveis (`BACKUP_R2_ENDPOINT`, `BACKUP_R2_ACCESS_KEY_ID`,
`BACKUP_R2_SECRET_ACCESS_KEY`, `BACKUP_BUCKET=kiroo-backups`) sem imprimir valores; Docker, imagem e se ela suporta
`BACKUP_R2_PREFIX`; cria a pasta (com marcador) e o volume `kiroo-ensaio-dados` com rótulo; lista `ensaio/db` e `ensaio/media` (prova
leitura no bucket); anota data de criação e tamanho de `kiroo_kiroo-data`.

Também compara o commit gravado na imagem (rótulo `org.opencontainers.image.revision`) com o `HEAD` da branch.
Se forem diferentes, avisa e lista os arquivos que entram na imagem e mudaram desde então (`scripts`, `docker`,
`litestream.yml`, `Dockerfile`, `src`). **Mudanças em scripts só valem no ensaio depois de reconstruir a imagem.**
É só aviso, não muda o resultado. Construa sempre com o commit (PowerShell, na raiz do repositório):

```powershell
docker build --build-arg "GIT_COMMIT=$(git rev-parse HEAD)" -t kiroo:dados .
```

Isso funciona sem as credenciais de leitura do R2 enquanto a camada de assets (`fetch_assets.py`) estiver no
cache do BuildKit: os secrets são opcionais e não entram na chave de cache. Sem cache, acrescente os três
`--secret` (docs/DOCKER.md). Não use `--no-cache` nem `--pull`.

**Esperado:** quatro linhas `presente`, `volume kiroo-ensaio-dados criado com rotulo`, `objetos ja existentes:
ensaio/db=0 ensaio/media=0` (ou o aviso de sobras de ensaio anterior), `RESULTADO passo 1: PASS`.

**Se falhar:**
- `AUSENTE` / `STUDIO_ENV deve ser 'staging'` → defina no terminal e rode de novo (`NAO_VERIFICADO`, nada foi criado).
- `imagem kiroo:dados nao encontrada` ou `sem suporte a BACKUP_R2_PREFIX` → reconstrua a imagem do `deploy/dados` atual.
- `listagem ... falhou` → endpoint/chave errados ou token sem permissão de leitura no `kiroo-backups`.
- `volume ... ja existe` → rode o passo 6 e depois o 1.

## Passo 2 — Replicação

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 2
```

Faz: sobe `kiroo:dados` como `kiroo-ensaio` no volume do ensaio (`STUDIO_MODE=simulated`,
`STUDIO_SIGNUP=open`, só em 127.0.0.1:8799), espera `/readyz` 200; cria a conta de teste
`ensaio-<data>@ensaio.test` (senha aleatória, nunca impressa nem gravada) e 2 produções simuladas
(`POST /api/demo`); espera as contagens do banco ficarem estáveis (até 5 min) + 10 s; lista `ensaio/db` no
bucket; restaura com `scripts/restore.sh --db-only` (Litestream) em `<pasta>\restore-p2-*`; compara as
contagens (`users workspaces memberships productions scenes attempts credit_entries`) do banco vivo com as do
restaurado (`verify_restore.py --json`).

**Esperado:** lista de objetos em `ensaio/db` (gerações/snapshots/WAL), `banco vivo` e `restauracao` com a
mesma linha de contagens, `PASS`.
O restore mostra `restore.sh --db-only codigo 5 (midia incompleta, esperado com --db-only)`: o banco
restaurado aponta para mídia que não foi restaurada. Isso é normal neste passo. Só um código diferente de 0 e de 5 é falha.

**Se falhar:**
- `/readyz nao ficou 200` → o script mostra as 40 últimas linhas do log; procure `entrypoint:` (variável faltando) ou erro do Litestream.
- erro no signup/demo (400/403) → a resposta aparece no erro; confira `STUDIO_ALLOWED_HOSTS` e se a porta 8799 está livre.
- `objetos em ensaio/db: 0` → o Litestream não está replicando; `docker logs kiroo-ensaio` mostra o motivo.
- contagens diferentes → rode o passo de novo só depois de investigar (o container continua no ar; o volume já tem dados — se quiser recomeçar do zero: passo 6, 1, 2).
- `restore.sh` código 4 → `litestream restore` não achou réplica: confira o prefixo e o relógio da máquina.

> O `restore.sh` roda com a configuração da própria imagem (`/etc/litestream.yml`, via `LITESTREAM_CONFIG`),
> sem montagem extra: o ensaio exercita o caminho real. (Antes da correção ele procurava `/app/litestream.yml` e
> falhava com `config file not found`; agora há teste de regressão em `tests/test_restore_image.py`.)

## Passo 3 — `docker stop -t 40`

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 3
```

Faz: cria a conta `ultima-<data>@ensaio.test` (a última escrita) e, 0,5 s depois, `docker stop -t 40`,
cronometrado; em paralelo sonda `/readyz` a cada 100 ms; mostra o código de saída do container
(`State.ExitCode`), as linhas do log com `SIGTERM`, `desligamento`, `litestream`, `sync`, `snapshot`, etc.
(log completo em `<pasta>\passo3-log.txt`); restaura de novo e confere se a conta `ultima-...` está no banco
restaurado.

**Esperado:** tempo bem abaixo de 40 s, código de saída `0`, log com `SIGTERM: parando de aceitar jobs`,
`/readyz` com alguns `503` antes de `sem_conexao`, restore `contem a ultima escrita: True`, `PASS`.

Critério de PASS: última escrita presente **e** saída 0 **e** tempo < 40 s. O `503` é relatado à parte: sem
produção em andamento o servidor drena em milissegundos e a sonda pode não pegar o 503 — nesse caso o script
diz que esse sub-item é `NAO_VERIFICADO` (não conta como PASS do item). O Litestream 0.3 não escreve
necessariamente uma linha de "última sincronização"; se nenhuma linha dele aparecer, a prova é o restore
conter a última escrita.

**Se falhar:**
- tempo ≈ 40 s e saída 137 → o Docker matou com SIGKILL: o processo não terminou no prazo (veja `passo3-log.txt`; tini → litestream → servidor deve repassar o SIGTERM).
- última escrita ausente → a sincronização final do Litestream não aconteceu ou não terminou: é exatamente o defeito que este passo procura; anote e não avance para produção.
- `container ... nao esta rodando` → rode o passo 2.

## Passo 4 — Mídia

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 4
```

Faz (container descartável com o volume do ensaio em `/data`, servidor parado): grava
`productions/ensaio-marcador.txt` = `versao-1` (e um `.ensaio-placeholder` em pastas de usuário vazias, porque
`backup_media.sh` recusa origem vazia com código 3); `backup_media.sh --dry-run`; `backup_media.sh` real; altera
o marcador para `versao-2`; roda de novo; lista `ensaio/media/archive/` e lê o marcador arquivado e o atual.

Cada execução mostra o código com o significado (`0 ok`, `1 FALHA do rclone`, `2 uso/config invalida`,
`3 recusado: origem vazia`, `4 outra execucao em andamento`) e a linha
`objetos enviados: N; origem: X objetos, Y bytes (Z MB); manifesto: ...`. Com código diferente de 0 também mostra
as linhas `ERRO`/`FALHOU` do `backup_media.sh`.

**Esperado:** códigos 0, 0, 0; `em archive/: <AAAA-MM-DDTHHMMSSZ>/productions/ensaio-marcador.txt`;
`archive contem 'versao-1'; current contem 'versao-2'`; `PASS`.

**Se falhar:**
- código 1 com `manifesto: NAO GRAVADO` e `501` → os objetos enviados ficam no bucket (nada é apagado); rode o
  diagnóstico abaixo antes de mexer no script.
- código 3 → alguma pasta de usuário vazia que o script não cobriu; a mensagem diz qual.
- código 4 → outra execução com o mesmo lock (não deveria ocorrer em container novo).
- nada em `archive/` → o `--backup-dir` não foi usado/aceito; veja a saída do rclone.
- `pare o container do ensaio antes` → rode o passo 3.
- `variaveis ausentes: ...` (`NAO_VERIFICADO`) → os passos 4 e 5 exigem `STUDIO_ENV`, `BACKUP_BUCKET` e as três
  `BACKUP_R2_*` no terminal; a mensagem lista as que faltam (só nomes).
- código 2 → o ensaio mostra a mensagem do `backup_media.sh` (variável ausente, argumento inválido, etc.).

Leituras de conteúdo (`rclone cat`, `rclone lsf`, `verify_restore.py`) usam **só o stdout**. O rclone escreve
avisos no stderr (por exemplo `NOTICE: Config file "/nonexistent/.rclone.conf" not found`), que aparecem à parte
e não entram na comparação. A comparação é exata: `versao-1` no archive e `versao-2` no current.

### Diagnóstico do 501 (`-Passo 4 -Diagnostico`)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 4 -Diagnostico
```

Faz **uma** operação de escrita: `rclone copyto` de um arquivo de ~40 bytes, gerado dentro do container, para
`ensaio/diag/<AAAA-MM-DDTHHMMSSZ>.txt` (objeto novo; nada existente é sobrescrito nem apagado), com
`-vv --dump headers --retries 1 --low-level-retries 1`. **Nunca** `--dump auth`. Mostra os cabeçalhos da
requisição e da resposta e grava a saída em `<pasta>\diag-<data>.txt`.

Antes de imprimir ou gravar, a saída passa por `Mask-Cred`: troca os valores de `BACKUP_R2_ACCESS_KEY_ID`,
`BACKUP_R2_SECRET_ACCESS_KEY` e `BACKUP_R2_ENDPOINT` por `***NOME***`, apaga o valor de `Authorization`,
`X-Amz-Security-Token`, `Cookie`, `Credential=`/`Signature=` e o id da conta em `<id>.r2.cloudflarestorage.com`.
A máscara é testada com valores fictícios em `scripts	est_ensaio_backup.ps1`.

Leitura: com `501`, compare os cabeçalhos da **requisição** com a lista de cabeçalhos que o R2 não implementa.
O suspeito anotado em BACKUP.md é `X-Amz-Acl: private`. `PASS` = o envio deu certo (código 0).

## Passo 5 — Restore cronometrado

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 5
```

Faz três restaurações em pastas novas (o `restore.sh` recusa destino com conteúdo): `--db-only`,
`--media-only` e completa com `--hash`; cronometra cada uma; roda `verify_restore.py --hash` na completa.

**Esperado:** `tempos: banco X s | midia Y s | total com --hash Z s`, verificação `RESULTADO: OK`, `PASS`.
Os tempos são o primeiro dado medido de RTO (em BACKUP.md §8 ainda são metas) — anote-os.

**Se falhar:**
- código 5 / `MIDIA INCOMPLETA` → arquivo de produção ausente na mídia restaurada: o passo 4 rodou antes das produções terminarem? Veja os ids listados.
- `hash divergente` → arquivo corrompido ou alterado depois do registro; anote o id.
- código 1 → banco corrompido ou schema incompatível: é falha real.

## Passo 7 — Desligamento sob carga (rodar antes do passo 6)

Primeiro a **fumaça** (1 rodada de cada tipo: a1, b1, c1), para validar a mecânica com o R2 real; só depois o ciclo
completo:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 7 -Fumaca
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 7            # -Rodadas 5 (padrão)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 7 -Rodadas 2 # 1..5
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 7 -Tipos a -Rodadas 5 -Carga alta
```

- `-Tipos` (padrão `a,b,c`): quais rodadas rodar. `a` = stop com escritas; `b` = reinício no volume da `a`; `c` =
  SIGKILL (independente). `b` sem `a` é **recusado** antes de qualquer docker. Aceita `-Tipos a,c` ou `-Tipos "a,c"`
  (com `powershell -File` a lista chega como uma string só; por isso o parâmetro valida por padrão, não por
  `ValidateSet`).
- `-Carga baixa|normal|alta` (padrão `normal`): só o ritmo dos cadastros nas rodadas `a`; o servidor não muda. Ver
  [WAL no fechamento](#wal-no-fechamento-x-erro-do-litestream).

Precisa só do passo 1 (pasta) e das 5 variáveis. Não usa o container nem o volume dos passos 2–5: cada rodada
cria o seu volume (`kiroo-ensaio-p7-a1..a5`, `kiroo-ensaio-p7-c1..c5`, com o rótulo do ensaio), o container
`kiroo-ensaio-p7` na porta `-Porta`+1 (8800) e apaga os dois ao fim da rodada.

**Saída em arquivo (sobrevive a um corte de sessão):** cada linha também vai para
`<pasta>\p7-<modo>-<data>.log` (`modo` = `fumaca` ou `rodadasN`, mais `-<tipos>` se não forem os três e `-<carga>`
se não for `normal`; ex.: `p7-rodadas5-a-alta-…`), já mascarada (o script só imprime nomes de
variáveis, nunca valores), e o resultado acumulado é regravado depois de **cada** rodada em
`<pasta>\p7-<modo>-<data>.json`. Se a sessão cair, o que já rodou está nesses dois arquivos.

**Tempo estimado** (medido no rascunho sem Litestream, 07/11/2026: par a+b ≈ 2 min 25 s, rodada c ≈ 1 min 40 s; com
o R2 real soma o restore da geração em cada `a` e a espera da geração nova em cada `c`, até 20 s):

| Execução | Estimativa |
|---|---|
| `-Fumaca` (a1, b1, c1) | 5–7 min |
| padrão (`-Rodadas 5`, 15 rodadas) | 25–35 min |
| `-Tipos a -Rodadas 5` (5 rodadas `a`) | 5–7 min (em 07/11 cada `a` com R2 levou ~50 s, mais ~10 s da sonda e limpeza) |

**Interromper com segurança:** `Ctrl+C` no terminal do ensaio (os jobs do escritor e da sonda morrem com a sessão
do PowerShell; se o terminal for fechado, também). Depois, limpe **só pelo rótulo** — nunca por nome solto:

```powershell
docker ps -a -q --filter label=kiroo.ensaio=backup --filter name=kiroo-ensaio-p7 | ForEach-Object { docker rm -f $_ }
docker volume ls -q --filter label=kiroo.ensaio=backup --filter name=kiroo-ensaio-p7- | ForEach-Object { docker volume rm $_ }
```

(ou `-Passo 6`, que faz o mesmo e também limpa o resto do ensaio). `kiroo_kiroo-data` nunca é tocado. No bucket
nada é apagado: a réplica das rodadas fica em `ensaio/db` (apagar faz parte da pendência de limpeza de `ensaio/`).
Os arquivos `p7-*` da pasta ficam até o passo 6.

**Como a produção fica em andamento (sem custo de IA, sem mudar código):** modo simulado + `STUDIO_X264_PRESET=placebo`
(a montagem final leva ~80 s em vez de ~2 s) + piloto `automatico` pela API (`POST /api/productions/<pid>/autonomy`),
que aprova as revisões inconclusivas do revisor simulado. `STUDIO_POLL_INTERVAL_S` **não** serve: no modo simulado o
servidor fixa o intervalo de consulta em 0,8 s.

Rodadas (cada uma termina em PASS, FAIL ou NAO_VERIFICADO com o motivo; falha de execução = NAO_VERIFICADO):

- **a1..a5** — produção na montagem; cadastros sequenciais (`w7-<rodada>-<n>@ensaio.test`) contínuos e `/readyz` a cada
  100 ms; `docker stop -t 40`. FAIL se: tempo ≥ 40 s; código de saída ≠ 0; nenhum 503 antes da primeira sonda sem
  conexão; alguma linha não-JSON com `error` no log depois de `SIGTERM: parando` (Litestream); `run_state` ≠
  `interrupted` (lido do volume parado, conexão só leitura); **alguma escrita aceita (200) ausente** no volume parado
  ou no restore da **geração da rodada** no R2 — a mensagem lista os ids ausentes.
- **b1..b5** — `docker start` no mesmo volume: a produção retoma (evento `resumed`) e chega a `awaiting_final_review`
  com `run_state=idle`; as tentativas confirmadas antes do stop continuam iguais (id, tipo, cena, número, hash,
  criação, operação remota); nenhuma tentativa nova para cena+tipo que já estava `succeeded` ou `submitted`; montagem
  registrada uma vez. O resumo mostra `resumed = N` (quantos eventos `resumed`; FAIL se 0). Não mostra mais
  `run_state.resume_attempts` ("retomadas"): ele vai a 1 na retomada e **volta a 0** quando a produção retomada
  termina (`_mark_run(pid, "idle", reset_attempts=True)`), então era sempre 0 no fim da `b` — esperado, mas enganoso.
- **c1..c5** — `docker kill -s SIGKILL` (ímpares: com operação remota `submitted`; pares: na montagem). Ponto de
  sincronização: um cadastro confirmado (200) e, depois dele, leitura do banco confirmado por conexão sqlite somente
  leitura (inclui o `-wal`), numa transação, que precisa enxergar esse cadastro. FAIL se, depois do reinício, algo do
  snapshot mudou (diff impresso), se a escrita de sincronização sumiu, se uma etapa registrada se repetiu, se a
  produção não termina, ou se o Litestream não abriu geração nova.

**Litestream inativo = NAO_VERIFICADO, nunca 0 nem FAIL.** O Litestream só conta como ativo com as duas evidências:
geração legível (16 hex em `.studio.sqlite3-litestream/generation`) **e** linha do próprio Litestream no log (versão,
`initialized db` ou `replicating to`); o aviso `entrypoint: backup desligado` marca inativo. Inativo → "erros do
Litestream", "geração nova depois do SIGKILL" e "restore do R2" saem como NAO_VERIFICADO com o motivo (zero linhas de
erro sem Litestream não prova nada). FAIL só quando a asserção rodou e falhou. As demais asserções da rodada rodam
normalmente.

### WAL no fechamento x erro do Litestream

Em 07/11 (5 rodadas `a`), a2, a3 e a5 saíram com código 1 e
`ERROR msg="error closing db" error="checkpoint: mode=PASSIVE err=release read lock: context canceled"`, sem perda de
dado (restore 100%). **Hipótese em teste:** o erro acontece se e só se o WAL tiver **≥ 1000 páginas** quando o
Litestream fecha o banco.

Base no código do Litestream **v0.3.13**:

- `litestream.go`: `WALHeaderSize = 32`, `WALFrameHeaderSize = 24` e
  `calcWALSize(pageSize, n) = WALHeaderSize + (WALFrameHeaderSize + pageSize) * n`. Logo o limite é
  **32 + (page_size + 24) × 1000 bytes** = 4.120.032 bytes com páginas de 4096. A fórmula da hipótese está certa.
- `db.go`: `DefaultMinCheckpointPageN = 1000`. No `DB.Sync`,
  `} else if newWALSize >= calcWALSize(db.pageSize, db.MinCheckpointPageN) { checkpoint = true`. Aqui `newWALSize` é o
  fim do último commit do `-wal` real copiado para o WAL-sombra. Há outras duas regras que também disparam checkpoint:
  `MaxCheckpointPageN` (10000 páginas, modo RESTART) e `CheckpointInterval` (1 min sem checkpoint e WAL > 1 página).
- `DB.Close` cancela `db.ctx` antes do `Sync` final. Se esse `Sync` faz checkpoint, `execCheckpoint` reabre o read lock
  com `tx.ExecContext(db.ctx, …)`, que já está cancelado. O erro sai com o rótulo "release read lock" e o processo
  termina com `os.Exit(1)`.

**O que a rodada `a` mede, depois da parada:**

- `stop_utc`: o instante do `docker stop`, pelo relógio do Windows.
- `saida` e `finished_utc`, de `docker inspect --format {{.State.ExitCode}};{{.State.FinishedAt}}`. Só esses dois
  campos: nunca `Env` nem a `Config` inteira.
- **Sonda no volume parado**, antes de qualquer outra leitura dele (`scripts/ensaio_p7_wal.py`):
  - roda num container descartável com o rótulo do ensaio, volume montado `:ro`, sem variáveis de ambiente;
  - mede `db_bytes`, `wal_arquivo_bytes` e `page_size` (por `PRAGMA page_size`, conexão `mode=ro&immutable=1`,
    conferido com o cabeçalho do banco);
  - e o **WAL-sombra** do Litestream (`.studio.sqlite3-litestream/generations/<geração>/wal/<índice>.wal`, o último
    índice).
- `wal_log`: o fim do último `wal segment written` do log (offset + `sz`).
- `wal_conferencia`: quando a sombra e o log estão na mesma geração e no mesmo índice, devem dar o mesmo tamanho
  (`sombra = log`). Se divergirem, a fonte "sombra" precisa ser revista.
- `wal_bytes` / `wal_fonte`: a medida usada na hipótese, nesta ordem de preferência:
  1. **sombra** (é o que o `Sync` final copiou);
  2. **log**;
  3. **arquivo** `-wal`.
- `wal_paginas = (wal_bytes − 32) / (page_size + 24)` (parte inteira), `limite_paginas` (1000), `limite_bytes`,
  `previsto_erro` (wal_bytes ≥ limite_bytes), `erro_checkpoint` (a linha da hipótese entre os ERROR depois do SIGTERM),
  e `hipotese` = `consistente`, `contraexemplo` ou `indeterminada`.
- `linha_do_tempo`: o stop e, relativos ao `signal received` do Litestream, o aviso de SIGTERM do servidor,
  `marcadas como interrompidas`, o início e o fim da janela de assentamento (`settle_ini`, `settle_fim`: eventos
  `settle_start`/`settle_end` do log JSON do app), cada linha ERROR, `litestream shut down` e o `FinishedAt`.
- `settle_s` e `settle`: o valor de `STUDIO_SHUTDOWN_SETTLE_S` lido do log do app e quanto a janela durou
  (`desativado` com 0; `ausente` quando não há evento `settle_*`, por exemplo imagem antiga; `SEM settle_end` se o
  processo morreu no meio; `INTERROMPIDO` por segundo sinal). O stop vem do relógio do
  Windows e o resto do relógio do Docker; podem divergir alguns ms.

**Por que o `-wal` do volume não é a medida principal:** ao fechar a última conexão, o SQLite faz checkpoint e
**apaga** o `-wal`. O Litestream fecha a dele no fim do `DB.Close`, mesmo depois do erro. O teste
`tests/test_ensaio_p7_wal.py::test_sonda_wal_apagado_no_fechamento` mostra isso. Além disso, depois de um reinício do
WAL o arquivo guarda o tamanho máximo, não o conteúdo atual. Ele é registrado, mas só entra na hipótese se não houver
sombra nem log.

**Fim do log:** uma tabela com rodada, carga, wal_bytes, fonte, wal_pag, limite, saída, settle_s, erros_ls,
resultado e hipótese, seguida de
`hipotese consistente em N de M rodadas / contraexemplos: <rodada (motivo)> … / indeterminadas: …` e de
`settle_s: <valor> em <rodadas> / …` (repetido no resumo do passo 7). M exclui as
indeterminadas, que são listadas à parte. Uma rodada é indeterminada quando falta o WAL ou o page_size, ou quando o
Litestream está inativo. **Isto é só medição: a regra de erros não muda.** Qualquer linha ERROR do Litestream depois
do SIGTERM e qualquer código de saída ≠ 0 continuam sendo FAIL, mesmo numa rodada "consistente".

**`-Carga`:** só muda o ritmo dos cadastros do ensaio.

| Valor | Escritores | Pausa entre cadastros | Ritmo |
|---|---|---|---|
| `baixa` | 1 | 1 s | ~1 cadastro/s |
| `normal` | 1 | nenhuma | ~12 cadastros/s, como em 07/11 |
| `alta` | 3 em paralelo | nenhuma | 2–3× o normal, limitado pelo servidor |

Na `alta`, cada escritor numera os e-mails a partir de j×100000 (sem colisão) e os arquivos são juntados em
`p7-<rodada>-escritas.txt`.

WAL esperado. São estimativas, por isso a medição:

- **Base (07/11, carga normal):** ~15 MB de WAL enviados em ~25 s de drenagem com ~300 cadastros, ou seja ~0,6 MB/s e
  ~50 KB por cadastro (inclui as escritas da produção). O limite (4,12 MB) enche em ~7 s.
  - O Litestream tenta checkpoint a cada sync (1 s). Com o servidor ativo, o PASSIVE nem sempre reinicia o WAL.
  - No fechamento, o WAL ficou entre 2,55 MB e 4,89 MB: 619 a 1187 páginas, 3 de 5 acima do limite.
- **baixa:** ~50 KB/s. O checkpoint por tempo (1 min) reinicia o WAL, então espera-se **abaixo** do limite no
  fechamento (≲ 3 MB, ≲ 730 páginas). Previsão: **sem** o erro. Um erro aqui é contraexemplo.
- **normal:** como em 07/11, perto do limite. Resultado misto esperado.
- **alta:** ~1,2–1,8 MB/s. O WAL passa do limite em 2–3 s e o incremento final é maior. Espera-se **acima** do limite
  na maioria das rodadas. Previsão: com erro.
- O que decide é o tamanho medido no fechamento, não a carga. A carga só desloca a distribuição.

**Contraexemplos possíveis**, que a conclusão lista com o motivo:

- WAL ≥ limite e sem erro: o checkpoint final pode ter sido feito antes pelo monitor, com o contexto vivo.
- Erro com WAL < limite: a regra de 1 min (`CheckpointInterval`) ou uma medida errada.

Qualquer um deles derruba o "se e só se". Dados de 07/11 aplicados à regra (WAL pelo log): 5 de 5 consistentes
(a1 619, a4 814 páginas, sem erro; a2 1036, a3 1035, a5 1187 páginas, com erro).

### Janela de assentamento (variante a')

Implementada no servidor (`src/studio/shutdown.py`; detalhes, trechos do Litestream v0.3.13 e o orçamento em
`docs/RUNBOOK.md`, *Prazo de parada e janela de assentamento*). Depois da drenagem (HTTP fechado, produções marcadas,
requisições em andamento e thread do checkpoint periódico encerradas) o servidor espera `STUDIO_SHUTDOWN_SETTLE_S`
(padrão 3 s) antes de sair. Nesse tempo o Litestream, que espera o filho, faz o último sync e o checkpoint pendente
com o contexto ainda válido; quando o servidor sai, o `DB.Close` não tem checkpoint a fazer nem envio em voo.
`litestream.yml`, a versão do Litestream e a regra de erros do ensaio **não mudaram**.

**A imagem precisa ser reconstruída** (`src/` mudou) antes de medir:

```powershell
docker build --build-arg "GIT_COMMIT=$(git rev-parse HEAD)" -t kiroo:dados .
```

**Critério de verificação:** `-Passo 7 -Tipos a -Rodadas 5` nas cargas `baixa`, `normal` e `alta`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 7 -Tipos a -Rodadas 5 -Carga baixa
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 7 -Tipos a -Rodadas 5 -Carga normal
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 7 -Tipos a -Rodadas 5 -Carga alta
```

Alvo: **15 de 15** rodadas com `saida = 0`, `erros_litestream = 0`, `settle_s = 3` e, na linha do tempo,
`settle_ini` < `settle_fim` < `ls_shutdown`. Qualquer linha ERROR do Litestream continua FAIL. Se sobrar erro, olhe
na linha do tempo **onde** ele cai em relação a `settle_fim`:

- `error closing db … checkpoint` depois do `settle_fim`: o checkpoint não aconteceu dentro da janela. Confira o
  evento `drained` no `-log.txt` (`producoes ainda em chamada` > 0 = alguém escreveu durante a janela) e se houve
  `wal segment written` com índice novo durante a janela.
- `monitor error … RequestCanceled` logo depois do `settle_fim`: o último envio ao R2 ainda estava em voo; o envio
  levou mais que a folga da janela (veja `elapsed=` nos `wal segment written`). Repita com
  `$env:STUDIO_SHUTDOWN_SETTLE_S = '5'` no terminal (o passo 7 repassa a variável ao container pelo nome; o orçamento
  continua cabendo: 25 + 2 + 5 + 5 = 37 ≤ 40) antes de qualquer conclusão. A rodada mostra o `settle_s` efetivo.

### Escritas depois do SIGTERM

Cada cadastro confirmado (200) é registrado em `p7-<rodada>-aceitas.tsv` (n, e-mail de teste, horário UTC de envio e
de resposta, e duas classificações):

- **servidor** — a linha `E-mail para <e-mail>` do app vem antes ou depois de `SIGTERM: parando` no **mesmo log**
  (mesmo processo, sem comparar relógios): `antes` | `depois` | `sem_log`;
- **cliente** — resposta antes do sinal → `antes`; envio depois do sinal → `depois`; envio antes e resposta depois →
  `em_voo` (o cliente não sabe de que lado o servidor gravou).

Toda escrita aceita, de qualquer classe, precisa estar no volume parado **e** no restore do R2; qualquer ausente = FAIL
com o id. A rodada mostra `aceitas`, `aceitas_servidor`, `aceitas_cliente`, `ausentes_volume` e `restore`
(`N/N aceitas presentes`).

**Comportamento atual na drenagem (lido do código e confirmado no rascunho):** depois do SIGTERM o servidor recusa com
503 + `Retry-After: 30` só `POST /api/productions*` e `POST /api/demo` (jobs novos); **todo o resto continua
aceito** — inclusive cadastro, login e configurações — até o `httpd.shutdown()`, que só acontece quando
`app.shutdown()` termina (até `STUDIO_SHUTDOWN_GRACE_S`, 25 s). `/readyz` passa a 503 logo no sinal. No rascunho
(rodada a1) foram 8 cadastros aceitos antes e **288 depois** do SIGTERM, ao longo dos ~25 s de drenagem. Como o
Litestream só faz a última sincronização depois que o servidor sai, essas escritas entram na réplica — é o que a
rodada `a` confere.

**Proposta (não aplicada):** manter a aceitação de escritas curtas durante a drenagem (com uma instância só, recusar
não as manda para outro lugar: só vira erro para o usuário) e:

1. garantir o orçamento de tempo: `STUDIO_SHUTDOWN_GRACE_S` + fechamento do HTTP + última sincronização do Litestream
   < tempo de parada da plataforma (`docker stop -t 40` aqui; `kill_timeout` no deploy) — **aplicado** junto com a
   janela de assentamento: 25 + 2 + 3 + 5 = 35 s ≤ 40, validado na subida (`STUDIO_STOP_GRACE_S`);
2. encerrar o listener assim que não houver produção em andamento, em vez de esperar o prazo inteiro quando os laços
   já pararam (reduz a janela de escritas aceitas no fim);
3. responder `Connection: close` durante a drenagem, para o cliente não reutilizar conexão que vai cair;
4. se um dia houver mais de uma instância atrás de balanceador, aí sim recusar escritas novas (503 + `Retry-After`)
   assim que o `/readyz` virar 503.

Arquivos de cada rodada ficam na pasta do ensaio: `p7-<rodada>-escritas.txt` (na carga `alta` também
`-escritas-0..2.txt`), `-aceitas.tsv`, `-readyz.txt`,
`-log.txt`, `-snapshot.json`, `-final.json`, além de `p7-<modo>-<data>.log` e `.json` da execução. Nada é apagado no
bucket: a réplica das rodadas fica em `ensaio/db`.

## Passo 6 — Limpeza

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 6
```

Faz: remove os containers com o rótulo `kiroo.ensaio=backup`; remove o volume `kiroo-ensaio-dados` e os
`kiroo-ensaio-p7-*` que sobrarem do passo 7, só se tiverem o rótulo; avisa (sem apagar) se sobrar outro volume com o rótulo; compara data de criação e tamanho de
`kiroo_kiroo-data` com o anotado no passo 1; imprime o resumo dos resultados; apaga a pasta do ensaio só se
ela tiver o marcador. **Não apaga nada do bucket.**

**Esperado:** remoções com código 0, `kiroo_kiroo-data antes: ... | depois: ...` iguais, resumo, `PASS`.

**Se falhar:**
- `kiroo_kiroo-data SUMIU` ou tamanho diferente → pare tudo e investigue (`docker volume inspect kiroo_kiroo-data`). O ensaio nunca monta esse volume; uma diferença de tamanho pode vir do seu próprio Kiroo local rodando ao mesmo tempo — confira se `docker compose` estava no ar.
- copie o resumo **antes**: a pasta com `estado.json` é removida no fim.

Objetos que ficam no bucket (apague só se e quando quiser): `ensaio/db/...` (réplica do banco do ensaio) e
`ensaio/media/{current,archive,manifests}/...`.

---

## Resultados (preencha ao rodar)

| Passo | Resultado | Observação |
|---|---|---|
| 1 Pré-requisitos | NAO_VERIFICADO | |
| 2 Replicação | NAO_VERIFICADO | |
| 3 docker stop | NAO_VERIFICADO | tempo: — |
| 4 Mídia | NAO_VERIFICADO | |
| 5 Restore | NAO_VERIFICADO | banco — / mídia — / total — |
| 7 Desligamento sob carga | NAO_VERIFICADO | a: — / b: — / c: — |
| 6 Limpeza | NAO_VERIFICADO | |
