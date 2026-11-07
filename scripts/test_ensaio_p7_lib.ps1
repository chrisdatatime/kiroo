<#
  Regressao das funcoes de avaliacao do passo 7 (scripts\ensaio_p7_lib.ps1), sem Docker e sem rede.
  Uso: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test_ensaio_p7_lib.ps1   (codigo 0 = todos passaram)
  Cada criterio tem um caso que PASSA e um que FALHA: a assercao nao pode ser frouxa.
#>
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ensaio_p7_lib.ps1')
$falhas = 0
function Ok([string]$Nome, [bool]$Cond, $Detalhe = '') {
    if ($Cond) { Write-Host "ok      $Nome" } else { $script:falhas++; Write-Host "FALHOU  $Nome $Detalhe" }
}
function T($id, $kind, $scene, $no, $status, $op, $sup = 0) {
    [pscustomobject]@{ id = $id; kind = $kind; scene_idx = $scene; attempt_no = $no; status = $status; remote_op_id = $op;
        input_hash = "h-$id"; created_at = "c-$id"; superseded = $sup }
}

# /readyz
$r = P7-Readyz @("1`t200", "2`t200", "3`t503", "4`t503", "5`tsem_conexao", "6`tsem_conexao")
Ok 'readyz: 200 > 503 > queda = 503 antes de cair' ($r.antes_de_cair -and $r.caiu -and $r.sequencia -eq '200x2 > 503x2 > sem_conexaox2') $r.sequencia
$r = P7-Readyz @("1`t200", "2`tsem_conexao", "3`t503")
Ok 'readyz: 503 so depois da queda NAO conta' (-not $r.antes_de_cair -and $r.viu503)
$r = P7-Readyz @("1`t200", "2`t200", "3`tsem_conexao")
Ok 'readyz: sem 503 nenhum -> falso' (-not $r.antes_de_cair)

# erros do Litestream so depois do SIGTERM, ignorando JSON do app
$log = @(
    '2026-11-07T10:00:00.1Z /data/studio.sqlite3: sync error: antes do sinal (nao conta)',
    '2026-11-07T10:00:01.1Z {"level": "INFO", "msg": "SIGTERM: parando de aceitar jobs; aguardando ate 25.0s"}',
    '2026-11-07T10:00:02.1Z {"level": "ERROR", "msg": "readyz falhou: error do app (JSON, nao e Litestream)"}',
    '2026-11-07T10:00:03.1Z /data/studio.sqlite3(s3): monitor error: context canceled',
    '2026-11-07T10:00:03.2Z litestream shut down')
$e = P7-ErrosLitestream $log $true
Ok 'litestream: conta 1 erro apos o SIGTERM (ignora o de antes e o JSON)' ($e.Count -eq 1 -and $e[0] -match 'monitor error') ($e -join ' | ')
$e = P7-ErrosLitestream @($log[1], $log[4]) $true
Ok 'litestream: desligamento limpo = 0' ($null -ne $e -and $e.Count -eq 0)
Ok 'litestream: sem linha de SIGTERM = NAO_VERIFICADO ($null)' ($null -eq (P7-ErrosLitestream @($log[0], $log[3]) $true))
# rascunho sem Litestream: log com SIGTERM e sem erro NAO pode virar 0 (nem FAIL)
Ok 'litestream inativo: erros = NAO_VERIFICADO ($null), nunca 0' ($null -eq (P7-ErrosLitestream @($log[1], $log[4]) $false))
Ok 'litestream inativo: mesmo com linha de erro = NAO_VERIFICADO, nunca FAIL' ($null -eq (P7-ErrosLitestream $log $false))

# Litestream ativo? (geracao 16 hex E linha do Litestream no log)
$g = '0123456789abcdef'
$logLs = @('2026-11-07T10:00:00.0Z litestream v0.3.13', '2026-11-07T10:00:00.1Z initialized db: /data/studio.sqlite3',
    '2026-11-07T10:00:00.2Z replicating to: name="s3" type="s3"', $log[1])
Ok 'litestream ativo: geracao valida + linhas do Litestream' ((P7-LitestreamAtivo $logLs $g).ativo)
$x = P7-LitestreamAtivo @('2026-11-07T10:00:00.0Z entrypoint: backup desligado (dev; faltam: BACKUP_R2_ENDPOINT)', $log[1]) $g
Ok 'litestream inativo: entrypoint com backup desligado' (-not $x.ativo -and $x.motivo -match 'SEM replicacao') $x.motivo
$x = P7-LitestreamAtivo $logLs 'SEM-LITESTREAM'
Ok 'litestream inativo: geracao falsa do rascunho (SEM-LITESTREAM)' (-not $x.ativo -and $x.motivo -match 'geracao') $x.motivo
Ok 'litestream inativo: geracao ausente' (-not (P7-LitestreamAtivo $logLs '').ativo)
$x = P7-LitestreamAtivo @($log[1], '2026-11-07T10:00:00.0Z {"msg": "replicating to: texto do app em JSON nao conta"}') $g
Ok 'litestream inativo: sem linha do proprio Litestream (JSON do app nao conta)' (-not $x.ativo -and $x.motivo -match 'nenhuma linha') $x.motivo

# geracao nova depois do SIGKILL
Ok 'geracao nova: inativo = NAO_VERIFICADO (nunca FAIL)' ((P7-GeracaoNova 'a' 'a' $false).resultado -eq 'NAO_VERIFICADO')
Ok 'geracao nova: ilegivel depois = NAO_VERIFICADO' ((P7-GeracaoNova $g '' $true).resultado -eq 'NAO_VERIFICADO')
Ok 'geracao nova: ilegivel antes = NAO_VERIFICADO' ((P7-GeracaoNova '' $g $true).resultado -eq 'NAO_VERIFICADO')
Ok 'geracao nova: mesma geracao com Litestream ativo = FAIL' ((P7-GeracaoNova $g $g $true).resultado -eq 'FAIL')
Ok 'geracao nova: geracao diferente = PASS' ((P7-GeracaoNova $g 'fedcba9876543210' $true).resultado -eq 'PASS')

# ultima escrita confirmada antes do sinal
$w = @("1`t200`t100", "2`t200`t200", "3`t503`t250", "4`t200`t310", "5`tsem_conexao`t400")
$u = P7-UltimaConfirmada $w 300
Ok 'escritas: ultima 200 antes do sinal = 2; total = 4' ($u.antes -eq 2 -and $u.total -eq 4 -and $u.confirmadas_depois_do_sinal -eq 1) ($u | Out-String)
$u = P7-UltimaConfirmada @("1`t503`t1") 300
Ok 'escritas: nenhuma 200 -> 0' ($u.antes -eq 0)
$u = P7-UltimaConfirmada @("1`t200`t100`t90", "2`t200`t310`t305") 300
Ok 'escritas: formato novo (4 colunas) continua lido' ($u.antes -eq 1 -and $u.total -eq 2)

# cada escrita confirmada: antes/depois do SIGTERM pelo servidor (ordem no log) e pelo cliente (horarios)
$pre = 'w7-a1-101522-'
$logW = @(
    '2026-11-07T13:15:38.40Z {"msg": "E-mail para w7-a1-101522-1@ensaio.test (sem SMTP configurado) | x"}',
    '2026-11-07T13:15:38.41Z {"msg": "SIGTERM: parando de aceitar jobs; aguardando ate 25.0s"}',
    '2026-11-07T13:15:38.47Z {"msg": "E-mail para w7-a1-101522-2@ensaio.test (sem SMTP configurado) | x"}',
    '2026-11-07T13:15:38.50Z {"msg": "E-mail para w7-a1-101522-30@ensaio.test (sem SMTP configurado) | x"}')
$wl = @("1`t200`t100`t90", "2`t200`t305`t295", "3`t200`t320`t310", "4`t503`t330`t325", "5`tsem_conexao`t340`t335")
$es = P7-Escritas $wl 300 $logW $pre
Ok 'aceitas: so as 200 (3), 503 e sem_conexao fora' (@($es).Count -eq 3) (@($es).Count)
Ok 'aceitas: cliente antes / em_voo / depois' ((($es | ForEach-Object { $_.cliente }) -join ',') -eq 'antes,em_voo,depois') (($es | ForEach-Object { $_.cliente }) -join ',')
Ok 'aceitas: servidor antes / depois / sem_log (o 3 nao esta no log; 30 nao e confundido com 3)' ((($es | ForEach-Object { $_.servidor }) -join ',') -eq 'antes,depois,sem_log') (($es | ForEach-Object { $_.servidor }) -join ',')
Ok 'aceitas: formato antigo (3 colunas) sem envio = em_voo, nunca depois' ((P7-Escritas @("7`t200`t305") 300 $logW $pre)[0].cliente -eq 'em_voo')
$tsv = P7-Tsv $es
Ok 'aceitas: tsv com cabecalho + 3 linhas' ($tsv.Count -eq 4 -and $tsv[1] -match "^1`tw7-a1-101522-1@ensaio\.test`t") ($tsv -join ' | ')

# todas as aceitas no restore
Ok 'restore: todas presentes (maiusculas nao importam) = nenhuma ausente' ((P7-Ausentes $es @('W7-A1-101522-1@ensaio.test', 'w7-a1-101522-2@ensaio.test', 'w7-a1-101522-3@ensaio.test', 'w7-a1-101522-99@ensaio.test')).Count -eq 0)
$aus = P7-Ausentes $es @('w7-a1-101522-1@ensaio.test', 'w7-a1-101522-3@ensaio.test')
Ok 'restore: uma aceita ausente = acusada com o id' ($aus.Count -eq 1 -and $aus[0] -eq 'w7-a1-101522-2@ensaio.test') ($aus -join ',')
Ok 'restore: restore vazio = todas ausentes' ((P7-Ausentes $es @()).Count -eq 3)

# snapshot x depois
$antes = @((T 'a1' 'plan' $null 1 'succeeded' $null), (T 'a2' 'image' 1 1 'succeeded' 'op-i1'), (T 'a3' 'video' 1 1 'submitted' 'op-v1'), (T 'a4' 'image' 2 1 'created' $null))
$depoisOk = @((T 'a1' 'plan' $null 1 'succeeded' $null), (T 'a2' 'image' 1 1 'succeeded' 'op-i1'), (T 'a3' 'video' 1 1 'succeeded' 'op-v1'),
    (T 'a4' 'image' 2 1 'succeeded' 'op-i2'), (T 'a5' 'video' 2 1 'succeeded' 'op-v2'))
Ok 'snapshot: progresso legitimo (submitted->succeeded, created->enviado, tentativa nova de outra etapa) = sem diff' ((P7-Tentativas $antes $depoisOk).Count -eq 0)
Ok 'repetidas: progresso legitimo = nada repetido' ((P7-Repetidas $antes $depoisOk).Count -eq 0) ((P7-Repetidas $antes $depoisOk) -join ' | ')
$sumiu = @($depoisOk | Where-Object { $_.id -ne 'a2' })
Ok 'snapshot: tentativa sumida aparece no diff' ((@(P7-Tentativas $antes $sumiu) -match 'a2 .*SUMIU').Count -gt 0)
$trocou = @($depoisOk | ForEach-Object { if ($_.id -eq 'a3') { T 'a3' 'video' 1 1 'succeeded' 'op-OUTRA' } else { $_ } })
Ok 'snapshot: operacao remota trocada aparece no diff' ((@(P7-Tentativas $antes $trocou) -match 'remote_op_id.*op-v1.*op-OUTRA').Count -gt 0)
$rep = $depoisOk + @(T 'a6' 'video' 1 2 'submitted' 'op-v1b')
Ok 'repetidas: video da cena 1 reenviado com o antigo ainda submitted = repetida' ((@(P7-Repetidas $antes $rep) -match 'a6 .*repete a3').Count -gt 0)
$rep = $depoisOk + @(T 'a7' 'image' 1 2 'succeeded' 'op-i1b')
Ok 'repetidas: imagem refeita depois de succeeded = repetida' ((@(P7-Repetidas $antes $rep) -match 'a7 .*repete a2').Count -gt 0)
$dup = $depoisOk + @(T 'a8' 'image' 2 1 'created' $null)
Ok 'repetidas: (cena, tipo, numero) duplicado acusado' ((@(P7-Repetidas $antes $dup) -match 'duplicada').Count -gt 0)
$sub = @((T 'a2' 'image' 1 1 'succeeded' 'op-i1' 1))
Ok 'repetidas: nova tentativa depois de uma SUBSTITUIDA e permitida' ((P7-Repetidas $sub ($sub + @(T 'a9' 'image' 1 2 'created' $null))).Count -eq 0)

Ok 'veredito: falha domina' ((P7-Veredito @('x') @('y')) -eq 'FAIL')
Ok 'veredito: so nao verificado' ((P7-Veredito @() @('y')) -eq 'NAO_VERIFICADO')
Ok 'veredito: limpo = PASS' ((P7-Veredito @() @()) -eq 'PASS')

if ($falhas) { Write-Host "$falhas caso(s) falharam"; exit 1 }
Write-Host 'todos os casos passaram'; exit 0
