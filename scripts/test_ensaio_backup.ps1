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
  # como o docker real: {{index .Config.Labels "..."}} chega sem as aspas internas (PS 5.1) e o template falha
  '^image inspect .*index .*Labels' { [Console]::Error.WriteLine('template parsing error: template: :1: function "org" not defined'); exit 64 }
  '^image inspect .*json \.Config\.Labels' {
    if ($env:STUB_REV_MODO -eq 'null') { 'null' } elseif ($env:STUB_REV) { '{"maintainer":"x","org.opencontainers.image.revision":"' + $env:STUB_REV + '"}' } else { '{"maintainer":"x"}' }
    exit 0 }
  '^image inspect'          { 'sha256:stub'; exit 0 }
  '^run .*--entrypoint grep' { '/etc/litestream.yml:2'; '/app/scripts/restore.sh:3'; '/usr/local/bin/kiroo-entrypoint:1'; exit 0 }
  '^run .*lista\.sh' {
    [Console]::Error.WriteLine('NOTICE: Config file "/nonexistent/.rclone.conf" not found - using defaults')
    if ($j -match 'media/archive') { '2099-01-01T000000Z/productions/ensaio-marcador.txt' }
    exit 0 }
  '^run .*le\.sh' {
    # rclone cat: conteudo no stdout, NOTICE no stderr (o bug: o NOTICE entrava na comparacao)
    [Console]::Error.WriteLine('NOTICE: Config file "/nonexistent/.rclone.conf" not found - using defaults')
    if ($j -match 'media/archive/') { 'versao-1' } elseif ($modo -eq 'p4_errado') { 'versao-1' } else { 'versao-2' }
    exit 0 }
  '^inspect '               { [Console]::Error.WriteLine('Error: No such object (stub)'); exit 1 }
  '^run .*prepara_midia\.sh' { 'versao-1'; exit 0 }
  '^run .*diag\.sh' {
    # saida no formato do rclone --dump headers, com credenciais FICTICIAS que a mascara precisa esconder
    'diag: rclone v1.60.1-DEV; arquivo de 40 bytes -> KBK:kiroo-backups/ensaio/diag/x.txt'
    '2026/11/07 12:00:00 DEBUG : >>>>>> HTTP REQUEST (req 0xc000)'
    'PUT /kiroo-backups/ensaio/diag/x.txt HTTP/1.1'
    'Host: 0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com'
    ('Authorization: AWS4-HMAC-SHA256 Credential=' + $env:BACKUP_R2_ACCESS_KEY_ID + '/20261107/auto/s3/aws4_request, SignedHeaders=host, Signature=assinaturaficticia0123')
    'X-Amz-Security-Token: tokenficticio-XYZ'
    'X-Amz-Acl: private'
    'GET /?X-Amz-Credential=AKIDFICTICIO99&X-Amz-Signature=sigficticia77 HTTP/1.1'
    ('linha crua com o segredo ' + $env:BACKUP_R2_SECRET_ACCESS_KEY)
    '2026/11/07 12:00:00 DEBUG : <<<<<< HTTP RESPONSE (req 0xc000)'
    'HTTP/1.1 501 Not Implemented'
    'diag: rclone saiu com codigo 1'
    exit 1 }
  '^run .*backup_media\.sh.*--dry-run' {
    if ($modo -eq 'bm2') { [Console]::Error.WriteLine('backup_media: variaveis ausentes (so os nomes): BACKUP_R2_ENDPOINT'); exit 2 }
    'backup_media: resumo: enviados=0 objetos; origem copiada: objetos=3 bytes=2048; manifesto: nao gravado em --dry-run [dry-run]'; exit 0 }
  '^run .*backup_media\.sh' {
    if ($modo -like 'p4_*') { 'backup_media: resumo: enviados=1 objetos; origem copiada: objetos=3 bytes=2048; manifesto: gravado em manifests/x.json'; exit 0 }
    'backup_media: resumo: enviados=1 objetos; origem copiada: objetos=3 bytes=2048; manifesto: NAO GRAVADO (manifests/x.json)'
    [Console]::Error.WriteLine('backup_media: ERRO ao gravar o manifesto (codigo 1): status code: 501')
    [Console]::Error.WriteLine('backup_media: FALHOU (x): manifesto(rc=1)')
    exit 1 }
  '^volume inspect .*kiroo-ensaio-dados' { if (Test-Path $vol) { '{"kiroo.ensaio":"backup"}'; exit 0 }; [Console]::Error.WriteLine('no such volume'); exit 1 }
  '^volume inspect .*kiroo_kiroo-data'   { [Console]::Error.WriteLine('no such volume'); exit 1 }
  '^volume create'          { if ($modo -eq 'create_falha') { [Console]::Error.WriteLine('permissao negada (stub)'); exit 1 }; New-Item -ItemType File $vol | Out-Null; 'kiroo-ensaio-dados'; exit 0 }
  default                   { [Console]::Error.WriteLine("stub: comando inesperado: $j"); exit 99 }
}
'@

Set-Content -Encoding ASCII (Join-Path $stubDir 'git.cmd') "@`"$psExe`" -NoProfile -ExecutionPolicy Bypass -File `"%~dp0git_stub.ps1`" %*`r`n@exit /b %ERRORLEVEL%"
Set-Content -Encoding ASCII (Join-Path $stubDir 'git_stub.ps1') @'
$j = @($args) -join ' '
if ($j -match 'rev-parse HEAD') { "$env:STUB_HEAD"; exit 0 }
if ($j -match 'diff --name-only') { 'scripts/ensaio_backup.ps1'; exit 0 }
exit 1
'@

$segredo = 'valor-ficticio-NAO-deve-aparecer'
$sys = Join-Path $env:SystemRoot 'System32'
$pathSemDocker = "$sys;$(Split-Path $psExe)"

function Rodar([string]$Nome, [hashtable]$Env, [string]$Pasta, [string[]]$Args2 = @('-Passo', '1'), [switch]$ManterVolume) {
    $caso = Join-Path $tmp $Nome; New-Item -ItemType Directory -Force $caso | Out-Null
    if (-not $Pasta) { $Pasta = Join-Path $caso 'pasta' }
    if (-not $ManterVolume) { Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $stubDir 'volume.criado') }
    $base = @{ PATH = "$stubDir;$pathSemDocker"; STUB_DIR = $stubDir; STUB_MODO = ''; STUDIO_ENV = 'staging';
        BACKUP_R2_ENDPOINT = $segredo; BACKUP_R2_ACCESS_KEY_ID = $segredo; BACKUP_R2_SECRET_ACCESS_KEY = $segredo; BACKUP_BUCKET = 'kiroo-backups' }
    foreach ($k in $Env.Keys) { $base[$k] = $Env[$k] }
    $salvo = @{}; foreach ($k in $base.Keys) { $salvo[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $base[$k]) }
    try {
        $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        $out = & $psExe -NoProfile -ExecutionPolicy Bypass -File $script @Args2 -Pasta $Pasta 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE; $ErrorActionPreference = $old
    } finally { foreach ($k in $salvo.Keys) { [Environment]::SetEnvironmentVariable($k, $salvo[$k]) } }
    return @{ Out = (@($out) -join "`n"); Code = $code }
}

$falhas = 0
function Checa([string]$Nome, $r, [string]$Esperado, [string[]]$Contem, [string[]]$NaoContem = @(), [string]$PassoN = '1') {
    $erros = @()
    if ($r.Out -notmatch "RESULTADO passo ${PassoN}: $Esperado(\s|$)") { $erros += "esperava RESULTADO $Esperado" }
    foreach ($c in $NaoContem) { if ($r.Out -match [regex]::Escape($c)) { $erros += "apareceu '$c'" } }
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

    # passos 4 e 4 -Diagnostico: precisam da pasta e do volume do passo 1 (mesma pasta, volume mantido)
    $p4 = Join-Path $tmp 'p4\pasta'
    $null = Rodar 'p4_prep' @{} $p4
    $r = Rodar 'p4' @{} $p4 @('-Passo', '4') -ManterVolume
    Checa 'passo 4: codigo 1 do backup_media -> FAIL com objetos e tamanho' $r 'FAIL' @(
        '--dry-run: codigo 0 \(ok\)', 'real #1: codigo 1 \(FALHA do rclone\)', 'objetos enviados: 1; origem: 3 objetos, 2.048 bytes|objetos enviados: 1; origem: 3 objetos, 2,048 bytes',
        'manifesto: NAO GRAVADO', 'FALHOU .*manifesto\(rc=1\)', '-Passo 4 -Diagnostico') -PassoN '4'
    $r = Rodar 'p4_diag' @{} $p4 @('-Passo', '4', '-Diagnostico') -ManterVolume
    Checa 'passo 4 -Diagnostico: cabecalhos com credenciais mascaradas' $r 'FAIL' @(
        'HTTP REQUEST', 'X-Amz-Acl: private', 'HTTP/1\.1 501 Not Implemented', 'Authorization: \*\*\*', 'X-Amz-Security-Token: \*\*\*',
        'X-Amz-Credential=\*\*\*', '\*\*\*\.r2\.cloudflarestorage\.com', 'R2 respondeu 501') @(
        'assinaturaficticia0123', 'tokenficticio-XYZ', 'AKIDFICTICIO99', 'sigficticia77', '0123456789abcdef0123456789abcdef') -PassoN '4'
    $diag = Get-ChildItem $p4 -Filter 'diag-*.txt' | Select-Object -First 1
    if (-not $diag -or (Get-Content $diag.FullName -Raw) -match ([regex]::Escape($segredo) + '|assinaturaficticia|tokenficticio')) { $falhas++; Write-Host 'FALHOU  arquivo diag-*.txt ausente ou com credencial' }
    else { Write-Host 'ok      arquivo diag-*.txt gravado ja mascarado' }

    # regressao do NOTICE no stderr: conteudo certo -> PASS; conteudo errado -> FAIL (comparacao exata)
    $r = Rodar 'p4_ok' @{ STUB_MODO = 'p4_ok' } $p4 @('-Passo', '4') -ManterVolume
    Checa 'passo 4 com NOTICE no stderr e conteudo certo -> PASS' $r 'PASS' @("archive contem 'versao-1'; current contem 'versao-2'", 'ignorado na comparacao') @("contem 'NOTICE") -PassoN '4'
    $r = Rodar 'p4_errado' @{ STUB_MODO = 'p4_errado' } $p4 @('-Passo', '4') -ManterVolume
    Checa 'passo 4 com NOTICE e conteudo errado -> FAIL' $r 'FAIL' @("current contem 'versao-1'") -PassoN '4'

    # variaveis ausentes nos passos 4 e 5 -> NAO_VERIFICADO com a lista; codigo 2 do backup_media mostra a mensagem
    $r = Rodar 'p4_sem_vars' @{ STUDIO_ENV = $null; BACKUP_BUCKET = $null } $p4 @('-Passo', '4') -ManterVolume
    Checa 'passo 4 sem variaveis -> NAO_VERIFICADO com lista' $r 'NAO_VERIFICADO' @('variaveis ausentes: STUDIO_ENV, BACKUP_BUCKET') -PassoN '4'
    $r = Rodar 'p5_sem_vars' @{ BACKUP_R2_ACCESS_KEY_ID = $null } $p4 @('-Passo', '5') -ManterVolume
    Checa 'passo 5 sem variaveis -> NAO_VERIFICADO com lista' $r 'NAO_VERIFICADO' @('variaveis ausentes: BACKUP_R2_ACCESS_KEY_ID') -PassoN '5'
    $r = Rodar 'p4_bm2' @{ STUB_MODO = 'bm2' } $p4 @('-Passo', '4') -ManterVolume
    Checa 'passo 4: codigo 2 do backup_media mostra a mensagem' $r 'FAIL' @('codigo 2 \(uso/config invalida\)', 'backup_media: variaveis ausentes \(so os nomes\): BACKUP_R2_ENDPOINT') -PassoN '4'

    # commit da imagem x HEAD
    $h = 'a' * 40; $o = 'b' * 40
    $r = Rodar 'rev_igual' @{ STUB_REV = $h; STUB_HEAD = $h }
    Checa 'passo 1: imagem do HEAD atual' $r 'PASS' @('imagem construida do HEAD atual \(aaaaaaa\)') @('AVISO: imagem construida')
    $r = Rodar 'rev_diferente' @{ STUB_REV = $o; STUB_HEAD = $h }
    Checa 'passo 1: commit diferente -> aviso de reconstruir' $r 'PASS' @("AVISO: imagem construida do commit $o, diferente do HEAD $h", 'exigem RECONSTRUIR', 'scripts/ensaio_backup\.ps1')
    $r = Rodar 'rev_ausente' @{ STUB_REV = '' }
    Checa 'passo 1: imagem sem commit -> aviso' $r 'PASS' @('AVISO: imagem kiroo:dados sem commit gravado')
    $r = Rodar 'rev_null' @{ STUB_REV_MODO = 'null'; STUB_HEAD = $h }
    Checa 'passo 1: imagem sem rotulo nenhum (null) -> aviso' $r 'PASS' @('AVISO: imagem kiroo:dados sem commit gravado')
    $r = Rodar 'rev_igual_sem_aviso' @{ STUB_REV = $h; STUB_HEAD = $h }
    Checa 'passo 1: rotulo igual ao HEAD -> nenhum aviso de commit' $r 'PASS' @('imagem construida do HEAD atual') @('AVISO: imagem kiroo:dados sem commit', 'AVISO: imagem construida', 'AVISO: commit da imagem')
    # passo 7 sem docker real: variaveis ausentes e pasta ausente -> NAO_VERIFICADO (nada de container/volume criado)
    $n0 = @(Get-Content (Join-Path $stubDir 'chamadas.log') -ErrorAction SilentlyContinue).Count
    $r = Rodar 'p7_sem_vars' @{ BACKUP_R2_ENDPOINT = $null } $p4 @('-Passo', '7') -ManterVolume
    Checa 'passo 7 sem variaveis -> NAO_VERIFICADO com lista' $r 'NAO_VERIFICADO' @('variaveis ausentes: BACKUP_R2_ENDPOINT') -PassoN '7'
    $r = Rodar 'p7_sem_pasta' @{} (Join-Path $tmp 'p7-nada') @('-Passo', '7')
    Checa 'passo 7 sem a pasta do passo 1 -> NAO_VERIFICADO' $r 'NAO_VERIFICADO' @('pasta do ensaio ausente') -PassoN '7'
    # -Rodadas / -Fumaca: a saida tambem vai para arquivo na pasta (sem credencial), com o modo no nome
    $r = Rodar 'p7_fumaca' @{ BACKUP_R2_ENDPOINT = $null } $p4 @('-Passo', '7', '-Fumaca') -ManterVolume
    Checa 'passo 7 -Fumaca anuncia 1 rodada de cada tipo' $r 'NAO_VERIFICADO' @('FUMACA: 1 rodada de cada tipo \(a1, b1, c1\)', 'p7-fumaca-\d{8}-\d{6}\.log') -PassoN '7'
    $r = Rodar 'p7_rodadas2' @{ BACKUP_R2_ENDPOINT = $null } $p4 @('-Passo', '7', '-Rodadas', '2') -ManterVolume
    Checa 'passo 7 -Rodadas 2' $r 'NAO_VERIFICADO' @('2 rodada\(s\) de cada tipo', 'p7-rodadas2-') -PassoN '7'
    $arqs = @(Get-ChildItem $p4 -Filter 'p7-*.log')
    $txt = ($arqs | ForEach-Object { Get-Content $_.FullName -Raw }) -join "`n"
    if ($arqs.Count -lt 3 -or $txt -notmatch 'RESULTADO passo 7: NAO_VERIFICADO' -or $txt -notmatch 'FUMACA' -or $txt -match [regex]::Escape($segredo)) {
        $falhas++; Write-Host "FALHOU  arquivo p7-*.log ausente, incompleto ou com credencial ($($arqs.Count) arquivo(s))" }
    else { Write-Host "ok      passo 7 grava a saida em p7-<modo>-<data>.log ($($arqs.Count) arquivos, sem credencial)" }
    $r = Rodar 'p7_rodadas6' @{} $p4 @('-Passo', '7', '-Rodadas', '6') -ManterVolume
    if ($r.Out -match 'RESULTADO passo 7' -or $r.Out -notmatch 'Rodadas') { $falhas++; Write-Host "FALHOU  -Rodadas 6 deveria ser recusado antes de rodar: $($r.Out)" }
    else { Write-Host 'ok      -Rodadas 6 recusado (1..5) antes de rodar' }

    # -Tipos / -Carga: recusas ANTES de rodar (sem RESULTADO, sem docker) e anuncio/nome do arquivo quando valem
    foreach ($c in @(@{ n = 'p7_tipos_b'; a = @('-Tipos', 'b'); m = "depende da rodada 'a'" }, @{ n = 'p7_tipos_bc'; a = @('-Tipos', 'b,c'); m = "depende da rodada 'a'" },
            @{ n = 'p7_tipos_x'; a = @('-Tipos', 'x'); m = 'Tipos' }, @{ n = 'p7_carga_ruim'; a = @('-Carga', 'extrema'); m = 'Carga' })) {
        $r = Rodar $c.n @{} $p4 (@('-Passo', '7') + $c.a) -ManterVolume
        if ($r.Out -match 'RESULTADO passo 7' -or $r.Out -notmatch [regex]::Escape($c.m)) { $falhas++; Write-Host "FALHOU  $($c.a -join ' ') deveria ser recusado antes de rodar: $($r.Out)" }
        else { Write-Host "ok      $($c.a -join ' ') recusado antes de rodar" }
    }
    $r = Rodar 'p7_tipos_a' @{ BACKUP_R2_ENDPOINT = $null } $p4 @('-Passo', '7', '-Tipos', 'a') -ManterVolume
    Checa 'passo 7 -Tipos a: so rodadas a, arquivo p7-rodadas5-a-' $r 'NAO_VERIFICADO' @('5 rodada\(s\) de cada tipo \(a\); carga normal', 'p7-rodadas5-a-\d{8}-\d{6}\.log') -PassoN '7'
    $r = Rodar 'p7_tipos_ac_alta' @{ BACKUP_R2_ENDPOINT = $null } $p4 @('-Passo', '7', '-Tipos', 'a,c', '-Carga', 'alta', '-Rodadas', '2') -ManterVolume
    Checa 'passo 7 -Tipos a,c -Carga alta' $r 'NAO_VERIFICADO' @('2 rodada\(s\) de cada tipo \(a, c\); carga alta', 'p7-rodadas2-ac-alta-') -PassoN '7'
    $r = Rodar 'p7_fumaca_a_baixa' @{ BACKUP_R2_ENDPOINT = $null } $p4 @('-Passo', '7', '-Fumaca', '-Tipos', 'a', '-Carga', 'baixa') -ManterVolume
    Checa 'passo 7 -Fumaca -Tipos a -Carga baixa' $r 'NAO_VERIFICADO' @('FUMACA: 1 rodada de cada tipo \(a1\); carga baixa', 'p7-fumaca-a-baixa-') -PassoN '7'

    $chamadas = @(Get-Content (Join-Path $stubDir 'chamadas.log') -ErrorAction SilentlyContinue) | Select-Object -Skip $n0
    if ($chamadas -match '^(run|volume create|stop|kill)') { $falhas++; Write-Host "FALHOU  passo 7 NAO_VERIFICADO mexeu no docker: $($chamadas -join ' | ')" }
    else { Write-Host 'ok      passo 7 NAO_VERIFICADO nao cria container nem volume' }

    # Sonda-WalP7 extraida do roteiro e chamada com docker falso em processo: volume SO LEITURA, rotulo do ensaio, --rm,
    # nenhum -e (nenhuma credencial), python da imagem rodando /ensaio/sh/p7_wal.py; JSON lido mesmo com texto antes.
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($script, [ref]$null, [ref]$null)
    $fn = $ast.FindAll({ param($x) $x -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $x.Name -eq 'Sonda-WalP7' }, $true) | Select-Object -First 1
    . ([scriptblock]::Create($fn.Extent.Text))
    $ROTULO = 'kiroo.ensaio=backup'; $Pasta = 'C:\ensaio-falso'; $IMAGEM = 'kiroo:dados'
    $script:sondaArgs = $null; $script:sondaVol = $null; $script:sondaResp = $null
    function Assert-VolumeP7([string]$N) { $script:sondaVol = $N }
    function Invoke-Docker([string[]]$ArgList) { $script:sondaArgs = $ArgList; $script:sondaResp }
    $script:sondaResp = @{ Code = 0; Out = ''; Stderr = ''; Stdout = "aviso qualquer`n{""db_bytes"": 8192, ""wal_arquivo_bytes"": null, ""page_size"": 4096, ""sombra_bytes"": 4152}" }
    $s = Sonda-WalP7 'kiroo-ensaio-p7-a3'
    $j = $script:sondaArgs -join ' '
    $okArgs = ($script:sondaVol -eq 'kiroo-ensaio-p7-a3') -and ($script:sondaArgs -contains 'kiroo-ensaio-p7-a3:/data:ro') -and ($j -match '^run --rm --label kiroo\.ensaio=backup ') -and
        ($script:sondaArgs -notcontains '-e') -and ($j -match '--entrypoint python kiroo:dados /ensaio/sh/p7_wal\.py /data$') -and ($j -notmatch 'BACKUP_|LITESTREAM_')
    if (-not $okArgs -or $s -is [string] -or $s.sombra_bytes -ne 4152 -or $s.page_size -ne 4096) { $falhas++; Write-Host "FALHOU  sonda do WAL: args '$j' / resultado '$s'" }
    else { Write-Host 'ok      sonda do WAL: volume :ro, rotulo, --rm, sem -e; JSON lido' }
    $script:sondaResp = @{ Code = 125; Out = 'Error: no such image'; Stderr = ''; Stdout = '' }
    $s = Sonda-WalP7 'kiroo-ensaio-p7-a3'
    if (-not ($s -is [string] -and $s -match 'sonda do WAL falhou \(codigo 125\)')) { $falhas++; Write-Host "FALHOU  sonda do WAL com docker falhando deveria devolver o motivo: $s" }
    else { Write-Host 'ok      sonda do WAL: falha do docker vira motivo (nao derruba a rodada)' }
    Remove-Item Function:\Invoke-Docker, Function:\Assert-VolumeP7, Function:\Sonda-WalP7
    # docker inspect da rodada "a": so ExitCode e FinishedAt (nunca Env nem a Config inteira)
    $txtScript = Get-Content $script -Raw
    if ($txtScript -notmatch [regex]::Escape("'{{.State.ExitCode}};{{.State.FinishedAt}}'") -or $txtScript -match '\.Config\.Env|\{\{json \.Config\}\}|\{\{json \.\}\}') {
        $falhas++; Write-Host 'FALHOU  docker inspect do passo 7 deveria pedir so ExitCode e FinishedAt' }
    else { Write-Host 'ok      docker inspect do passo 7 pede so {{.State.ExitCode}};{{.State.FinishedAt}}' }

    $log = (@(Get-Content (Join-Path $stubDir 'chamadas.log') -ErrorAction SilentlyContinue) -join "`n")
    if ($log -match 'image inspect --format \{\{index') { $falhas++; Write-Host 'FALHOU  passo 1 ainda usa {{index ...}} (quebra no PS 5.1)' }
    else { Write-Host 'ok      passo 1 le os rotulos com {{json .Config.Labels}}' }
} finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $tmp
}

if ($falhas) { Write-Host "$falhas caso(s) falharam"; exit 1 }
Write-Host 'todos os casos passaram'; exit 0
