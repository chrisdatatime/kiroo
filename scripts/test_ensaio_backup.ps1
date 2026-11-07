<#
.SYNOPSIS
  Regressao do passo 1 de scripts/ensaio_backup.ps1 SEM Docker real e SEM credenciais.
  Uso: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test_ensaio_backup.ps1
  Um "docker" falso (docker.cmd -> docker_stub.ps1) vai na frente do PATH; as variaveis recebem valores ficticios.
  Casos: caminho feliz (sem estouro de pilha), docker ausente, daemon fora, variaveis ausentes, falha de comando,
  excecao inesperada. Sai com codigo 0 se todos passarem.
#>
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'ensaio_backup.ps1'
$psExe = (Get-Command powershell -CommandType Application | Select-Object -First 1).Source
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("ensaio-teste-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$stubDir = Join-Path $tmp 'stub'
New-Item -ItemType Directory -Force $stubDir | Out-Null

# docker falso: registra os argumentos e responde conforme STUB_MODO. Estado do volume num arquivo.
Set-Content -Encoding ASCII (Join-Path $stubDir 'docker.cmd') "@`"$psExe`" -NoProfile -ExecutionPolicy Bypass -File `"%~dp0docker_stub.ps1`" %*`r`n@exit /b %ERRORLEVEL%"
Set-Content -Encoding ASCII (Join-Path $stubDir 'docker_stub.ps1') @'
$a = @($args); $modo = "$env:STUB_MODO"; $vol = Join-Path $env:STUB_DIR 'volume.criado'
Add-Content -Path (Join-Path $env:STUB_DIR 'chamadas.log') -Value ($a -join ' ')
$j = $a -join ' '
switch -Regex ($j) {
  '^version'                { if ($modo -eq 'daemon_fora') { [Console]::Error.WriteLine('Cannot connect to the Docker daemon'); exit 1 }; '27.0.0-stub'; exit 0 }
  '^image inspect'          { 'sha256:stub'; exit 0 }
  '^run .*--entrypoint grep' { '/etc/litestream.yml:2'; '/app/scripts/restore.sh:3'; '/usr/local/bin/kiroo-entrypoint:1'; exit 0 }
  '^run .*lista\.sh'        { exit 0 }
  '^volume inspect .*kiroo-ensaio-dados' { if (Test-Path $vol) { '{"kiroo.ensaio":"backup"}'; exit 0 }; [Console]::Error.WriteLine('no such volume'); exit 1 }
  '^volume inspect .*kiroo_kiroo-data'   { [Console]::Error.WriteLine('no such volume'); exit 1 }
  '^volume create'          { if ($modo -eq 'create_falha') { [Console]::Error.WriteLine('permissao negada (stub)'); exit 1 }; New-Item -ItemType File $vol | Out-Null; 'kiroo-ensaio-dados'; exit 0 }
  default                   { [Console]::Error.WriteLine("stub: comando inesperado: $j"); exit 99 }
}
'@

$segredo = 'valor-ficticio-NAO-deve-aparecer'
$sys = Join-Path $env:SystemRoot 'System32'
$pathSemDocker = "$sys;$(Split-Path $psExe)"

function Rodar([string]$Nome, [hashtable]$Env, [string]$Pasta) {
    $caso = Join-Path $tmp $Nome; New-Item -ItemType Directory -Force $caso | Out-Null
    if (-not $Pasta) { $Pasta = Join-Path $caso 'pasta' }
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $stubDir 'volume.criado')
    $base = @{ PATH = "$stubDir;$pathSemDocker"; STUB_DIR = $stubDir; STUB_MODO = ''; STUDIO_ENV = 'staging';
        BACKUP_R2_ENDPOINT = $segredo; BACKUP_R2_ACCESS_KEY_ID = $segredo; BACKUP_R2_SECRET_ACCESS_KEY = $segredo; BACKUP_BUCKET = 'kiroo-backups' }
    foreach ($k in $Env.Keys) { $base[$k] = $Env[$k] }
    $salvo = @{}; foreach ($k in $base.Keys) { $salvo[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $base[$k]) }
    try {
        $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        $out = & $psExe -NoProfile -ExecutionPolicy Bypass -File $script -Passo 1 -Pasta $Pasta 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE; $ErrorActionPreference = $old
    } finally { foreach ($k in $salvo.Keys) { [Environment]::SetEnvironmentVariable($k, $salvo[$k]) } }
    return @{ Out = (@($out) -join "`n"); Code = $code }
}

$falhas = 0
function Checa([string]$Nome, $r, [string]$Esperado, [string[]]$Contem) {
    $erros = @()
    if ($r.Out -notmatch "RESULTADO passo 1: $Esperado(\s|$)") { $erros += "esperava RESULTADO $Esperado" }
    if ($r.Out -match 'call depth|profundidade da chamada|CallDepth') { $erros += 'ESTOURO DE PILHA' }
    if ($r.Out -match [regex]::Escape($segredo)) { $erros += 'valor de credencial impresso' }
    foreach ($c in $Contem) { if ($r.Out -notmatch $c) { $erros += "faltou /$c/" } }
    if ($erros) { $script:falhas++; Write-Host "FALHOU  $Nome : $($erros -join '; ')"; Write-Host ($r.Out -replace '(?m)^', '        | ') }
    else { Write-Host "ok      $Nome ($Esperado)" }
}

try {
    $r = Rodar 'feliz' @{}
    Checa 'caminho feliz chega ao fim do passo 1 sem recursao' $r 'PASS' @('docker 27\.0\.0-stub', 'volume kiroo-ensaio-dados criado', 'kiroo_kiroo-data nao existe')

    $r = Rodar 'sem_docker' @{ PATH = $pathSemDocker }
    if ((Get-Command docker -CommandType Application -ErrorAction SilentlyContinue | Where-Object { $_.Source -like "$sys*" })) { Write-Host 'aviso: ha docker em System32; caso sem_docker pode nao isolar' }
    Checa 'docker ausente -> NAO_VERIFICADO' $r 'NAO_VERIFICADO' @("executavel 'docker' nao encontrado")

    $r = Rodar 'daemon_fora' @{ STUB_MODO = 'daemon_fora' }
    Checa 'daemon fora -> NAO_VERIFICADO' $r 'NAO_VERIFICADO' @('docker indisponivel', 'Cannot connect')

    $r = Rodar 'sem_vars' @{ BACKUP_R2_SECRET_ACCESS_KEY = $null }
    Checa 'variavel ausente -> NAO_VERIFICADO' $r 'NAO_VERIFICADO' @('BACKUP_R2_SECRET_ACCESS_KEY: AUSENTE')

    $r = Rodar 'create_falha' @{ STUB_MODO = 'create_falha' }
    Checa 'comando falha (volume create) -> FAIL com mensagem' $r 'FAIL' @('ERRO: volume create falhou', 'permissao negada')

    # excecao nao prevista: -Pasta aponta para um ARQUIVO -> New-Item lanca IOException
    $arq = Join-Path $tmp 'sou-um-arquivo'; Set-Content $arq 'x'
    $r = Rodar 'excecao' @{} $arq
    Checa 'excecao nao tratada -> FAIL com mensagem' $r 'FAIL' @('ERRO: .+')
} finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $tmp
}

if ($falhas) { Write-Host "$falhas caso(s) falharam"; exit 1 }
Write-Host 'todos os casos passaram'; exit 0
