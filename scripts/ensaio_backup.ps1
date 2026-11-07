<#
.SYNOPSIS
  Ensaio de backup/restore do Kiroo (Litestream + rclone) contra o bucket kiroo-backups, prefixo ensaio/ (BACKUP_R2_PREFIX).
  Roteiro e criterios: docs/ENSAIO-BACKUP.md.

.DESCRIPTION
  PowerShell nativo (Windows PowerShell 5.1 ou pwsh). Nao usa Git Bash.
  Uso:   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 1
         (Passo = 1..6 ou "todos"; os passos 2..5 dependem do estado gravado pelos anteriores)
         -Passo 4 -Diagnostico: so UM envio rclone (copyto) de arquivo pequeno para ensaio/diag/, com
         -vv --dump headers (nunca --dump auth); cabecalhos de requisicao e resposta com credenciais mascaradas.

  Seguranca:
   * Credenciais: SO das variaveis do terminal. Vao aos containers com "-e NOME" (sem valor), nunca na linha de
     comando nem em arquivo. O script so imprime NOMES de variaveis, nunca valores.
   * Volume: so "kiroo-ensaio-dados", criado com rotulo kiroo.ensaio=backup. Qualquer outro nome e recusado.
     kiroo_kiroo-data nunca e montado nem alterado; so e consultado (docker volume inspect / docker system df).
   * Bucket: so LEITURA para conferir (rclone lsf/cat). Nada e apagado no bucket.
   * Containers temporarios usam --rm e --tmpfs /data (sem volume anonimo).
  Resultado por passo: PASS, FAIL ou NAO_VERIFICADO (o comando nem rodou). Gravado em <pasta do ensaio>\estado.json.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('1', '2', '3', '4', '5', '6', 'todos')][string]$Passo,
    [string]$Volume = 'kiroo-ensaio-dados',
    [string]$Pasta = (Join-Path $env:TEMP 'kiroo-ensaio'),
    [int]$Porta = 8799,
    [switch]$Diagnostico
)

Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'

# ------------------------------------------------------------------ constantes
$VOLUME_ENSAIO = 'kiroo-ensaio-dados'
$VOLUME_REAL = 'kiroo_kiroo-data'
$ROTULO = 'kiroo.ensaio=backup'
$IMAGEM = 'kiroo:dados'
$CONTAINER = 'kiroo-ensaio'
$BUCKET = 'kiroo-backups'
$PREFIXO = 'ensaio'                       # BACKUP_R2_PREFIX do ensaio: nunca mistura com staging/ real
$VARS_CRED = @('BACKUP_R2_ENDPOINT', 'BACKUP_R2_ACCESS_KEY_ID', 'BACKUP_R2_SECRET_ACCESS_KEY', 'BACKUP_BUCKET')
$MARCADOR = '.kiroo-ensaio-backup'          # arquivo que identifica a pasta do ensaio (limpeza so com ele)
$REPO = Split-Path -Parent $PSScriptRoot
$BASE = "http://127.0.0.1:$Porta"

if ($Volume -ne $VOLUME_ENSAIO) { throw "Volume recusado: '$Volume'. Este ensaio so usa '$VOLUME_ENSAIO'." }

# ------------------------------------------------------------------ utilitarios

function Say([string]$m) { Write-Host "[ensaio] $m" }

function Mask-Cred([string]$t) {
    # Mascara credenciais em texto vindo do rclone (--dump headers). Valores das variaveis, cabecalhos de
    # autenticacao e parametros de assinatura. Testado com valor ficticio em scripts	est_ensaio_backup.ps1.
    if (-not $t) { return $t }
    foreach ($v in @('BACKUP_R2_SECRET_ACCESS_KEY', 'BACKUP_R2_ACCESS_KEY_ID', 'BACKUP_R2_ENDPOINT')) {
        $x = [Environment]::GetEnvironmentVariable($v)
        if ($x -and $x.Length -ge 4) { $t = $t.Replace($x, "***$v***") }
    }
    $t = $t -replace '(?im)\b(Authorization|X-Amz-Security-Token|X-Amz-Credential|X-Amz-Signature|Cookie|Set-Cookie)\s*:.*$', '$1: ***'
    $t = $t -replace '(?i)((?:X-Amz-)?(?:Credential|Signature|Security-Token)=)[^\s,&"]+', '$1***'
    $t = $t -replace '(?i)\b[0-9a-f]{32}(\.r2\.cloudflarestorage\.com)', '***$1'   # id da conta no Host
    return $t
}

function Invoke-Native {
    # Roda um EXECUTAVEL (nunca uma funcao/alias de mesmo nome: "& 'docker'" resolvia a antiga funcao Docker e
    # recursava ate estourar a pilha). Devolve @{Code; Out} (stdout+stderr como texto). Nao lanca excecao por stderr (PS 5.1).
    # Se o executavel nao existe ou nao pode ser iniciado, lanca 'NAO_VERIFICADO: ...' (o comando nem rodou).
    param([string]$Exe, [string[]]$ArgList)
    $cmd = Get-Command -Name $Exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmd) { throw ('NAO_VERIFICADO: ' + "executavel '$Exe' nao encontrado no PATH") }
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $global:LASTEXITCODE = $null
    try { $out = & $cmd.Source @ArgList 2>&1 | ForEach-Object { "$_" } }
    catch { throw ('NAO_VERIFICADO: ' + "nao foi possivel executar '$($cmd.Source)': $($_.Exception.Message)") }
    finally { $ErrorActionPreference = $old }
    if ($null -eq $LASTEXITCODE) { throw ('NAO_VERIFICADO: ' + "'$Exe' nao devolveu codigo de saida") }
    return @{ Code = $LASTEXITCODE; Out = (@($out) -join "`n") }
}

function Invoke-Docker([string[]]$ArgList) { Invoke-Native 'docker' $ArgList }

function EnvArgs {
    # "-e NOME" sem valor: o docker copia o valor do ambiente deste processo. Nada vai para a linha de comando.
    $a = @()
    foreach ($v in @('STUDIO_ENV') + $VARS_CRED) { $a += @('-e', $v) }
    return $a + @('-e', "BACKUP_R2_PREFIX=$PREFIXO")   # prefixo nao e segredo
}

function Assert-VolumeEnsaio {
    $r = Invoke-Docker @('volume', 'inspect', '--format', '{{json .Labels}}', $VOLUME_ENSAIO)
    if ($r.Code -ne 0) { throw "volume $VOLUME_ENSAIO nao existe (rode o passo 1)" }
    if ($r.Out -notmatch '"kiroo\.ensaio"\s*:\s*"backup"') { throw "volume $VOLUME_ENSAIO existe SEM o rotulo $ROTULO; recusado" }
}

function Get-Estado {
    $f = Join-Path $Pasta 'estado.json'
    if (Test-Path $f) {
        $o = Get-Content $f -Raw | ConvertFrom-Json
        $h = @{}; foreach ($p in $o.PSObject.Properties) { $h[$p.Name] = $p.Value }
        if (-not $h.ContainsKey('resultados')) { $h['resultados'] = @{} }
        else { $r = @{}; foreach ($p in $h['resultados'].PSObject.Properties) { $r[$p.Name] = $p.Value }; $h['resultados'] = $r }
        return $h
    }
    return @{ resultados = @{} }
}

function Save-Estado($e) {
    if (-not (Test-Path (Join-Path $Pasta $MARCADOR))) { return }
    $e | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $Pasta 'estado.json') -Encoding UTF8
}

function Write-Sh([string]$Nome, [string[]]$Linhas) {
    # Scripts auxiliares para dentro do container (LF, sem BOM). Evita aspas na linha de comando do PS 5.1.
    $dir = Join-Path $Pasta 'sh'
    New-Item -ItemType Directory -Force $dir | Out-Null
    [IO.File]::WriteAllText((Join-Path $dir $Nome), (($Linhas -join "`n") + "`n"), (New-Object Text.UTF8Encoding $false))
}

function Prepare-Auxiliares {
    Write-Sh 'rclone_env.sh' @(
        'export RCLONE_CONFIG_KBK_TYPE=s3 RCLONE_CONFIG_KBK_PROVIDER=Cloudflare RCLONE_CONFIG_KBK_NO_CHECK_BUCKET=true',
        'export RCLONE_CONFIG_KBK_ENDPOINT="$BACKUP_R2_ENDPOINT"',
        'export RCLONE_CONFIG_KBK_ACCESS_KEY_ID="$BACKUP_R2_ACCESS_KEY_ID"',
        'export RCLONE_CONFIG_KBK_SECRET_ACCESS_KEY="$BACKUP_R2_SECRET_ACCESS_KEY"')
    # so LISTA: caminhos relativos ao prefixo pedido
    Write-Sh 'lista.sh' @('set -eu', '. /ensaio/sh/rclone_env.sh', 'rclone lsf -R --files-only "KBK:$BACKUP_BUCKET/$1"')
    # so LE um objeto
    Write-Sh 'le.sh' @('set -eu', '. /ensaio/sh/rclone_env.sh', 'rclone cat "KBK:$BACKUP_BUCKET/$1"')
    Write-Sh 'conta_email.py' @(
        'import sqlite3, sys',
        'con = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True)',
        'print(con.execute("SELECT COUNT(*) FROM users WHERE email=?", (sys.argv[2],)).fetchone()[0])')
    Write-Sh 'prepara_midia.sh' @(
        'set -eu',
        '# pastas de dado do usuario vazias fariam o backup_media.sh recusar (codigo 3); no ensaio recebem um marcador',
        'for d in productions uploads workspaces music training; do',
        '  if [ -d /data/$d ] && [ -z "$(ls -A /data/$d)" ]; then echo ensaio > /data/$d/.ensaio-placeholder; fi',
        'done',
        'printf %s "$1" > /data/productions/ensaio-marcador.txt',
        'cat /data/productions/ensaio-marcador.txt; echo')
}

function Run-Temp {
    # container descartavel com rotulo, --rm, --tmpfs /data (sem volume anonimo), pasta do ensaio em /ensaio
    param([string[]]$Extra, [string]$Entrypoint, [string[]]$Cmd)
    $a = @('run', '--rm', '--label', $ROTULO, '--tmpfs', '/data') + (EnvArgs) + @('-v', "${Pasta}:/ensaio") + $Extra + @('--entrypoint', $Entrypoint, $IMAGEM) + $Cmd
    Invoke-Docker $a
}

function Run-NoVolume {
    # container descartavel com o volume DO ENSAIO em /data
    param([string]$Entrypoint, [string[]]$Cmd)
    Assert-VolumeEnsaio
    $a = @('run', '--rm', '--label', $ROTULO, '-e', 'STUDIO_DATA_DIR=/data') + (EnvArgs) + @('-v', "${VOLUME_ENSAIO}:/data", '-v', "${Pasta}:/ensaio", '--entrypoint', $Entrypoint, $IMAGEM) + $Cmd
    Invoke-Docker $a
}

function Lista-Bucket([string]$Sub) {
    $r = Run-Temp @() 'sh' @('/ensaio/sh/lista.sh', $Sub)
    if ($r.Code -ne 0) { throw "listagem de $Sub falhou (codigo $($r.Code)): $($r.Out)" }
    return @($r.Out -split "`n" | Where-Object { $_.Trim() -ne '' })
}

function Restore-Container([string]$Dest, [string[]]$Opts) {
    # scripts/restore.sh da imagem, com a configuracao da propria imagem (/etc/litestream.yml). So LE do bucket.
    $extra = @('-e', 'STUDIO_DATA_DIR=/data')
    Run-Temp $extra 'bash' (@('/app/scripts/restore.sh', '--dest', "/ensaio/$Dest") + $Opts)
}

function Contagens([string]$DataDirNoContainer, [switch]$Vivo) {
    if ($Vivo) { $r = Invoke-Docker @('exec', $CONTAINER, 'python', '/app/scripts/verify_restore.py', '--data-dir', $DataDirNoContainer, '--json') }
    else { $r = Run-Temp @() 'python' @('/app/scripts/verify_restore.py', '--data-dir', $DataDirNoContainer, '--json') }
    $j = $null
    try { $j = $r.Out.Substring($r.Out.IndexOf('{')) | ConvertFrom-Json } catch { throw "verify_restore sem JSON (codigo $($r.Code)): $($r.Out)" }
    $h = [ordered]@{}; foreach ($p in $j.counts.PSObject.Properties) { $h[$p.Name] = [int]$p.Value }
    return $h
}

function Fmt($h) { ($h.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ' ' }

function Wait-Ready([int]$Seg = 90) {
    $fim = (Get-Date).AddSeconds($Seg)
    while ((Get-Date) -lt $fim) {
        try { $r = Invoke-WebRequest -UseBasicParsing -Uri "$BASE/readyz" -TimeoutSec 3; if ($r.StatusCode -eq 200) { return $true } } catch { }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

function Nova-Senha { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ }) }

function Signup([string]$Email) {
    # conta de TESTE no container do ensaio (localhost). A senha e aleatoria, nunca impressa nem gravada.
    $s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $body = @{ email = $Email; password = (Nova-Senha); name = 'Ensaio Backup' } | ConvertTo-Json
    Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$BASE/api/auth/signup" -WebSession $s -ContentType 'application/json' `
        -Headers @{ 'X-Studio-Client' = 'game' } -Body $body | Out-Null
    return $s
}

function Snapshot-Real {
    # SO consulta: existencia, data de criacao e tamanho (docker system df -v). Nunca monta o volume real.
    $i = Invoke-Docker @('volume', 'inspect', '--format', '{{.CreatedAt}}', $VOLUME_REAL)
    if ($i.Code -ne 0) { return $null }
    $df = Invoke-Docker @('system', 'df', '-v')
    $tam = $null
    foreach ($l in ($df.Out -split "`n")) { if ($l -match ('^' + [regex]::Escape($VOLUME_REAL) + '\s+\d+\s+(\S+)')) { $tam = $Matches[1] } }
    return @{ criado = $i.Out.Trim(); tamanho = $tam }
}

# ------------------------------------------------------------------ passos
function Passo1($e) {
    Say 'Passo 1: pre-requisitos'
    $ok = $true
    if ($env:STUDIO_ENV -ne 'staging') { Say "  STUDIO_ENV deve ser 'staging' (atual: '$env:STUDIO_ENV')"; $ok = $false } else { Say '  STUDIO_ENV=staging' }
    foreach ($v in $VARS_CRED) {
        $tem = -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($v))
        Say ("  {0}: {1}" -f $v, $(if ($tem) { 'presente' } else { 'AUSENTE' }))
        if (-not $tem) { $ok = $false }
    }
    if ($env:BACKUP_BUCKET -and $env:BACKUP_BUCKET -ne $BUCKET) { Say "  BACKUP_BUCKET deve ser '$BUCKET'"; $ok = $false }
    if (-not $ok) { throw ('NAO_VERIFICADO: ' + 'variaveis ausentes/erradas: defina-as no terminal e rode de novo') }
    $d = Invoke-Docker @('version', '--format', '{{.Server.Version}}')
    if ($d.Code -ne 0) { throw ('NAO_VERIFICADO: ' + "docker indisponivel: $($d.Out)") }
    $img = Invoke-Docker @('image', 'inspect', '--format', '{{.Id}}', $IMAGEM)
    if ($img.Code -ne 0) { throw ('NAO_VERIFICADO: ' + "imagem $IMAGEM nao encontrada") }
    Say "  docker $($d.Out.Trim()); imagem $IMAGEM ok"
    # a imagem precisa ter a correcao (litestream.yml com BACKUP_R2_PREFIX e restore.sh com LITESTREAM_CONFIG);
    # imagem antiga replicaria em staging/ e o restore.sh nao acharia a configuracao.
    $g1 = Invoke-Docker @('run', '--rm', '--network', 'none', '--tmpfs', '/data', '--entrypoint', 'grep', $IMAGEM, '-c', 'BACKUP_R2_PREFIX', '/etc/litestream.yml', '/app/scripts/restore.sh', '/usr/local/bin/kiroo-entrypoint')
    if ($g1.Out -match ':0(\s|$)' -or $g1.Code -gt 1) { throw ('NAO_VERIFICADO: ' + "imagem $IMAGEM sem suporte a BACKUP_R2_PREFIX (reconstrua a partir de deploy/dados atual): $($g1.Out)") }

    # pasta do ensaio (com marcador)
    if ((Test-Path $Pasta) -and -not (Test-Path (Join-Path $Pasta $MARCADOR)) -and (Get-ChildItem $Pasta -Force | Select-Object -First 1)) {
        throw "pasta $Pasta existe, nao e do ensaio (sem $MARCADOR); escolha outra com -Pasta"
    }
    New-Item -ItemType Directory -Force $Pasta | Out-Null
    Set-Content -Path (Join-Path $Pasta $MARCADOR) -Value 'pasta do ensaio de backup; pode ser apagada pelo passo 6'
    Prepare-Auxiliares

    # volume descartavel com rotulo
    $v = Invoke-Docker @('volume', 'inspect', '--format', '{{json .Labels}}', $VOLUME_ENSAIO)
    if ($v.Code -eq 0) {
        Assert-VolumeEnsaio
        throw "volume $VOLUME_ENSAIO ja existe (de um ensaio anterior). Rode o passo 6 e depois o 1 de novo."
    }
    $c = Invoke-Docker @('volume', 'create', '--label', $ROTULO, $VOLUME_ENSAIO)
    if ($c.Code -ne 0) { throw "volume create falhou: $($c.Out)" }
    Assert-VolumeEnsaio
    Say "  volume $VOLUME_ENSAIO criado com rotulo $ROTULO"

    # bucket: acesso de leitura e prefixo vazio
    $db = @(Lista-Bucket "$PREFIXO/db")
    $md = @(Lista-Bucket "$PREFIXO/media")
    Say "  bucket $BUCKET acessivel; objetos ja existentes: $PREFIXO/db=$($db.Count) $PREFIXO/media=$($md.Count)"
    # o prefixo e fixo e exclusivo do ensaio: so pode estar vazio ou ter sobras de ensaios anteriores.
    # As conferencias usam a geracao mais recente (Litestream) e so archive/ posterior ao inicio do passo 4.
    if (($db.Count + $md.Count) -gt 0) { Say "  $PREFIXO/ tem sobras de ensaio anterior (aceito: prefixo exclusivo do ensaio)" }
    $e['real_antes'] = Snapshot-Real
    if ($e['real_antes']) { Say "  $VOLUME_REAL existe (criado $($e['real_antes'].criado), tamanho $($e['real_antes'].tamanho)); nao sera tocado" }
    else { Say "  $VOLUME_REAL nao existe neste Docker" }
    $e['db_objs_inicio'] = $db.Count
    return 'PASS'
}

function Passo2($e) {
    Say 'Passo 2: replicacao'
    Assert-VolumeEnsaio
    $a = @('run', '-d', '--name', $CONTAINER, '--label', $ROTULO, '-p', "127.0.0.1:${Porta}:8765", '-v', "${VOLUME_ENSAIO}:/data",
        '-e', 'STUDIO_SIGNUP=open', '-e', "STUDIO_ALLOWED_HOSTS=127.0.0.1:$Porta", '-e', 'STUDIO_MODE=simulated') + (EnvArgs) + @($IMAGEM)
    $r = Invoke-Docker $a
    if ($r.Code -ne 0) { throw "docker run falhou: $($r.Out)" }
    if (-not (Wait-Ready 120)) { throw "/readyz nao ficou 200 em 120 s. Logs: $((Invoke-Docker @('logs', '--tail', '40', $CONTAINER)).Out)" }
    Say '  container no ar (/readyz 200)'

    $email = "ensaio-$(Get-Date -Format yyyyMMddHHmmss)@ensaio.test"
    $s = Signup $email
    $me = Invoke-WebRequest -UseBasicParsing -Uri "$BASE/api/me" -WebSession $s | Select-Object -ExpandProperty Content | ConvertFrom-Json
    $pids = @()
    foreach ($n in 1..2) {
        $p = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$BASE/api/demo" -WebSession $s -ContentType 'application/json' `
            -Headers @{ 'X-Studio-Token' = $me.csrf } -Body '{"budget": 5}' | Select-Object -ExpandProperty Content | ConvertFrom-Json
        $pids += $p.pid
    }
    $e['conta'] = $email; $e['producoes'] = $pids
    Say "  conta de teste $email; producoes simuladas: $($pids -join ', ')"

    # espera o banco parar de mudar (producoes simuladas terminando), no maximo 5 min
    $ant = $null; $fim = (Get-Date).AddMinutes(5)
    while ((Get-Date) -lt $fim) {
        $c = Contagens '/data' -Vivo
        if ($ant -and (Fmt $c) -eq (Fmt $ant)) { break }
        $ant = $c; Start-Sleep -Seconds 15
    }
    Say "  banco vivo:       $(Fmt $ant)"
    Start-Sleep -Seconds 10   # sync-interval do Litestream = 1 s; folga
    $objs = @(Lista-Bucket "$PREFIXO/db")
    Say "  objetos em $PREFIXO/db: $($objs.Count)"
    $objs | Select-Object -First 15 | ForEach-Object { Say "    $_" }
    $dest = "restore-p2-$(Get-Date -Format HHmmss)"
    $rr = Restore-Container $dest @('--db-only')
    $rot = switch ($rr.Code) { 0 { 'ok' } 5 { 'midia incompleta, esperado com --db-only' } default { 'falha' } }
    Say "  restore.sh --db-only codigo $($rr.Code) ($rot)"
    if ($rr.Code -ne 0 -and $rr.Code -ne 5) { throw "restore falhou: $($rr.Out)" }   # 5 = midia ausente (esperado com --db-only)
    $cr = Contagens "/ensaio/$dest"
    Say "  restauracao:      $(Fmt $cr)"
    if ($objs.Count -eq 0) { return 'FAIL' }
    if ((Fmt $cr) -ne (Fmt $ant)) { Say '  contagens DIFERENTES'; return 'FAIL' }
    return 'PASS'
}

function Passo3($e) {
    Say 'Passo 3: docker stop -t 40'
    $st = Invoke-Docker @('inspect', '--format', '{{.State.Running}}', $CONTAINER)
    if ($st.Out.Trim() -ne 'true') { throw ('NAO_VERIFICADO: ' + "container $CONTAINER nao esta rodando (rode o passo 2)") }
    # ultima escrita: uma conta nova, imediatamente antes do stop
    $ultima = "ultima-$(Get-Date -Format yyyyMMddHHmmssfff)@ensaio.test"
    Signup $ultima | Out-Null
    $e['ultima_escrita'] = $ultima
    Say "  ultima escrita antes do stop: conta $ultima"

    $job = Start-Job -ArgumentList $BASE -ScriptBlock {
        param($b) $res = @(); $fim = (Get-Date).AddSeconds(50); $falhas = 0
        while ((Get-Date) -lt $fim -and $falhas -lt 5) {
            try { $r = Invoke-WebRequest -UseBasicParsing -Uri "$b/readyz" -TimeoutSec 2; $res += "$($r.StatusCode)"; $falhas = 0 }
            catch { if ($_.Exception.Response) { $res += [string][int]$_.Exception.Response.StatusCode } else { $res += 'sem_conexao'; $falhas++ } }
            Start-Sleep -Milliseconds 100
        }
        $res
    }
    Start-Sleep -Milliseconds 500
    $t0 = Get-Date
    $r = Invoke-Docker @('stop', '-t', '40', $CONTAINER)
    $dur = ((Get-Date) - $t0).TotalSeconds
    $sondas = @(Receive-Job $job -Wait -AutoRemoveJob)
    $exit = (Invoke-Docker @('inspect', '--format', '{{.State.ExitCode}}', $CONTAINER)).Out.Trim()
    Say ("  docker stop levou {0:N1} s (codigo do comando {1}); codigo de saida do container: {2}" -f $dur, $r.Code, $exit)
    $viu503 = $sondas -contains '503'
    Say "  /readyz durante a parada: $(($sondas | Group-Object | ForEach-Object { "$($_.Name)x$($_.Count)" }) -join ' ')"
    $logs = (Invoke-Docker @('logs', '--timestamps', $CONTAINER)).Out -split "`n"
    $rel = $logs | Where-Object { $_ -match 'SIGTERM|desligamento|drenand|interromp|readyz|litestream|sync|replica|snapshot|exit|signal' } | Select-Object -Last 25
    Say '  linhas relevantes do log:'; $rel | ForEach-Object { Say "    $_" }
    Set-Content -Path (Join-Path $Pasta 'passo3-log.txt') -Value $logs

    $dest = "restore-p3-$(Get-Date -Format HHmmss)"
    $rr = Restore-Container $dest @('--db-only')
    if ($rr.Code -ne 0 -and $rr.Code -ne 5) { throw "restore falhou: $($rr.Out)" }
    $q = Run-Temp @() 'python' @('/ensaio/sh/conta_email.py', "/ensaio/$dest/studio.sqlite3", $ultima)
    $achou = $q.Out.Trim() -eq '1'
    Say "  restore depois do stop contem a ultima escrita: $achou"
    $e['stop_s'] = [math]::Round($dur, 1)
    if (-not $viu503) { Say '  AVISO: nenhum 503 capturado (sem producao em andamento o dreno pode ser rapido demais); sub-item NAO_VERIFICADO' }
    if ($achou -and $exit -eq '0' -and $dur -lt 40) { return 'PASS' }
    return 'FAIL'
}

function Show-Backup([string]$Nome, $r) {
    # Codigos do backup_media.sh: 0 ok | 1 falha do rclone | 2 config | 3 origem vazia | 4 outra execucao.
    $sig = switch ($r.Code) { 0 { 'ok' } 1 { 'FALHA do rclone' } 2 { 'uso/config invalida' } 3 { 'recusado: origem vazia' } 4 { 'outra execucao em andamento' } default { 'codigo inesperado' } }
    Say "  ${Nome}: codigo $($r.Code) ($sig)"
    $txt = Mask-Cred $r.Out
    $res = @($txt -split "`n" | Where-Object { $_ -match 'resumo:' }) | Select-Object -Last 1
    if ($res -and $res -match 'enviados=(\d+) objetos.*objetos=(\d+) bytes=(\d+); manifesto: (.*)$') {
        Say ("    objetos enviados: {0}; origem: {1} objetos, {2:N0} bytes ({3:N1} MB); manifesto: {4}" -f $Matches[1], $Matches[2], [int64]$Matches[3], ([int64]$Matches[3] / 1MB), $Matches[4])
    } else { Say '    (sem linha de resumo do backup_media.sh)' }
    if ($r.Code -ne 0) {
        $txt -split "`n" | Where-Object { $_ -match 'ERRO|FALHOU|501|Failed|nada foi apagado' } | Select-Object -Last 12 | ForEach-Object { Say "    $_" }
    }
    return ($r.Code -eq 0)
}

function Passo4Diag($e) {
    Say 'Passo 4 -Diagnostico: um envio rclone copyto com -vv --dump headers (sem --dump auth)'
    Write-Sh 'diag.sh' @(
        'set -u',
        '. /ensaio/sh/rclone_env.sh',
        'f=/tmp/kiroo-diag.txt; printf "diagnostico do ensaio %s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$f"',
        'dst="KBK:$BACKUP_BUCKET/$BACKUP_R2_PREFIX/diag/$(date -u +%Y-%m-%dT%H%M%SZ).txt"',
        'echo "diag: $(rclone version | head -n 1); arquivo de $(wc -c < "$f") bytes -> $dst"',
        '# so cabecalhos: --dump auth NUNCA (imprimiria a assinatura). Uma tentativa, para ver a primeira resposta.',
        'rclone copyto "$f" "$dst" -vv --dump headers --retries 1 --low-level-retries 1 2>&1',
        'rc=$?; echo "diag: rclone saiu com codigo $rc"; exit $rc')
    $r = Run-Temp @() 'sh' @('/ensaio/sh/diag.sh')
    $txt = Mask-Cred $r.Out
    $arq = Join-Path $Pasta "diag-$(Get-Date -Format yyyyMMdd-HHmmss).txt"
    Set-Content -Path $arq -Value $txt -Encoding UTF8
    $txt -split "`n" | ForEach-Object { Say "  $_" }
    Say "  saida (mascarada) gravada em $arq"
    if ($txt -match '\b501\b') { Say '  R2 respondeu 501: compare os cabecalhos da REQUISICAO acima (X-Amz-Acl, X-Amz-Checksum-*, Content-Encoding) com docs/BACKUP.md' }
    if ($r.Code -eq 0) { return 'PASS' }
    return 'FAIL'
}

function Passo4($e) {
    if ($Diagnostico) { return (Passo4Diag $e) }
    Say 'Passo 4: midia (backup_media.sh)'
    $inicio = (Get-Date).ToUniversalTime().AddSeconds(-2).ToString('yyyy-MM-ddTHHmmssZ')
    $st = Invoke-Docker @('inspect', '--format', '{{.State.Running}}', $CONTAINER)
    if ($st.Code -eq 0 -and $st.Out.Trim() -eq 'true') { throw ('NAO_VERIFICADO: ' + 'pare o container do ensaio antes (passo 3)') }
    $r = Run-NoVolume 'sh' @('/ensaio/sh/prepara_midia.sh', 'versao-1')
    if ($r.Code -ne 0) { throw "preparar midia falhou: $($r.Out)" }
    $bk = { param($x) Run-NoVolume 'bash' (@('/app/scripts/backup_media.sh') + $x) }
    $d = & $bk @('--dry-run')
    if (-not (Show-Backup '--dry-run' $d)) { return 'FAIL' }
    $a = & $bk @()
    if (-not (Show-Backup 'real #1' $a)) { Say '  se o erro for 501 no manifesto: rode -Passo 4 -Diagnostico'; return 'FAIL' }
    Start-Sleep -Seconds 2   # o carimbo de archive/<data> e por segundo
    $r = Run-NoVolume 'sh' @('/ensaio/sh/prepara_midia.sh', 'versao-2')
    $b = & $bk @()
    if (-not (Show-Backup 'real #2 (arquivo alterado)' $b)) { return 'FAIL' }
    $arch = Lista-Bucket "$PREFIXO/media/archive" | Where-Object { $_ -match 'productions/ensaio-marcador\.txt$' -and $_.Split('/')[0] -ge $inicio }
    Say "  em archive/: $($arch -join ', ')"
    if (-not $arch) { return 'FAIL' }
    $velho = Run-Temp @() 'sh' @('/ensaio/sh/le.sh', "$PREFIXO/media/archive/$(@($arch)[-1])")
    $atual = Run-Temp @() 'sh' @('/ensaio/sh/le.sh', "$PREFIXO/media/current/productions/ensaio-marcador.txt")
    Say "  archive contem '$($velho.Out.Trim())'; current contem '$($atual.Out.Trim())'"
    if ($velho.Out.Trim() -eq 'versao-1' -and $atual.Out.Trim() -eq 'versao-2') { return 'PASS' }
    return 'FAIL'
}

function Passo5($e) {
    Say 'Passo 5: restore cronometrado (pastas novas)'
    $ts = Get-Date -Format HHmmss
    $t = [Diagnostics.Stopwatch]::StartNew(); $a = Restore-Container "p5-banco-$ts" @('--db-only'); $tb = $t.Elapsed.TotalSeconds
    $t = [Diagnostics.Stopwatch]::StartNew(); $b = Restore-Container "p5-midia-$ts" @('--media-only'); $tm = $t.Elapsed.TotalSeconds
    $t = [Diagnostics.Stopwatch]::StartNew(); $c = Restore-Container "p5-total-$ts" @('--hash'); $tt = $t.Elapsed.TotalSeconds
    Say ("  tempos: banco {0:N1} s (codigo {1}) | midia {2:N1} s (codigo {3}) | total com --hash {4:N1} s (codigo {5})" -f $tb, $a.Code, $tm, $b.Code, $tt, $c.Code)
    $v = Run-Temp @() 'python' @('/app/scripts/verify_restore.py', '--data-dir', "/ensaio/p5-total-$ts", '--hash')
    $v.Out -split "`n" | ForEach-Object { Say "    $_" }
    $e['tempos'] = @{ banco_s = [math]::Round($tb, 1); midia_s = [math]::Round($tm, 1); total_s = [math]::Round($tt, 1) }
    if ($c.Code -eq 0 -and $v.Code -eq 0 -and ($a.Code -in 0, 5) -and $b.Code -eq 0) { return 'PASS' }
    return 'FAIL'
}

function Passo6($e) {
    Say 'Passo 6: limpeza (so o que tem o rotulo do ensaio)'
    $ids = (Invoke-Docker @('ps', '-a', '-q', '--filter', "label=$ROTULO")).Out -split "`n" | Where-Object { $_.Trim() }
    foreach ($id in $ids) { $r = Invoke-Docker @('rm', '-f', $id.Trim()); Say "  container $($id.Trim()) removido (codigo $($r.Code))" }
    $v = Invoke-Docker @('volume', 'inspect', '--format', '{{json .Labels}}', $VOLUME_ENSAIO)
    if ($v.Code -eq 0) {
        Assert-VolumeEnsaio
        $r = Invoke-Docker @('volume', 'rm', $VOLUME_ENSAIO); Say "  volume $VOLUME_ENSAIO removido (codigo $($r.Code))"
    } else { Say "  volume $VOLUME_ENSAIO ja nao existe" }
    $resto = (Invoke-Docker @('volume', 'ls', '-q', '--filter', "label=$ROTULO")).Out.Trim()
    if ($resto) { Say "  AINDA existem volumes com o rotulo: $resto (nao removidos automaticamente)" }
    $depois = Snapshot-Real
    $antes = $e['real_antes']
    $ok = $true
    if ($null -eq $antes) { Say "  $VOLUME_REAL nao existia no passo 1: comparacao NAO_VERIFICADA" }
    elseif ($null -eq $depois) { Say "  $VOLUME_REAL SUMIU!"; $ok = $false }
    else {
        Say "  $VOLUME_REAL antes: criado $($antes.criado), tamanho $($antes.tamanho) | depois: criado $($depois.criado), tamanho $($depois.tamanho)"
        if ($antes.criado -ne $depois.criado -or $antes.tamanho -ne $depois.tamanho) { $ok = $false }
    }
    Say '  resultados finais:'
    foreach ($k in ($e['resultados'].Keys | Sort-Object)) { Say "    passo $k = $($e['resultados'][$k])" }
    if (Test-Path (Join-Path $Pasta $MARCADOR)) { Remove-Item -Recurse -Force $Pasta; Say "  pasta $Pasta removida" }
    Say '  nada foi apagado no bucket (objetos em / continuam; apague so se quiser, a mao)'
    if ($resto) { $ok = $false }
    return $(if ($ok) { 'PASS' } else { 'FAIL' })
}

# ------------------------------------------------------------------ execucao
$passos = if ($Passo -eq 'todos') { '1', '2', '3', '4', '5', '6' } else { @($Passo) }
$estado = Get-Estado
foreach ($p in $passos) {
    if ($p -ne '1' -and -not (Test-Path (Join-Path $Pasta $MARCADOR))) {
        $res = 'NAO_VERIFICADO'; Say "Passo ${p}: pasta do ensaio ausente (rode o passo 1)"
    } else {
        try { $res = & "Passo$p" $estado }
        catch {
            $msg = $_.Exception.Message
            if ($msg -like 'NAO_VERIFICADO:*') { $res = 'NAO_VERIFICADO'; Say "  $msg" } else { $res = 'FAIL'; Say "  ERRO: $msg" }
        }
    }
    $estado['resultados'][$p] = $res
    Save-Estado $estado
    Write-Host ("RESULTADO passo {0}: {1}" -f $p, $res)
    if ($Passo -eq 'todos' -and $res -ne 'PASS' -and $p -ne '6') { Say 'parando a sequencia: corrija e rode o passo de novo (ou -Passo 6 para limpar)'; break }
}
