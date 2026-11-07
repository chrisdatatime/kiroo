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
$e = P7-ErrosLitestream $log
Ok 'litestream: conta 1 erro apos o SIGTERM (ignora o de antes e o JSON)' ($e.Count -eq 1 -and $e[0] -match 'monitor error') ($e -join ' | ')
$e = P7-ErrosLitestream @($log[1], $log[4])
Ok 'litestream: desligamento limpo = 0' ($null -ne $e -and $e.Count -eq 0)
Ok 'litestream: sem linha de SIGTERM = NAO_VERIFICADO ($null)' ($null -eq (P7-ErrosLitestream @($log[0], $log[3])))

# ultima escrita confirmada antes do sinal
$w = @("1`t200`t100", "2`t200`t200", "3`t503`t250", "4`t200`t310", "5`tsem_conexao`t400")
$u = P7-UltimaConfirmada $w 300
Ok 'escritas: ultima 200 antes do sinal = 2; total = 4' ($u.antes -eq 2 -and $u.total -eq 4 -and $u.confirmadas_depois_do_sinal -eq 1) ($u | Out-String)
$u = P7-UltimaConfirmada @("1`t503`t1") 300
Ok 'escritas: nenhuma 200 -> 0' ($u.antes -eq 0)

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
