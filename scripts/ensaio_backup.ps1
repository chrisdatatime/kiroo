<#
.SYNOPSIS
  Ensaio de backup/restore do Kiroo (Litestream + rclone) contra o bucket kiroo-backups, prefixo ensaio/ (BACKUP_R2_PREFIX).
  Roteiro e criterios: docs/ENSAIO-BACKUP.md.

.DESCRIPTION
  PowerShell nativo (Windows PowerShell 5.1 ou pwsh). Nao usa Git Bash.
  Uso:   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensaio_backup.ps1 -Passo 1
         (Passo = 1..7 ou "todos" = 1..6; os passos 2..5 dependem do estado gravado pelos anteriores;
          o 7 (desligamento sob carga) so precisa do passo 1 e roda separado, antes do 6)
         -Passo 7 -Fumaca: 1 rodada de cada tipo (a1, b1, c1) para validar a mecanica com o R2 real;
         -Passo 7 -Rodadas N (1..5, padrao 5): N rodadas de cada tipo. A saida vai tambem para
         <pasta>\p7-<modo>-<data>.log e o resultado parcial (apos cada rodada) para p7-<modo>-<data>.json.
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
    [Parameter(Mandatory = $true)][ValidateSet('1', '2', '3', '4', '5', '6', '7', 'todos')][string]$Passo,
    [string]$Volume = 'kiroo-ensaio-dados',
    [string]$Pasta = (Join-Path $env:TEMP 'kiroo-ensaio'),
    [int]$Porta = 8799,
    [switch]$Diagnostico,
    [ValidateRange(1, 5)][int]$Rodadas = 5,   # passo 7: quantas rodadas de cada tipo (a/b e c)
    [switch]$Fumaca                          # passo 7: fumaca = 1 rodada de cada tipo (a1, b1, c1), ignora -Rodadas
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

$script:LOG_ARQ = $null   # passo 7: cada linha tambem vai para este arquivo (mascarada), para sobreviver a um corte de sessao

function Log-Arq([string]$m) {
    if (-not $script:LOG_ARQ) { return }
    try { Add-Content -Path $script:LOG_ARQ -Value ('{0} {1}' -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'), (Mask-Cred $m)) -Encoding UTF8 } catch { }
}

function Say([string]$m) { Write-Host "[ensaio] $m"; Log-Arq "[ensaio] $m" }

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
    # recursava ate estourar a pilha). Devolve @{Code; Out; Stdout; Stderr}: Out = stdout+stderr (para mensagens),
    # Stdout/Stderr separados. LEITURA DE CONTEUDO usa SO .Stdout (o rclone escreve NOTICE no stderr). Nao lanca excecao por stderr (PS 5.1).
    # Se o executavel nao existe ou nao pode ser iniciado, lanca 'NAO_VERIFICADO: ...' (o comando nem rodou).
    param([string]$Exe, [string[]]$ArgList)
    $cmd = Get-Command -Name $Exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmd) { throw ('NAO_VERIFICADO: ' + "executavel '$Exe' nao encontrado no PATH") }
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $global:LASTEXITCODE = $null
    $so = New-Object System.Collections.Generic.List[string]; $se = New-Object System.Collections.Generic.List[string]
    try {
        $out = & $cmd.Source @ArgList 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { $se.Add("$_") } else { $so.Add("$_") }
            "$_"
        }
    }
    catch { throw ('NAO_VERIFICADO: ' + "nao foi possivel executar '$($cmd.Source)': $($_.Exception.Message)") }
    finally { $ErrorActionPreference = $old }
    if ($null -eq $LASTEXITCODE) { throw ('NAO_VERIFICADO: ' + "'$Exe' nao devolveu codigo de saida") }
    return @{ Code = $LASTEXITCODE; Out = (@($out) -join "`n"); Stdout = (@($so) -join "`n"); Stderr = (@($se) -join "`n") }
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
    return @($r.Stdout -split "`n" | Where-Object { $_.Trim() -ne '' })     # so stdout: NOTICE do rclone nao vira "objeto"
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
    try { $j = $r.Stdout.Substring($r.Stdout.IndexOf('{')) | ConvertFrom-Json } catch { throw "verify_restore sem JSON (codigo $($r.Code)): $($r.Out)" }
    $h = [ordered]@{}; foreach ($p in $j.counts.PSObject.Properties) { $h[$p.Name] = [int]$p.Value }
    return $h
}

function Fmt($h) { ($h.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ' ' }

function Wait-Ready([int]$Seg = 90, [string]$Base = $BASE) {
    $fim = (Get-Date).AddSeconds($Seg)
    while ((Get-Date) -lt $fim) {
        try { $r = Invoke-WebRequest -UseBasicParsing -Uri "$Base/readyz" -TimeoutSec 3; if ($r.StatusCode -eq 200) { return $true } } catch { }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

function Nova-Senha { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ }) }

function Signup([string]$Email, [string]$Base = $BASE) {
    # conta de TESTE no container do ensaio (localhost). A senha e aleatoria, nunca impressa nem gravada.
    $s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $body = @{ email = $Email; password = (Nova-Senha); name = 'Ensaio Backup' } | ConvertTo-Json
    Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$Base/api/auth/signup" -WebSession $s -ContentType 'application/json' `
        -Headers @{ 'X-Studio-Client' = 'game' } -Body $body | Out-Null
    return $s
}

function Snapshot-Real {
    # SO consulta: existencia, data de criacao e tamanho (docker system df -v). Nunca monta o volume real.
    $i = Invoke-Docker @('volume', 'inspect', '--format', '{{.CreatedAt}}', $VOLUME_REAL)
    if ($i.Code -ne 0) { return $null }
    $df = Invoke-Docker @('system', 'df', '-v')
    $tam = $null
    foreach ($l in ($df.Stdout -split "`n")) { if ($l -match ('^' + [regex]::Escape($VOLUME_REAL) + '\s+\d+\s+(\S+)')) { $tam = $Matches[1] } }
    return @{ criado = $i.Stdout.Trim(); tamanho = $tam }
}

# ------------------------------------------------------------------ passos
function Check-Revisao {
    # So AVISA: commit gravado na imagem (rotulo org.opencontainers.image.revision) x HEAD da branch.
    # {{json .Config.Labels}} e lido aqui. NAO usar {{index .Config.Labels "org..."}}: o PowerShell 5.1 nao escapa aspas
    # internas ao chamar executaveis, o docker recebia {{index .Config.Labels org.opencontainers...}} e respondia
    # 'function "org" not defined' (codigo 64) -> o passo avisava "sem commit" mesmo com o rotulo gravado.
    $r = Invoke-Docker @('image', 'inspect', '--format', '{{json .Config.Labels}}', $IMAGEM)
    if ($r.Code -ne 0) { Say "  AVISO: commit da imagem $IMAGEM NAO_VERIFICADO (docker image inspect codigo $($r.Code): $($r.Stderr))"; return }
    $lab = $null
    $txt = $r.Stdout.Trim()
    if ($txt -and $txt -ne 'null') {
        try { $o = $txt | ConvertFrom-Json } catch { Say "  AVISO: rotulos da imagem $IMAGEM ilegiveis (NAO_VERIFICADO): $txt"; return }
        $prop = $o.PSObject.Properties['org.opencontainers.image.revision']
        if ($prop) { $lab = "$($prop.Value)".Trim() }
    }
    if (-not $lab -or $lab -eq 'desconhecido') {
        Say "  AVISO: imagem $IMAGEM sem commit gravado (construa com --build-arg GIT_COMMIT=...; ver docs/DOCKER.md)"; return
    }
    $head = $null
    try { $g = Invoke-Native 'git' @('-C', $REPO, 'rev-parse', 'HEAD'); if ($g.Code -eq 0) { $head = $g.Stdout.Trim() } } catch { }
    if (-not $head) { Say "  AVISO: commit da imagem $lab; HEAD da branch NAO_VERIFICADO (git indisponivel)"; return }
    if ($lab -eq $head) { Say "  imagem construida do HEAD atual ($($head.Substring(0, 7)))"; return }
    Say "  AVISO: imagem construida do commit $lab, diferente do HEAD $head"
    $d = $null
    try { $d = Invoke-Native 'git' @('-C', $REPO, 'diff', '--name-only', "$lab..$head", '--', 'scripts', 'docker', 'litestream.yml', 'Dockerfile', 'src') } catch { }
    if ($d -and $d.Code -eq 0 -and $d.Stdout.Trim()) {
        Say '  arquivos que entram na imagem mudaram desde entao (mudancas em scripts exigem RECONSTRUIR a imagem):'
        $d.Stdout -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { Say "    $_" }
    } else { Say '  mudancas em scripts exigem RECONSTRUIR a imagem; nao foi possivel listar o que mudou (commit fora da branch?)' }
}

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
    Say "  docker $($d.Stdout.Trim()); imagem $IMAGEM ok"
    Check-Revisao
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
    if ($st.Stdout.Trim() -ne 'true') { throw ('NAO_VERIFICADO: ' + "container $CONTAINER nao esta rodando (rode o passo 2)") }
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
    $exit = (Invoke-Docker @('inspect', '--format', '{{.State.ExitCode}}', $CONTAINER)).Stdout.Trim()
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
    $achou = $q.Stdout.Trim() -ceq '1'
    if ($q.Stderr) { Say "  (stderr da consulta: $($q.Stderr))" }
    Say "  restore depois do stop contem a ultima escrita: $achou"
    $e['stop_s'] = [math]::Round($dur, 1)
    if (-not $viu503) { Say '  AVISO: nenhum 503 capturado (sem producao em andamento o dreno pode ser rapido demais); sub-item NAO_VERIFICADO' }
    if ($achou -and $exit -eq '0' -and $dur -lt 40) { return 'PASS' }
    return 'FAIL'
}

function Assert-Vars {
    # As 5 variaveis que os passos com bucket precisam. Faltando -> NAO_VERIFICADO com a lista (so nomes).
    $falta = @(@('STUDIO_ENV') + $VARS_CRED | Where-Object { [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) })
    if ($falta.Count) { throw ('NAO_VERIFICADO: ' + "variaveis ausentes: $($falta -join ', ') (defina no terminal e rode de novo)") }
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
    if ($r.Code -eq 2) { $txt -split "`n" | Where-Object { $_ -match 'backup_media:' } | ForEach-Object { Say "    $_" } }
    elseif ($r.Code -ne 0) {
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
    Assert-Vars
    if ($Diagnostico) { return (Passo4Diag $e) }
    Say 'Passo 4: midia (backup_media.sh)'
    $inicio = (Get-Date).ToUniversalTime().AddSeconds(-2).ToString('yyyy-MM-ddTHHmmssZ')
    $st = Invoke-Docker @('inspect', '--format', '{{.State.Running}}', $CONTAINER)
    if ($st.Code -eq 0 -and $st.Stdout.Trim() -eq 'true') { throw ('NAO_VERIFICADO: ' + 'pare o container do ensaio antes (passo 3)') }
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
    # conteudo = SO stdout do rclone cat, comparado EXATAMENTE (o arquivo e gravado com printf %s, sem quebra de linha)
    foreach ($x in @(@('archive', $velho), @('current', $atual))) {
        if ($x[1].Code -ne 0) { Say "  leitura de $($x[0]) falhou (codigo $($x[1].Code)): $($x[1].Stderr)"; return 'FAIL' }
        if ($x[1].Stderr) { Say "  (stderr do rclone em $($x[0]), ignorado na comparacao: $($x[1].Stderr))" }
    }
    Say "  archive contem '$($velho.Stdout)'; current contem '$($atual.Stdout)'"
    if ($velho.Stdout -ceq 'versao-1' -and $atual.Stdout -ceq 'versao-2') { return 'PASS' }
    return 'FAIL'
}

function Passo5($e) {
    Say 'Passo 5: restore cronometrado (pastas novas)'
    Assert-Vars
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
    $ids = (Invoke-Docker @('ps', '-a', '-q', '--filter', "label=$ROTULO")).Stdout -split "`n" | Where-Object { $_.Trim() }
    foreach ($id in $ids) { $r = Invoke-Docker @('rm', '-f', $id.Trim()); Say "  container $($id.Trim()) removido (codigo $($r.Code))" }
    $v = Invoke-Docker @('volume', 'inspect', '--format', '{{json .Labels}}', $VOLUME_ENSAIO)
    if ($v.Code -eq 0) {
        Assert-VolumeEnsaio
        $r = Invoke-Docker @('volume', 'rm', $VOLUME_ENSAIO); Say "  volume $VOLUME_ENSAIO removido (codigo $($r.Code))"
    } else { Say "  volume $VOLUME_ENSAIO ja nao existe" }
    foreach ($v7 in ((Invoke-Docker @('volume', 'ls', '-q', '--filter', "label=$ROTULO")).Stdout -split "`n" | Where-Object { $_.Trim() -match '^kiroo-ensaio-p7-[ac][1-5]$' })) {
        $r = Invoke-Docker @('volume', 'rm', $v7.Trim()); Say "  volume $($v7.Trim()) (passo 7) removido (codigo $($r.Code))"
    }
    $resto = (Invoke-Docker @('volume', 'ls', '-q', '--filter', "label=$ROTULO")).Stdout.Trim()
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

# ------------------------------------------------------------------ passo 7: desligamento sob carga
# Producao SIMULADA (sem IA, sem custo) mantida em andamento SEM mudar codigo de producao:
#   * STUDIO_POLL_INTERVAL_S NAO serve: no modo simulado o servidor fixa o intervalo em 0,8 s (WebApp.orch_for).
#   * STUDIO_X264_PRESET=placebo (variavel existente): a montagem final do video simulado leva ~80 s em vez de ~2 s.
#   * piloto "automatico" (POST /api/productions/<pid>/autonomy, acao existente da API): aprova as revisoes
#     inconclusivas do revisor simulado e leva a producao sozinha ate awaiting_final_review.
# Cada rodada usa um volume PROPRIO (kiroo-ensaio-p7-a1..a5 / c1..c5, rotulo do ensaio), apagado ao fim da rodada.
# A replica vai para ensaio/db (mesmo prefixo do ensaio); o restore escolhe a GERACAO da rodada (-generation), so leitura.
$CONTAINER7 = 'kiroo-ensaio-p7'
$PORTA7 = $Porta + 1
$BASE7 = "http://127.0.0.1:$PORTA7"
. (Join-Path $PSScriptRoot 'ensaio_p7_lib.ps1')

function Assert-VolumeP7([string]$Nome) {
    if ($Nome -notmatch '^kiroo-ensaio-p7-[ac][1-5]$') { throw "volume recusado no passo 7: '$Nome'" }
    $r = Invoke-Docker @('volume', 'inspect', '--format', '{{json .Labels}}', $Nome)
    if ($r.Code -ne 0) { throw "volume $Nome nao existe" }
    if ($r.Out -notmatch '"kiroo\.ensaio"\s*:\s*"backup"') { throw "volume $Nome existe SEM o rotulo $ROTULO; recusado" }
}

function Remove-RodadaP7([string]$Vol) {
    Invoke-Docker @('rm', '-f', $CONTAINER7) | Out-Null
    $v = Invoke-Docker @('volume', 'inspect', '--format', '{{json .Labels}}', $Vol)
    if ($v.Code -eq 0) { Assert-VolumeP7 $Vol; Invoke-Docker @('volume', 'rm', $Vol) | Out-Null }
}

function New-RodadaP7([string]$Vol) {
    Remove-RodadaP7 $Vol
    $c = Invoke-Docker @('volume', 'create', '--label', $ROTULO, $Vol)
    if ($c.Code -ne 0) { throw ('NAO_VERIFICADO: ' + "volume create $Vol falhou: $($c.Out)") }
    Assert-VolumeP7 $Vol
    $a = @('run', '-d', '--name', $CONTAINER7, '--label', $ROTULO, '-p', "127.0.0.1:${PORTA7}:8765", '-v', "${Vol}:/data", '-v', "${Pasta}:/ensaio",
        '-e', 'STUDIO_SIGNUP=open', '-e', "STUDIO_ALLOWED_HOSTS=127.0.0.1:$PORTA7", '-e', 'STUDIO_MODE=simulated',
        '-e', 'STUDIO_X264_PRESET=placebo') + (EnvArgs) + @($IMAGEM)
    $r = Invoke-Docker $a
    if ($r.Code -ne 0) { throw ('NAO_VERIFICADO: ' + "docker run falhou: $($r.Out)") }
    if (-not (Wait-Ready 120 $BASE7)) { throw ('NAO_VERIFICADO: ' + "/readyz nao ficou 200. Logs: $((Invoke-Docker @('logs', '--tail', '30', $CONTAINER7)).Out)") }
}

function Estado-P7([string]$Pid7, [string]$Marcador = '') {
    # le o banco CONFIRMADO do container vivo: conexao sqlite (le o -wal), uma unica transacao de leitura
    $a = @('exec', $CONTAINER7, 'python', '/ensaio/sh/p7_q.py', 'estado', '/data/studio.sqlite3', $Pid7)
    if ($Marcador) { $a += $Marcador }
    $r = Invoke-Docker $a
    if ($r.Code -ne 0) { throw ('NAO_VERIFICADO: ' + "leitura do banco falhou (codigo $($r.Code)): $($r.Out)") }
    return ($r.Stdout | ConvertFrom-Json)
}

function Estado-VolumeParado([string]$Vol, [string]$Pid7) {
    # banco de um volume com o container PARADO: conexao somente leitura (nao faz checkpoint nem apaga o -wal)
    Assert-VolumeP7 $Vol
    $r = Invoke-Docker (@('run', '--rm', '--label', $ROTULO, '-v', "${Vol}:/data", '-v', "${Pasta}:/ensaio", '--entrypoint', 'python', $IMAGEM,
            '/ensaio/sh/p7_q.py', 'estado', '/data/studio.sqlite3', $Pid7))
    if ($r.Code -ne 0) { throw ('NAO_VERIFICADO: ' + "leitura do volume parado falhou (codigo $($r.Code)): $($r.Out)") }
    return ($r.Stdout | ConvertFrom-Json)
}

function Emails-P7([string]$Vol, [string]$Db, [string]$Prefixo) {
    # e-mails com o prefixo da rodada num banco: volume parado do passo 7 ($Vol) ou restore na pasta do ensaio ($Vol vazio).
    # Conexao sqlite somente leitura. Devolve a lista ou $null se a leitura falhou.
    if ($Vol) {
        Assert-VolumeP7 $Vol
        $r = Invoke-Docker @('run', '--rm', '--label', $ROTULO, '-v', "${Vol}:/data", '-v', "${Pasta}:/ensaio", '--entrypoint', 'python', $IMAGEM,
            '/ensaio/sh/p7_q.py', 'emails', $Db, $Prefixo)
    } else { $r = Run-Temp @() 'python' @('/ensaio/sh/p7_q.py', 'emails', $Db, $Prefixo) }
    if ($r.Code -ne 0) { Say "    leitura de e-mails falhou (codigo $($r.Code)): $($r.Out)"; return $null }
    # PS 5.1: o array JSON chega como UM objeto; atribuir e reenumerar
    try { $j = $r.Stdout | ConvertFrom-Json; return , @($j | ForEach-Object { "$_" }) } catch { Say "    leitura de e-mails sem JSON: $($r.Stdout)"; return $null }
}

function Geracao-P7 {
    $r = Invoke-Docker @('exec', $CONTAINER7, 'cat', '/data/.studio.sqlite3-litestream/generation')
    if ($r.Code -ne 0) { return $null }
    return $r.Stdout.Trim()
}

function Post-P7($S, [string]$Csrf, [string]$Rota, [string]$Corpo) {
    Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$BASE7$Rota" -WebSession $S -ContentType 'application/json' `
        -Headers @{ 'X-Studio-Token' = $Csrf } -Body $Corpo | Select-Object -ExpandProperty Content | ConvertFrom-Json
}

function Inicia-ProducaoP7([string]$Tag) {
    $s = Signup "p7-$Tag@ensaio.test" $BASE7
    $me = Invoke-WebRequest -UseBasicParsing -Uri "$BASE7/api/me" -WebSession $s | Select-Object -ExpandProperty Content | ConvertFrom-Json
    $p = Post-P7 $s $me.csrf '/api/demo' '{"budget": 5}'
    # a demo para na 1a aprovacao humana (run_state idle); o piloto automatico so pode ser ligado com o laco parado
    $fim = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $fim) { $st = Estado-P7 $p.pid; if ($st.run_state -eq 'idle') { break }; Start-Sleep -Milliseconds 500 }
    if ($st.run_state -ne 'idle') { throw ('NAO_VERIFICADO: ' + "demo nao parou na aprovacao em 60 s (status $($st.status))") }
    Post-P7 $s $me.csrf "/api/productions/$($p.pid)/autonomy" '{"mode": "automatico"}' | Out-Null
    return $p.pid
}

function Wait-StatusP7([string]$Pid7, [scriptblock]$Cond, [int]$Seg, [string]$Oque) {
    $fim = (Get-Date).AddSeconds($Seg)
    while ((Get-Date) -lt $fim) { $st = Estado-P7 $Pid7; if (& $Cond $st) { return $st }; Start-Sleep -Milliseconds 300 }
    throw ('NAO_VERIFICADO: ' + "$Oque nao aconteceu em $Seg s (status $($st.status), run_state $($st.run_state))")
}

function Termina-P7([string]$Pid7, [int]$Seg = 360) {
    Wait-StatusP7 $Pid7 { param($x) $x.status -eq 'awaiting_final_review' -and $x.run_state -eq 'idle' } $Seg 'producao retomada terminar (awaiting_final_review, run_state idle)'
}

function Show-Diff([string]$Titulo, [string[]]$Linhas) {
    if (-not $Linhas -or -not $Linhas.Count) { return }
    Say "    diff ${Titulo}:"; $Linhas | ForEach-Object { Say "      $_" }
}

function Checa-Retomada($Antes, $Depois, [ref]$Falhas, [string]$Rot) {
    $d = P7-Tentativas $Antes.attempts $Depois.attempts
    $r = P7-Repetidas $Antes.attempts $Depois.attempts
    if ($d.Count) { $Falhas.Value += "$Rot`: tentativas confirmadas mudaram ($($d.Count))"; Show-Diff 'tentativas (antes -> depois)' $d }
    if ($r.Count) { $Falhas.Value += "$Rot`: etapa registrada repetida ($($r.Count))"; Show-Diff 'etapas repetidas' $r }
    $ed = 0; if ($Depois.events.PSObject.Properties['edit_done']) { $ed = [int]$Depois.events.edit_done }
    if ($ed -ne 1) { $Falhas.Value += "$Rot`: montagem registrada $ed vez(es) (esperado 1)" }
}

function Rodada-P7A([int]$I, $Ret) {
    $vol = "kiroo-ensaio-p7-a$I"; $tag = "a$I-$(Get-Date -Format HHmmss)"
    $f = @(); $nv = @(); $info = [ordered]@{ rodada = "a$I" }
    try {
        New-RodadaP7 $vol
        $pid7 = Inicia-ProducaoP7 $tag
        $null = Wait-StatusP7 $pid7 { param($x) $x.status -eq 'editing' } 120 'producao chegar na montagem (editing)'
        Start-Sleep -Seconds 3
        $gen = Geracao-P7   # pode faltar (rascunho sem Litestream): decidido depois, com o log, em P7-LitestreamAtivo
        $antesStop = Estado-P7 $pid7
        $info.fase = $antesStop.status
        # escritor (cadastros sequenciais) e sonda /readyz a cada 100 ms, cada um gravando num arquivo
        $wf = Join-Path $Pasta "p7-$tag-escritas.txt"; $pf = Join-Path $Pasta "p7-$tag-readyz.txt"
        $jw = Start-Job -ArgumentList $BASE7, $tag, $wf -ScriptBlock {
            param($b, $t, $arq) $i = 0; $falhas = 0; $fim = (Get-Date).AddSeconds(90)
            while ((Get-Date) -lt $fim -and $falhas -lt 5) {
                $i++; $pw = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
                $body = @{ email = "w7-$t-$i@ensaio.test"; password = $pw; name = 'Ensaio P7' } | ConvertTo-Json
                $tEnv = [DateTime]::UtcNow.Ticks
                try { $r = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$b/api/auth/signup" -ContentType 'application/json' -Headers @{ 'X-Studio-Client' = 'game' } -Body $body -TimeoutSec 5; $c = "$($r.StatusCode)"; $falhas = 0 }
                catch { if ($_.Exception.Response) { $c = [string][int]$_.Exception.Response.StatusCode } else { $c = 'sem_conexao'; $falhas++ } }
                Add-Content -Path $arq -Value ("{0}`t{1}`t{2}`t{3}" -f $i, $c, [DateTime]::UtcNow.Ticks, $tEnv)   # n, codigo, resposta, envio
            } }
        $jp = Start-Job -ArgumentList $BASE7, $pf -ScriptBlock {
            param($b, $arq) $falhas = 0; $fim = (Get-Date).AddSeconds(90)
            while ((Get-Date) -lt $fim -and $falhas -lt 5) {
                try { $r = Invoke-WebRequest -UseBasicParsing -Uri "$b/readyz" -TimeoutSec 2; $c = "$($r.StatusCode)"; $falhas = 0 }
                catch { if ($_.Exception.Response) { $c = [string][int]$_.Exception.Response.StatusCode } else { $c = 'sem_conexao'; $falhas++ } }
                Add-Content -Path $arq -Value ("{0}`t{1}" -f [DateTime]::UtcNow.Ticks, $c)
                Start-Sleep -Milliseconds 100
            } }
        $fim = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $fim) {
            $okW = @((Get-Content $wf -ErrorAction SilentlyContinue) | Where-Object { ($_ -split "`t")[1] -eq '200' }).Count
            $okP = @(Get-Content $pf -ErrorAction SilentlyContinue).Count
            if ($okW -ge 3 -and $okP -ge 3) { break }; Start-Sleep -Milliseconds 200
        }
        if ($okW -lt 3) { throw ('NAO_VERIFICADO: ' + 'escritor nao confirmou escritas antes do stop') }
        $tSig = [DateTime]::UtcNow.Ticks
        $t0 = Get-Date
        $r = Invoke-Docker @('stop', '-t', '40', $CONTAINER7)
        $info.parada_s = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
        Wait-Job $jw, $jp -Timeout 30 | Out-Null; Stop-Job $jw, $jp -ErrorAction SilentlyContinue; Remove-Job $jw, $jp -Force
        if ($r.Code -ne 0) { throw ('NAO_VERIFICADO: ' + "docker stop falhou: $($r.Out)") }
        $info.saida = (Invoke-Docker @('inspect', '--format', '{{.State.ExitCode}}', $CONTAINER7)).Stdout.Trim()
        $rz = P7-Readyz @(Get-Content $pf)
        $info.readyz = $rz.sequencia; $info.readyz_503_antes_de_cair = $rz.antes_de_cair
        $logs = @((Invoke-Docker @('logs', '--timestamps', $CONTAINER7)).Out -split "`n")
        Set-Content -Path (Join-Path $Pasta "p7-$tag-log.txt") -Value $logs
        $ls = P7-LitestreamAtivo $logs $gen
        $info.litestream = if ($ls.ativo) { "ativo (geracao $gen)" } else { "NAO_VERIFICADO: $($ls.motivo)" }
        $el = P7-ErrosLitestream $logs $ls.ativo
        $info.erros_litestream = if (-not $ls.ativo) { 'NAO_VERIFICADO (Litestream inativo)' } elseif ($null -eq $el) { 'NAO_VERIFICADO (sem linha de SIGTERM no log)' } else { $el.Count }
        $parado = Estado-VolumeParado $vol $pid7
        $info.run_state = $parado.run_state
        $uc = P7-UltimaConfirmada @(Get-Content $wf) $tSig
        $info.ultima_confirmada_antes = $uc.antes; $info.confirmadas_depois_do_sigterm = $uc.confirmadas_depois_do_sinal
        # cada escrita confirmada (200): horario e se o servidor a aceitou antes ou depois do SIGTERM
        $esc = P7-Escritas @(Get-Content $wf) $tSig $logs "w7-$tag-"
        Set-Content -Path (Join-Path $Pasta "p7-$tag-aceitas.tsv") -Value (P7-Tsv $esc) -Encoding UTF8
        $info.aceitas = @($esc).Count
        $info.aceitas_servidor = 'antes={0} depois={1} sem_log={2}' -f @($esc | Where-Object { $_.servidor -eq 'antes' }).Count,
            @($esc | Where-Object { $_.servidor -eq 'depois' }).Count, @($esc | Where-Object { $_.servidor -eq 'sem_log' }).Count
        $info.aceitas_cliente = 'antes={0} em_voo={1} depois={2}' -f @($esc | Where-Object { $_.cliente -eq 'antes' }).Count,
            @($esc | Where-Object { $_.cliente -eq 'em_voo' }).Count, @($esc | Where-Object { $_.cliente -eq 'depois' }).Count
        # o volume parado precisa ter TODAS as aceitas (perda local, independe do Litestream)
        $loc = Emails-P7 $vol '/data/studio.sqlite3' "w7-$tag-"
        if ($null -eq $loc) { $nv += 'leitura das escritas no volume parado falhou' }
        else { $aus = P7-Ausentes $esc $loc; $info.ausentes_volume = $aus.Count; if ($aus.Count) { $f += "volume parado SEM $($aus.Count) escrita(s) aceita(s): $($aus -join ', ')" } }
        if (-not $ls.ativo) {
            $info.restore = 'NAO_VERIFICADO (Litestream inativo)'
            $nv += "restore do R2: NAO_VERIFICADO ($($ls.motivo))"
        } else {
            $dest = "p7-restore-$tag"
            $rr = Run-Temp @() 'sh' @('/ensaio/sh/p7_restore.sh', $gen, $dest)
            if ($rr.Code -ne 0) { $nv += "restore do R2 falhou (codigo $($rr.Code)): $(Mask-Cred $rr.Out)" }
            else {
                $rest = Emails-P7 '' "/ensaio/$dest/studio.sqlite3" "w7-$tag-"
                if ($null -eq $rest) { $nv += 'consulta ao restore falhou' }
                else {
                    $aus = P7-Ausentes $esc $rest; $info.ausentes_restore = $aus.Count
                    $info.restore = "$(@($esc).Count - $aus.Count)/$(@($esc).Count) aceitas presentes"
                    if ($aus.Count) { $f += "restore do R2 SEM $($aus.Count) escrita(s) aceita(s): $($aus -join ', ')" }
                    if (-not @($esc).Count) { $nv += 'nenhuma escrita aceita para conferir no restore' }
                }
            }
        }
        if ($info.saida -ne '0') { $f += "codigo de saida $($info.saida) (esperado 0)" }
        if ($info.parada_s -ge 40) { $f += "parada levou $($info.parada_s) s (>= 40: o docker matou)" }
        if (-not $rz.antes_de_cair) { $f += "/readyz nao respondeu 503 antes de cair ($($rz.sequencia))" }
        if (-not $ls.ativo) { $nv += 'erros do Litestream no desligamento: NAO_VERIFICADO (Litestream inativo)' }
        elseif ($null -eq $el) { $nv += 'linha de SIGTERM ausente no log: erros do Litestream nao contados' }
        elseif ($el.Count) { $f += "$($el.Count) linha(s) ERROR do Litestream no desligamento"; Show-Diff 'erros do Litestream' $el }
        if ($parado.run_state -ne 'interrupted') { $f += "run_state='$($parado.run_state)' (esperado interrupted)" }
        $Ret.Value = @{ vol = $vol; pid = $pid7; antes = $parado }
    } catch {
        $m = $_.Exception.Message
        $nv += $(if ($m -like 'NAO_VERIFICADO:*') { $m.Substring(16).Trim() } else { "falha de execucao: $m" })
    }
    $info.resultado = P7-Veredito $f $nv; $info.motivos = @($f + $nv)
    return $info
}

function Rodada-P7B([int]$I, $Ctx) {
    $f = @(); $nv = @(); $info = [ordered]@{ rodada = "b$I" }
    try {
        if (-not $Ctx) { throw ('NAO_VERIFICADO: ' + "rodada a$I nao deixou volume para reiniciar") }
        Assert-VolumeP7 $Ctx.vol
        $r = Invoke-Docker @('start', $CONTAINER7)
        if ($r.Code -ne 0 -or -not (Wait-Ready 120 $BASE7)) { throw ('NAO_VERIFICADO: ' + "reinicio falhou: $($r.Out)") }
        $fim = Termina-P7 $Ctx.pid
        $info.status = $fim.status; $info.retomadas = $fim.resume_attempts
        $res = 0; if ($fim.events.PSObject.Properties['resumed']) { $res = [int]$fim.events.resumed }
        if ($res -lt 1) { $f += 'nenhum evento resumed: a producao nao foi retomada pelo reinicio' }
        Checa-Retomada $Ctx.antes $fim ([ref]$f) "b$I"
    } catch {
        $m = $_.Exception.Message
        $nv += $(if ($m -like 'NAO_VERIFICADO:*') { $m.Substring(16).Trim() } else { "falha de execucao: $m" })
    }
    $info.resultado = P7-Veredito $f $nv; $info.motivos = @($f + $nv)
    return $info
}

function Rodada-P7C([int]$I) {
    $vol = "kiroo-ensaio-p7-c$I"; $tag = "c$I-$(Get-Date -Format HHmmss)"
    $f = @(); $nv = @(); $info = [ordered]@{ rodada = "c$I" }
    try {
        New-RodadaP7 $vol
        $pid7 = Inicia-ProducaoP7 $tag
        # rodadas impares: kill com operacao remota em andamento (cenas); pares: no meio da montagem final
        if ($I % 2) { $null = Wait-StatusP7 $pid7 { param($x) $x.status -eq 'producing' -and @($x.attempts | Where-Object { $_.status -eq 'submitted' }).Count -ge 1 } 60 'operacao remota em andamento' }
        else { $null = Wait-StatusP7 $pid7 { param($x) $x.status -eq 'editing' } 120 'producao chegar na montagem'; Start-Sleep -Seconds 3 }
        $gen0 = Geracao-P7   # pode faltar (rascunho sem Litestream): a assercao da geracao nova vira NAO_VERIFICADO
        # ponto de sincronizacao deterministico: uma escrita confirmada (HTTP 200 = COMMIT feito) e, depois dela, a leitura
        # do banco confirmado por conexao sqlite (inclui o -wal) numa unica transacao; o snapshot so vale se enxergar a escrita.
        $marcador = "k7-$tag@ensaio.test"
        Signup $marcador $BASE7 | Out-Null
        $snap = Estado-P7 $pid7 $marcador
        $r = Invoke-Docker @('kill', '-s', 'SIGKILL', $CONTAINER7)
        if ($r.Code -ne 0) { throw ('NAO_VERIFICADO: ' + "docker kill falhou: $($r.Out)") }
        if ([int]$snap.marker -ne 1) { throw ('NAO_VERIFICADO: ' + 'snapshot nao enxergou a escrita de sincronizacao') }
        $info.fase = $snap.status; $info.tentativas_no_snapshot = @($snap.attempts).Count
        $info.saida = (Invoke-Docker @('inspect', '--format', '{{.State.ExitCode}}', $CONTAINER7)).Stdout.Trim()
        Set-Content -Path (Join-Path $Pasta "p7-$tag-snapshot.json") -Value ($snap | ConvertTo-Json -Depth 6)
        $r = Invoke-Docker @('start', $CONTAINER7)
        if ($r.Code -ne 0 -or -not (Wait-Ready 120 $BASE7)) { throw ('NAO_VERIFICADO: ' + "reinicio apos kill falhou: $($r.Out)") }
        $pos = Estado-P7 $pid7 $marcador
        if ([int]$pos.marker -ne 1) { $f += "escrita confirmada antes do kill ($marcador) SUMIU" }
        $d0 = P7-Tentativas $snap.attempts $pos.attempts
        if ($d0.Count) { $f += "logo apos o reinicio, tentativas confirmadas mudaram ($($d0.Count))"; Show-Diff 'snapshot -> apos reinicio' $d0 }
        $gen1 = $null; $lim = (Get-Date).AddSeconds(20)
        while ((Get-Date) -lt $lim) { $gen1 = Geracao-P7; if ($gen1 -and $gen1 -ne $gen0) { break }; Start-Sleep -Milliseconds 500 }
        $info.geracao_antes = $gen0; $info.geracao_depois = $gen1
        $logsC = @((Invoke-Docker @('logs', '--timestamps', $CONTAINER7)).Out -split "`n")
        $ls = P7-LitestreamAtivo $logsC $gen0
        $info.litestream = if ($ls.ativo) { 'ativo' } else { "NAO_VERIFICADO: $($ls.motivo)" }
        $gn = P7-GeracaoNova $gen0 $gen1 $ls.ativo
        $info.geracao_nova = $gn.resultado
        if ($gn.resultado -eq 'FAIL') { $f += $gn.motivo } elseif ($gn.resultado -eq 'NAO_VERIFICADO') { $nv += $gn.motivo }
        $fim = Termina-P7 $pid7
        $info.status = $fim.status
        Set-Content -Path (Join-Path $Pasta "p7-$tag-final.json") -Value ($fim | ConvertTo-Json -Depth 6)
        Checa-Retomada $snap $fim ([ref]$f) "c$I"
    } catch {
        $m = $_.Exception.Message
        $nv += $(if ($m -like 'NAO_VERIFICADO:*') { $m.Substring(16).Trim() } else { "falha de execucao: $m" })
    }
    try { Remove-RodadaP7 $vol } catch { $nv += "limpeza da rodada falhou: $($_.Exception.Message)" }
    $info.resultado = P7-Veredito $f $nv; $info.motivos = @($f + $nv)
    return $info
}

function Prepare-P7 {
    Write-Sh 'p7_q.py' @(
        '# consultas do passo 7. Conexao sqlite SOMENTE LEITURA, uma transacao: le o banco confirmado (inclusive o -wal).',
        'import json, sqlite3, sys',
        'modo, db = sys.argv[1], sys.argv[2]',
        'con = sqlite3.connect("file:" + db + "?mode=ro", uri=True)',
        'con.row_factory = sqlite3.Row',
        'con.execute("BEGIN")',
        'if modo == "email":',
        '    print(con.execute("SELECT COUNT(*) FROM users WHERE email=?", (sys.argv[3],)).fetchone()[0]); sys.exit(0)',
        'if modo == "emails":   # todos os e-mails com o prefixo da rodada (lista JSON)',
        '    print(json.dumps([x[0] for x in con.execute("SELECT email FROM users WHERE email LIKE ?", (sys.argv[3] + "%",))])); sys.exit(0)',
        'pid = sys.argv[3]',
        'p = con.execute("SELECT status FROM productions WHERE id=?", (pid,)).fetchone()',
        'r = con.execute("SELECT state, resume_attempts FROM run_state WHERE production_id=?", (pid,)).fetchone()',
        'out = {"status": p["status"] if p else None, "run_state": r["state"] if r else None,',
        '       "resume_attempts": r["resume_attempts"] if r else None}',
        'out["attempts"] = [dict(x) for x in con.execute("SELECT id, kind, scene_idx, attempt_no, status, remote_op_id, input_hash,"',
        '    " created_at, superseded FROM attempts WHERE production_id=? ORDER BY created_at, id", (pid,))]',
        'out["events"] = {x[0]: x[1] for x in con.execute("SELECT type, COUNT(*) FROM events WHERE production_id=? GROUP BY type", (pid,))}',
        'if len(sys.argv) > 4:',
        '    out["marker"] = con.execute("SELECT COUNT(*) FROM users WHERE email=?", (sys.argv[4],)).fetchone()[0]',
        'con.rollback()',
        'print(json.dumps(out))')
    # restore de UMA geracao (a da rodada) para /ensaio/<dest>. So LE o bucket.
    Write-Sh 'p7_restore.sh' @(
        'set -eu',
        'export LITESTREAM_ACCESS_KEY_ID="$BACKUP_R2_ACCESS_KEY_ID" LITESTREAM_SECRET_ACCESS_KEY="$BACKUP_R2_SECRET_ACCESS_KEY"',
        'mkdir -p "/ensaio/$2"',
        'STUDIO_DATA_DIR=/data litestream restore -config /etc/litestream.yml -generation "$1" -o "/ensaio/$2/studio.sqlite3" /data/studio.sqlite3')
}

function Salva-ParcialP7([string]$Arq, $Todas) {
    # resultado acumulado depois de CADA rodada (sobrevive a um corte de sessao). So ids, codigos e motivos; sem credenciais.
    try { [IO.File]::WriteAllText($Arq, (Mask-Cred ((@($Todas) | ConvertTo-Json -Depth 6))), (New-Object Text.UTF8Encoding $false)) } catch { }
}

function Passo7($e) {
    $n = if ($Fumaca) { 1 } else { $Rodadas }
    $carimbo = Get-Date -Format 'yyyyMMdd-HHmmss'
    $modo = if ($Fumaca) { 'fumaca' } else { "rodadas$n" }
    $script:LOG_ARQ = Join-Path $Pasta "p7-$modo-$carimbo.log"
    $parcial = Join-Path $Pasta "p7-$modo-$carimbo.json"
    Say "Passo 7: desligamento sob carga (producao simulada, sem custo de IA); $(if ($Fumaca) { 'FUMACA: 1 rodada de cada tipo (a1, b1, c1)' } else { "$n rodada(s) de cada tipo" })"
    Say "  saida tambem em $($script:LOG_ARQ) e resultado parcial em $parcial"
    Assert-Vars
    $d = Invoke-Docker @('version', '--format', '{{.Server.Version}}')
    if ($d.Code -ne 0) { throw ('NAO_VERIFICADO: ' + "docker indisponivel: $($d.Out)") }
    Prepare-P7
    $todas = @()
    for ($i = 1; $i -le $n; $i++) {
        Say "  rodada a$i (docker stop -t 40 no meio da producao, com escritas)"
        $ctx = $null
        $ra = Rodada-P7A $i ([ref]$ctx)
        $ra.GetEnumerator() | Where-Object { $_.Key -notin 'motivos' } | ForEach-Object { Say "    $($_.Key) = $($_.Value)" }
        $ra.motivos | ForEach-Object { Say "    motivo: $_" }
        Say "  rodada b$i (reinicio no mesmo volume)"
        $rb = Rodada-P7B $i $ctx
        $rb.GetEnumerator() | Where-Object { $_.Key -notin 'motivos' } | ForEach-Object { Say "    $($_.Key) = $($_.Value)" }
        $rb.motivos | ForEach-Object { Say "    motivo: $_" }
        try { Remove-RodadaP7 "kiroo-ensaio-p7-a$i" } catch { Say "    limpeza falhou: $($_.Exception.Message)" }
        $todas += $ra, $rb
        Salva-ParcialP7 $parcial $todas
    }
    for ($i = 1; $i -le $n; $i++) {
        Say "  rodada c$i (SIGKILL no meio da producao)"
        $rc = Rodada-P7C $i
        $rc.GetEnumerator() | Where-Object { $_.Key -notin 'motivos' } | ForEach-Object { Say "    $($_.Key) = $($_.Value)" }
        $rc.motivos | ForEach-Object { Say "    motivo: $_" }
        $todas += $rc
        Salva-ParcialP7 $parcial $todas
    }
    $e['p7'] = $todas
    Say '  resumo do passo 7:'
    foreach ($g in @('a', 'b', 'c')) {
        $x = @($todas | Where-Object { $_.rodada -like "$g*" })
        Say ("    {0}: PASS={1} FAIL={2} NAO_VERIFICADO={3}" -f $g, @($x | Where-Object { $_.resultado -eq 'PASS' }).Count,
            @($x | Where-Object { $_.resultado -eq 'FAIL' }).Count, @($x | Where-Object { $_.resultado -eq 'NAO_VERIFICADO' }).Count)
    }
    foreach ($x in $todas) { if ($x.resultado -ne 'PASS') { Say "    $($x.rodada) $($x.resultado): $($x.motivos -join ' | ')" } }
    Say '  nada foi apagado no bucket (a replica das rodadas fica em ensaio/db)'
    return (P7-Veredito @($todas | Where-Object { $_.resultado -eq 'FAIL' } | ForEach-Object { $_.rodada }) @($todas | Where-Object { $_.resultado -eq 'NAO_VERIFICADO' } | ForEach-Object { $_.rodada }))
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
    Write-Host ("RESULTADO passo {0}: {1}" -f $p, $res); Log-Arq ("RESULTADO passo {0}: {1}" -f $p, $res)
    if ($Passo -eq 'todos' -and $res -ne 'PASS' -and $p -ne '6') { Say 'parando a sequencia: corrija e rode o passo de novo (ou -Passo 6 para limpar)'; break }
}
