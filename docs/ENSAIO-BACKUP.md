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

## Passo 6 — Limpeza

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 6
```

Faz: remove os containers com o rótulo `kiroo.ensaio=backup`; remove o volume `kiroo-ensaio-dados` só se tiver
o rótulo; avisa (sem apagar) se sobrar outro volume com o rótulo; compara data de criação e tamanho de
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
| 6 Limpeza | NAO_VERIFICADO | |
