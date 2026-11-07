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

# ------------------------------------------------------------------ WAL no fechamento x erro do Litestream
# calcWALSize (Litestream v0.3.13, litestream.go): 32 + (24 + page_size) * n
Ok 'limite: 1000 paginas de 4096 = 4.120.032 bytes' ((P7-LimiteWal 4096) -eq 4120032) (P7-LimiteWal 4096)
Ok 'limite: 1000 paginas de 8192 = 8.216.032 bytes' ((P7-LimiteWal 8192) -eq 8216032)
Ok 'limite: 1 pagina de 4096 = 4152 (o 1o segmento do log tem sz=4152)' ((P7-LimiteWal 4096 1) -eq 4152)
Ok 'paginas: exatamente no limite = 1000' ((P7-PaginasWal 4120032 4096) -eq 1000)
Ok 'paginas: 1 byte abaixo do limite = 999' ((P7-PaginasWal 4120031 4096) -eq 999)
Ok 'paginas: so o cabecalho = 0; vazio = 0' ((P7-PaginasWal 32 4096) -eq 0 -and (P7-PaginasWal 0 4096) -eq 0)
Ok 'paginas: sem bytes ou sem page_size = $null' ($null -eq (P7-PaginasWal $null 4096) -and $null -eq (P7-PaginasWal 5000 $null) -and $null -eq (P7-PaginasWal 5000 0))
Ok 'paginas: a2 de 07/11 (4.268.352 bytes) = 1036' ((P7-PaginasWal 4268352 4096) -eq 1036)

# horarios
Ok 'utc: nanossegundos do docker truncados em ms' ((P7-Utc '2026-11-07T14:11:02.028396491Z') -eq '2026-11-07T14:11:02.028Z')
Ok 'utc: sem fracao vira .000' ((P7-Utc '2026-11-07T14:11:02Z') -eq '2026-11-07T14:11:02.000Z')
Ok 'utc: fracao curta completada' ((P7-Utc '2026-11-07T14:11:02.5Z') -eq '2026-11-07T14:11:02.500Z')
Ok 'utc: ilegivel = $null' ($null -eq (P7-Utc '0001-01-01 lixo'))
Ok 'seg: diferenca em segundos' ((P7-Seg '2026-11-07T14:10:36.346Z' '2026-11-07T14:11:02.028Z') -eq 25.682)

# log de uma rodada com o erro (formato real do docker logs --timestamps de 07/11, encurtado)
$logA = @(
    '2026-11-07T14:10:23.464840969Z time=2026-11-07T14:10:23.464Z level=INFO msg="initialized db" path=/data/studio.sqlite3',
    '2026-11-07T14:10:36.346287027Z time=2026-11-07T14:10:36.346Z level=INFO msg="signal received, litestream shutting down"',
    '2026-11-07T14:10:36.346743627Z {"ts": "2026-11-07T14:10:36.346+00:00", "level": "INFO", "msg": "SIGTERM: parando de aceitar jobs; aguardando ate 25.0s", "event": "stop"}',
    '2026-11-07T14:11:00.985391384Z time=2026-11-07T14:11:00.985Z level=INFO msg="wal segment written" db=/data/studio.sqlite3 replica=s3 position=ec535fa216d82639/00000003:3024112 elapsed=511ms sz=630360',
    '2026-11-07T14:11:01.349172487Z {"ts": "2026-11-07T14:11:01.348+00:00", "level": "WARNING", "msg": "desligamento: 1 producao(oes) ainda em andamento marcadas como interrompidas"}',
    '2026-11-07T14:11:01.486753005Z time=2026-11-07T14:11:01.483Z level=INFO msg="write wal segment" db=/data/studio.sqlite3 replica=s3 position=ec535fa216d82639/00000003:3654472',
    '2026-11-07T14:11:02.028078548Z time=2026-11-07T14:11:02.027Z level=INFO msg="wal segment written" db=/data/studio.sqlite3 replica=s3 position=ec535fa216d82639/00000003:3654472 elapsed=544ms sz=613880',
    '2026-11-07T14:11:02.028396491Z time=2026-11-07T14:11:02.028Z level=ERROR msg="error closing db" db=/data/studio.sqlite3 error="checkpoint: mode=PASSIVE err=release read lock: context canceled"',
    '2026-11-07T14:11:02.028403885Z time=2026-11-07T14:11:02.028Z level=INFO msg="litestream shut down"',
    '2026-11-07T14:11:02.028407222Z time=2026-11-07T14:11:02.028Z level=ERROR msg="failed to run" error="checkpoint: mode=PASSIVE err=release read lock: context canceled"')
$wl = P7-WalDoLog $logA
Ok 'wal do log: ultimo segmento enviado = offset + sz (3.654.472 + 613.880)' ($wl.bytes -eq 4268352 -and $wl.indice -eq '00000003' -and $wl.geracao -eq 'ec535fa216d82639') "$($wl.bytes)"
Ok 'wal do log: sem segmento enviado = $null' ($null -eq (P7-WalDoLog @($logA[0], $logA[1])))
$elA = P7-ErrosLitestream $logA $true
Ok 'erro de checkpoint: detectado nas linhas ERROR' ((P7-ErroCheckpoint $elA) -eq $true)
Ok 'erro de checkpoint: mode=RESTART tambem conta' ((P7-ErroCheckpoint @('x level=ERROR msg="error closing db" error="checkpoint: mode=RESTART err=release read lock: context canceled"')) -eq $true)
Ok 'erro de checkpoint: so "monitor error" NAO e o erro da hipotese' ((P7-ErroCheckpoint @('x level=ERROR msg="monitor error" error="client write: RequestCanceled: request context canceled"')) -eq $false)
Ok 'erro de checkpoint: nenhuma linha ERROR = falso' ((P7-ErroCheckpoint @()) -eq $false)
Ok 'erro de checkpoint: erros nao contados = $null (NAO_VERIFICADO)' ($null -eq (P7-ErroCheckpoint $null))
$mc = P7-Marcos $logA $elA
Ok 'marcos: signal, SIGTERM do app, interrompidas e shut down' ($mc.signal_ls -eq '2026-11-07T14:10:36.346Z' -and $mc.sigterm_app -eq '2026-11-07T14:10:36.346Z' -and
    $mc.interrompidas -eq '2026-11-07T14:11:01.349Z' -and $mc.ls_shutdown -eq '2026-11-07T14:11:02.028Z') ($mc | Out-String)
Ok 'marcos: duas linhas ERROR com horario e msg' ($mc.erros.Count -eq 2 -and $mc.erros[0] -eq '2026-11-07T14:11:02.028Z error closing db' -and $mc.erros[1] -match 'failed to run$') ($mc.erros -join ' | ')
$lt = P7-LinhaDoTempo $mc '2026-11-07T14:10:36.340Z' '2026-11-07T14:11:02.100Z'
Ok 'linha do tempo: tempos relativos ao signal do Litestream' ($lt -match 'stop=2026-11-07T14:10:36\.340Z' -and $lt -match 'interrompidas=\+25\.003 s' -and
    $lt -match 'ERROR\(error closing db\)=\+25\.682 s' -and $lt -match 'finished=\+25\.754 s') $lt
$lt = P7-LinhaDoTempo (P7-Marcos @() @()) $null $null
Ok 'linha do tempo: sem marcos = ? (sem quebrar)' ($lt -match 'signal_ls=\?' -and $lt -match 'finished=\?') $lt

# fonte do WAL: sombra > log > arquivo
$son = [pscustomobject]@{ sombra_bytes = 3353712; wal_arquivo_bytes = $null; page_size = 4096 }
Ok 'fonte: sombra quando existe' ((P7-EscolheWal $son $wl).fonte -eq 'sombra' -and (P7-EscolheWal $son $wl).bytes -eq 3353712)
$son2 = [pscustomobject]@{ sombra_bytes = $null; wal_arquivo_bytes = 9999999 }
Ok 'fonte: log sem sombra (o -wal do volume fica por ultimo)' ((P7-EscolheWal $son2 $wl).fonte -eq 'log')
Ok 'fonte: arquivo -wal so sem sombra e sem log' ((P7-EscolheWal $son2 $null).fonte -eq 'arquivo' -and (P7-EscolheWal $son2 $null).bytes -eq 9999999)
Ok 'fonte: sonda falhou e sem log = nenhuma' ((P7-EscolheWal $null $null).fonte -eq 'nenhuma' -and $null -eq (P7-EscolheWal $null $null).bytes)

# hipotese: casos a favor E contra (a funcao nao pode concordar com tudo)
$h = P7-Hipotese 4268352 4096 $true
Ok 'hipotese: acima do limite COM erro = consistente' ($h.classe -eq 'consistente' -and $h.previsto -eq $true -and $h.paginas -eq 1036) ($h | Out-String)
$h = P7-Hipotese 3353712 4096 $false
Ok 'hipotese: abaixo do limite SEM erro = consistente' ($h.classe -eq 'consistente' -and $h.previsto -eq $false)
$h = P7-Hipotese 4120032 4096 $true
Ok 'hipotese: exatamente 1000 paginas preve erro (>=)' ($h.previsto -eq $true -and $h.classe -eq 'consistente')
$h = P7-Hipotese 5000000 4096 $false
Ok 'hipotese CONTRARIADA: acima do limite SEM erro = contraexemplo' ($h.classe -eq 'contraexemplo' -and $h.motivo -match '1213 paginas \(>= 1000\) e SEM erro') $h.motivo
$h = P7-Hipotese 2550312 4096 $true
Ok 'hipotese CONTRARIADA: erro com WAL abaixo do limite = contraexemplo' ($h.classe -eq 'contraexemplo' -and $h.motivo -match 'erro de checkpoint com WAL de 619 paginas \(< 1000\)') $h.motivo
Ok 'hipotese: sem WAL = indeterminada' ((P7-Hipotese $null 4096 $true).classe -eq 'indeterminada')
Ok 'hipotese: sem page_size = indeterminada' ((P7-Hipotese 4268352 $null $true).classe -eq 'indeterminada')
$h = P7-Hipotese 4268352 4096 $null
Ok 'hipotese: erros NAO_VERIFICADO = indeterminada (nunca consistente)' ($h.classe -eq 'indeterminada' -and $h.motivo -match 'NAO_VERIFICADO')
Ok 'hipotese: page_size 8192 usa o limite de 8192' ((P7-Hipotese 5000000 8192 $false).classe -eq 'consistente')

# os 5 "a" de 07/11 (WAL pelo log; erro de checkpoint em a2, a3, a5): 5 de 5 consistentes
function Rod7($rod, $bytes, $erro, $res = 'FAIL', $saida = '1') {
    $h = P7-Hipotese $bytes 4096 $erro
    [ordered]@{ rodada = $rod; carga = 'normal'; wal_bytes = $bytes; wal_fonte = 'log'; wal_paginas = $h.paginas; limite_paginas = 1000; saida = $saida;
        erros_litestream = $(if ($erro) { 2 } else { 0 }); resultado = $res; hipotese = $h.classe; hipotese_motivo = $h.motivo }
}
$r0711 = @((Rod7 'a1' 2550312 $false 'FAIL' '0'), (Rod7 'a2' 4268352 $true), (Rod7 'a3' 4264232 $true), (Rod7 'a4' 3353712 $false 'PASS' '0'), (Rod7 'a5' 4890472 $true))
$c = P7-Conclusao $r0711
Ok 'conclusao: 07/11 = consistente em 5 de 5, sem contraexemplo' ($c -eq 'hipotese consistente em 5 de 5 rodadas / contraexemplos: nenhum') $c
$mix = @((Rod7 'a1' 4268352 $true), (Rod7 'a2' 5000000 $false 'PASS' '0'), (Rod7 'a3' 1000000 $true), (Rod7 'a4' 3353712 $false 'PASS' '0'),
    [ordered]@{ rodada = 'a5'; hipotese = 'indeterminada'; hipotese_motivo = 'WAL ou page_size desconhecido' }, [ordered]@{ rodada = 'a6' })
$c = P7-Conclusao $mix
Ok 'conclusao: contraexemplos listados com o motivo; indeterminadas fora do M' ($c -match '^hipotese consistente em 2 de 4 rodadas / contraexemplos: a2 \(WAL com 1213 paginas' -and
    $c -match '; a3 \(erro de checkpoint com WAL de 242 paginas' -and $c -match 'indeterminadas: a5 \(WAL ou page_size desconhecido\); a6 \(sem medicao\)$') $c
Ok 'conclusao: nada medido = 0 de 0' ((P7-Conclusao @()) -eq 'hipotese consistente em 0 de 0 rodadas / contraexemplos: nenhum')
$tb = P7-Tabela $r0711
Ok 'tabela: cabecalho + 1 linha por rodada' ($tb.Count -eq 6 -and $tb[0] -match '^rodada\s+carga\s+wal_bytes\s+fonte\s+wal_pag\s+limite\s+saida\s+settle_s\s+erros_ls\s+resultado\s+hipotese$') ($tb -join "`n")
Ok 'tabela: linha da a2 com os valores' ($tb[2] -match '^a2\s+normal\s+4268352\s+log\s+1036\s+1000\s+1\s+\?\s+2\s+FAIL\s+consistente$') $tb[2]
$tb = P7-Tabela @([ordered]@{ rodada = 'a9'; erros_litestream = 'NAO_VERIFICADO (Litestream inativo)'; resultado = 'NAO_VERIFICADO' })
Ok 'tabela: campo ausente = ?; erros NAO_VERIFICADO abreviados' ($tb[1] -match '^a9\s+\?\s+\?\s+\?\s+\?\s+\?\s+\?\s+\?\s+NAO_VERIF\s+NAO_VERIFICADO\s+\?$') $tb[1]

# janela de assentamento (settle): eventos JSON do app no log do container
$logS = @(
    '2026-11-08T10:00:00.100000000Z time=2026-11-08T10:00:00.100Z level=INFO msg="signal received, litestream shutting down"',
    '2026-11-08T10:00:00.101000000Z {"ts": "2026-11-08T10:00:00.101+00:00", "level": "INFO", "logger": "studio.web.server", "msg": "SIGTERM: parando de aceitar jobs; aguardando ate 25.0s", "event": "stop"}',
    '2026-11-08T10:00:25.110000000Z {"ts": "2026-11-08T10:00:25.110+00:00", "level": "WARNING", "logger": "studio.web.server", "msg": "desligamento: 1 producao(oes) ainda em andamento marcadas como interrompidas"}',
    '2026-11-08T10:00:25.300000000Z {"ts": "2026-11-08T10:00:25.300+00:00", "level": "INFO", "logger": "studio.web.server", "msg": "drenagem concluida: requisicoes em andamento=0, checkpoint periodico parado, producoes ainda em chamada=0", "event": "drained"}',
    '2026-11-08T10:00:25.301000000Z {"ts": "2026-11-08T10:00:25.301+00:00", "level": "INFO", "logger": "studio.shutdown", "msg": "settle: inicio (3s para o Litestream sincronizar antes de o servidor sair)", "event": "settle_start", "settle_s": 3.0}',
    '2026-11-08T10:00:26.200000000Z time=2026-11-08T10:00:26.199Z level=INFO msg="wal segment written" db=/data/studio.sqlite3 replica=s3 position=ec535fa216d82639/00000004:0 elapsed=300ms sz=4152',
    '2026-11-08T10:00:28.302000000Z {"ts": "2026-11-08T10:00:28.302+00:00", "level": "INFO", "logger": "studio.shutdown", "msg": "settle: fim (3.001s)", "event": "settle_end", "settle_s": 3.0, "duration_ms": 3001.2, "interrupted": false}',
    '2026-11-08T10:00:28.400000000Z time=2026-11-08T10:00:28.400Z level=INFO msg="subprocess exited, litestream shutting down"',
    '2026-11-08T10:00:28.900000000Z time=2026-11-08T10:00:28.900Z level=INFO msg="litestream shut down"')
$st = P7-Settle $logS
Ok 'settle: inicio, fim, settle_s e duracao lidos do log' ($st.settle_s -eq 3 -and $st.inicio -eq '2026-11-08T10:00:25.301Z' -and $st.fim -eq '2026-11-08T10:00:28.302Z' -and
    $st.duracao_s -eq 3.001 -and $st.interrompido -eq $false -and $st.estado -eq 'completo') ($st | Out-String)
Ok 'settle: texto da rodada' ((P7-SettleTexto $st) -eq '3 s, durou 3.001 s') (P7-SettleTexto $st)
$mcS = P7-Marcos $logS @()
Ok 'marcos: settle_ini e settle_fim pelos eventos do app' ($mcS.settle_ini -eq '2026-11-08T10:00:25.301Z' -and $mcS.settle_fim -eq '2026-11-08T10:00:28.302Z') ($mcS | Out-String)
$ltS = P7-LinhaDoTempo $mcS '2026-11-08T10:00:00.095Z' '2026-11-08T10:00:28.950Z'
Ok 'linha do tempo: settle entre interrompidas e o shut down' ($ltS -match 'interrompidas=\+25\.010 s \| settle_ini=\+25\.201 s \| settle_fim=\+28\.202 s \| ls_shutdown=\+28\.800 s' -and $ltS -match 'finished=\+28\.850 s') $ltS
$ltV = P7-LinhaDoTempo $mc '2026-11-07T14:10:36.340Z' '2026-11-07T14:11:02.100Z'
Ok 'linha do tempo: log sem settle (imagem antiga) = settle_ini=? sem quebrar' ($ltV -match 'settle_ini=\? \| settle_fim=\? \| ls_shutdown=\+25\.682 s') $ltV
Ok 'settle: log sem eventos = ausente (settle_s $null)' ((P7-Settle $logA).estado -eq 'ausente' -and $null -eq (P7-Settle $logA).settle_s -and (P7-SettleTexto (P7-Settle $logA)) -match '^ausente')
$sk = P7-Settle @('2026-11-08T10:00:25.3Z {"level": "INFO", "msg": "settle desativado (STUDIO_SHUTDOWN_SETTLE_S=0)", "event": "settle_skipped", "settle_s": 0}')
Ok 'settle: settle_skipped = desativado, settle_s 0' ($sk.estado -eq 'desativado' -and $sk.settle_s -eq 0 -and (P7-SettleTexto $sk) -match 'desativado') ($sk | Out-String)
$it = P7-Settle @($logS[4], '2026-11-08T10:00:26.0Z {"msg": "settle: fim", "event": "settle_end", "settle_s": 3.0, "duration_ms": 699.0, "interrupted": true}')
Ok 'settle: interrompido por segundo sinal' ($it.estado -eq 'interrompido' -and $it.interrompido -and $it.duracao_s -eq 0.699 -and (P7-SettleTexto $it) -match 'INTERROMPIDO') ($it | Out-String)
$sf = P7-Settle @($logS[4])
Ok 'settle: inicio sem fim = sem_fim (processo morto no meio)' ($sf.estado -eq 'sem_fim' -and $sf.settle_s -eq 3 -and (P7-SettleTexto $sf) -match 'SEM settle_end') ($sf | Out-String)
Ok 'settle: "settle_start" so na mensagem (sem campo event) NAO conta' ((P7-Settle @('2026-11-08T10:00:25.3Z {"msg": "settle_start"}')).estado -eq 'ausente')
$sr = P7-SettleResumo @([ordered]@{ rodada = 'a1'; settle_s = 3.0 }, [ordered]@{ rodada = 'a2'; settle_s = 3.0 }, [ordered]@{ rodada = 'a3'; settle_s = $null }, [ordered]@{ rodada = 'a4' })
Ok 'settle: resumo agrupa por valor (ausente separado)' ($sr -eq 'settle_s: 3 em a1, a2 / ausente em a3, a4') $sr
# a regra de erros NAO afrouxa com o settle: linhas do app (JSON) nunca contam, ERROR do Litestream depois do settle conta
$logE = @($logS[0..6]) + @('2026-11-08T10:00:28.500000000Z time=2026-11-08T10:00:28.500Z level=ERROR msg="monitor error" db=/data/studio.sqlite3 replica=s3 error="RequestCanceled"') + @($logS[8])
$eS = P7-ErrosLitestream $logS $true
Ok 'settle: desligamento limpo com settle = 0 erros' ($null -ne $eS -and $eS.Count -eq 0) ($eS -join ' | ')
$eE = P7-ErrosLitestream $logE $true
Ok 'settle: ERROR do Litestream depois do settle continua contando' ($eE.Count -eq 1 -and $eE[0] -match 'monitor error') ($eE -join ' | ')

# -Carga e -Tipos
Ok 'carga: baixa = 1 escritor com 1 s de pausa' ((P7-Carga 'baixa').escritores -eq 1 -and (P7-Carga 'baixa').pausa_ms -eq 1000)
Ok 'carga: normal = 1 escritor sem pausa (07/11)' ((P7-Carga 'normal').escritores -eq 1 -and (P7-Carga 'normal').pausa_ms -eq 0)
Ok 'carga: alta = 3 escritores sem pausa' ((P7-Carga 'alta').escritores -eq 3 -and (P7-Carga 'alta').pausa_ms -eq 0)
$ex = $null; try { P7-Carga 'extrema' | Out-Null } catch { $ex = $_.Exception.Message }
Ok 'carga: valor desconhecido recusado' ($ex -match 'carga invalida') $ex
Ok 'tipos: "a,c" (uma string, como chega do -File) = a, c' (((P7-Tipos @('a,c')) -join '') -eq 'ac')
Ok 'tipos: ordem e repeticao normalizadas (c, A, a) = a, c' (((P7-Tipos @('c', 'A', 'a')) -join '') -eq 'ac')
Ok 'tipos: so "a"' (((P7-Tipos @('a')) -join '') -eq 'a' -and @(P7-Tipos @('a')).Count -eq 1)
Ok 'tipos: padrao a,b,c' (((P7-Tipos @('a', 'b', 'c')) -join '') -eq 'abc')
foreach ($ruim in @(@('b'), @('b,c'), @('x'), @(''))) {
    $ex = $null; try { P7-Tipos $ruim | Out-Null } catch { $ex = $_.Exception.Message }
    Ok "tipos: '$($ruim -join ',')' recusado" ([bool]$ex) $ex
}
$ex = $null; try { P7-Tipos @('b') | Out-Null } catch { $ex = $_.Exception.Message }
Ok 'tipos: "b" sem "a" explica a dependencia' ($ex -match "depende da rodada 'a'") $ex

if ($falhas) { Write-Host "$falhas caso(s) falharam"; exit 1 }
Write-Host 'todos os casos passaram'; exit 0
