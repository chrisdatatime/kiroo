<#
  Funcoes PURAS de avaliacao do passo 7 do ensaio (desligamento sob carga). Sem docker, sem rede: recebem texto/objetos
  e devolvem o veredito. Carregadas por scripts\ensaio_backup.ps1 e testadas em scripts\test_ensaio_p7_lib.ps1.
#>

function P7-Readyz([string[]]$Linhas) {
    # Linhas "ticks<TAB>codigo" (codigo = 200 | 503 | ... | sem_conexao), em ordem. 503 "antes de cair" = algum 503
    # antes da primeira sonda sem conexao (ou em qualquer ponto, se a sonda nunca perdeu conexao).
    $cod = @($Linhas | Where-Object { $_ -and $_.Trim() } | ForEach-Object { ($_ -split "`t")[1] })
    $queda = [array]::IndexOf($cod, 'sem_conexao')
    $ate = if ($queda -ge 0) { $queda } else { $cod.Count }
    $antes = $false
    for ($k = 0; $k -lt $ate; $k++) { if ($cod[$k] -eq '503') { $antes = $true; break } }
    $resumo = @(); $ant = $null; $n = 0
    foreach ($c in $cod) { if ($c -eq $ant) { $n++ } else { if ($ant) { $resumo += "${ant}x$n" }; $ant = $c; $n = 1 } }
    if ($ant) { $resumo += "${ant}x$n" }
    return @{ viu503 = ($cod -contains '503'); antes_de_cair = $antes; caiu = ($queda -ge 0); sequencia = ($resumo -join ' > ') }
}

function P7-LitestreamAtivo([string[]]$Linhas, [string]$Geracao) {
    # O Litestream so conta como ATIVO com as duas evidencias: geracao legivel (16 hex, arquivo
    # .studio.sqlite3-litestream/generation) E linha do proprio Litestream no log (versao, "initialized db" ou
    # "replicating to"). Aviso do entrypoint de backup desligado = inativo. Sem as duas: inativo (as assercoes do
    # Litestream ficam NAO_VERIFICADO, nunca 0 nem FAIL).
    $l = @($Linhas | Where-Object { $_ })
    if (@($l | Where-Object { $_ -match 'entrypoint: backup desligado|BACKUP DO BANCO N.O CONFIGURADO' }).Count) {
        return @{ ativo = $false; motivo = 'entrypoint subiu SEM replicacao (variaveis de backup ausentes)' }
    }
    if ("$Geracao".Trim() -notmatch '^[0-9a-f]{16}$') { return @{ ativo = $false; motivo = "geracao do Litestream ausente/ilegivel ('$Geracao')" } }
    $viu = @($l | Where-Object { -not ($_ -replace '^\d{4}-\d\d-\d\dT\S+Z\s', '').TrimStart().StartsWith('{') -and
            $_ -match '(?i)litestream v\d|initialized db|replicating to' }).Count
    if (-not $viu) { return @{ ativo = $false; motivo = 'nenhuma linha do Litestream no log' } }
    return @{ ativo = $true; motivo = '' }
}

function P7-GeracaoNova([string]$Antes, [string]$Depois, [bool]$Ativo) {
    # Depois de um SIGKILL o Litestream precisa abrir geracao nova. So avalia com o Litestream ativo e as duas geracoes
    # lidas; senao NAO_VERIFICADO (nunca FAIL por falta de evidencia).
    if (-not $Ativo) { return @{ resultado = 'NAO_VERIFICADO'; motivo = 'geracao nova do Litestream: NAO_VERIFICADO (Litestream inativo)' } }
    if (-not $Antes -or -not $Depois) { return @{ resultado = 'NAO_VERIFICADO'; motivo = 'geracao nova do Litestream: NAO_VERIFICADO (geracao ilegivel antes ou depois)' } }
    if ($Antes -eq $Depois) { return @{ resultado = 'FAIL'; motivo = "Litestream NAO abriu geracao nova (continua $Antes)" } }
    return @{ resultado = 'PASS'; motivo = '' }
}

function P7-ErrosLitestream([string[]]$Linhas, [bool]$Ativo) {
    # Linhas do docker logs (com ou sem --timestamps). Conta so DEPOIS da linha "SIGTERM: parando" do app (fronteira pelo
    # proprio log, sem comparar relogios). Linhas JSON sao do app; as demais (Litestream/entrypoint) com "error" contam.
    # $null (NAO_VERIFICADO) sem Litestream ativo (zero linhas de erro nao prova nada) ou sem a linha de SIGTERM.
    if (-not $Ativo) { return $null }
    $ini = -1
    for ($k = 0; $k -lt $Linhas.Count; $k++) { if ($Linhas[$k] -match 'SIGTERM: parando') { $ini = $k; break } }
    if ($ini -lt 0) { return $null }
    $err = @()
    for ($k = $ini + 1; $k -lt $Linhas.Count; $k++) {
        $l = $Linhas[$k] -replace '^\d{4}-\d\d-\d\dT\S+Z\s', ''
        if ($l.TrimStart().StartsWith('{')) { continue }
        if ($l -match '(?i)\berror\b') { $err += $Linhas[$k] }
    }
    return , $err
}

function P7-UltimaConfirmada([string[]]$Linhas, [long]$TicksSinal) {
    # Linhas do escritor "n<TAB>codigo<TAB>ticks_utc_da_resposta". Devolve o maior n com 200 recebido ANTES do sinal
    # (antes) e o maior n com 200 em qualquer momento (total). 0 = nenhuma.
    $antes = 0; $total = 0; $ok = 0; $depois = 0
    foreach ($l in $Linhas) {
        $p = $l -split "`t"; if ($p.Count -lt 3) { continue }
        if ($p[1] -ne '200') { continue }
        $n = [int]$p[0]; $ok++
        if ([long]$p[2] -lt $TicksSinal) { if ($n -gt $antes) { $antes = $n } } else { $depois++ }
        if ($n -gt $total) { $total = $n }
    }
    return @{ antes = $antes; total = $total; confirmadas = $ok; confirmadas_depois_do_sinal = $depois }
}

function P7-Escritas([string[]]$Linhas, [long]$TicksSinal, [string[]]$Log, [string]$Prefixo) {
    # Cadastros do escritor: linhas "n<TAB>codigo<TAB>ticks_resposta[<TAB>ticks_envio]" (ticks UTC do cliente).
    # Classifica cada escrita CONFIRMADA (200) em relacao ao SIGTERM de dois jeitos:
    #   servidor: a linha "E-mail para <email>" do app vem antes ou depois da linha "SIGTERM: parando" no MESMO log
    #             (mesmo processo, sem comparar relogios) -> antes | depois | sem_log (linha nao achada);
    #   cliente : resposta antes do sinal -> antes; envio depois do sinal -> depois; envio antes e resposta depois -> em_voo.
    # Devolve so as confirmadas: {n, email, envio, resposta, cliente, servidor}.
    $iSig = -1; $pos = @{}
    $re = 'E-mail para (' + [regex]::Escape($Prefixo) + '\d+@ensaio\.test)'
    for ($k = 0; $k -lt $Log.Count; $k++) {
        if ($iSig -lt 0 -and $Log[$k] -match 'SIGTERM: parando') { $iSig = $k; continue }
        if ($Log[$k] -match $re -and -not $pos.ContainsKey($Matches[1])) { $pos[$Matches[1]] = $k }
    }
    $out = @()
    foreach ($l in $Linhas) {
        $p = "$l" -split "`t"; if ($p.Count -lt 3 -or $p[1] -ne '200') { continue }
        $n = [int]$p[0]; $resp = [long]$p[2]; $snd = $null; if ($p.Count -ge 4 -and $p[3]) { $snd = [long]$p[3] }
        $cli = if ($resp -lt $TicksSinal) { 'antes' } elseif ($null -ne $snd -and $snd -ge $TicksSinal) { 'depois' } else { 'em_voo' }
        $email = "$Prefixo$n@ensaio.test"
        $srv = if ($iSig -lt 0 -or -not $pos.ContainsKey($email)) { 'sem_log' } elseif ($pos[$email] -lt $iSig) { 'antes' } else { 'depois' }
        $out += [pscustomobject]@{ n = $n; email = $email; envio = $snd; resposta = $resp; cliente = $cli; servidor = $srv }
    }
    return , $out
}

function P7-Ausentes($Aceitas, [string[]]$Presentes) {
    # Toda escrita aceita (200) precisa estar no banco. Devolve os e-mails ausentes (vazio = todas presentes).
    $set = @{}; foreach ($e in @($Presentes)) { if ($e) { $set[$e.Trim().ToLowerInvariant()] = 1 } }
    $f = @(); foreach ($a in @($Aceitas)) { if (-not $set.ContainsKey($a.email.ToLowerInvariant())) { $f += $a.email } }
    return , $f
}

function P7-Tsv($Escritas) {
    # Registro legivel (sem credenciais: so ids de teste e horarios UTC do cliente).
    $l = @("n`temail`tenvio_utc`tresposta_utc`tcliente`tservidor")
    foreach ($e in @($Escritas)) {
        $ev = if ($null -ne $e.envio) { ([DateTime]::new([long]$e.envio, 'Utc')).ToString('HH:mm:ss.fff') } else { '' }
        $l += "{0}`t{1}`t{2}`t{3}`t{4}`t{5}" -f $e.n, $e.email, $ev, ([DateTime]::new([long]$e.resposta, 'Utc')).ToString('HH:mm:ss.fff'), $e.cliente, $e.servidor
    }
    return , $l
}

function P7-Tentativas($Antes, $Depois) {
    # Tudo o que estava confirmado em $Antes continua igual em $Depois: mesmo id, tipo, cena, numero, hash de entrada,
    # criacao e (se ja existia) a mesma operacao remota. Devolve a lista de diferencas (vazia = igual).
    $dif = @()
    $idx = @{}; foreach ($d in @($Depois)) { $idx[$d.id] = $d }
    foreach ($a in @($Antes)) {
        if (-not $idx.ContainsKey($a.id)) { $dif += "- tentativa $($a.id) ($($a.kind) cena $($a.scene_idx) #$($a.attempt_no)) SUMIU"; continue }
        $d = $idx[$a.id]
        foreach ($c in @('kind', 'scene_idx', 'attempt_no', 'input_hash', 'created_at')) {
            if ("$($a.$c)" -ne "$($d.$c)") { $dif += "~ $($a.id).${c}: '$($a.$c)' -> '$($d.$c)'" }
        }
        if ($a.remote_op_id -and "$($a.remote_op_id)" -ne "$($d.remote_op_id)") {
            $dif += "~ $($a.id).remote_op_id: '$($a.remote_op_id)' -> '$($d.remote_op_id)' (operacao remota trocada)"
        }
    }
    return , $dif
}

function P7-Repetidas($Antes, $Depois) {
    # Etapa registrada repetida: tentativa NOVA (id ausente em $Antes) para a mesma cena+tipo de uma tentativa que em $Antes
    # ja tinha terminado com sucesso (succeeded, nao substituida) ou ja estava enviada (submitted = operacao em andamento,
    # reenviar seria pagar de novo). Tambem acusa (cena, tipo, numero) duplicado em $Depois.
    $rep = @()
    $ids = @{}; foreach ($a in @($Antes)) { $ids[$a.id] = $a }
    foreach ($n in @($Depois)) {
        if ($ids.ContainsKey($n.id)) { continue }
        foreach ($a in @($Antes)) {
            if ($a.kind -eq $n.kind -and "$($a.scene_idx)" -eq "$($n.scene_idx)" -and [int]$a.superseded -eq 0 -and $a.status -in @('succeeded', 'submitted')) {
                $rep += "+ $($n.id) ($($n.kind) cena $($n.scene_idx) #$($n.attempt_no)) repete $($a.id) que ja estava $($a.status)"
            }
        }
    }
    $vistos = @{}
    foreach ($d in @($Depois)) {
        $k = "$($d.kind)|$($d.scene_idx)|$($d.attempt_no)"
        if ($vistos.ContainsKey($k)) { $rep += "= ($($d.kind) cena $($d.scene_idx) #$($d.attempt_no)) duplicada: $($vistos[$k]) e $($d.id)" } else { $vistos[$k] = $d.id }
    }
    return , $rep
}

function P7-Veredito([string[]]$Falhas, [string[]]$NaoVerificado) {
    if ($Falhas.Count) { return 'FAIL' }
    if ($NaoVerificado.Count) { return 'NAO_VERIFICADO' }
    return 'PASS'
}

# ------------------------------------------------------------------ WAL no fechamento x erro do Litestream
# Hipotese medida: o erro "checkpoint: mode=... err=release read lock: context canceled" no desligamento acontece se e
# so se o WAL tiver >= 1000 paginas quando o Litestream fecha o banco. Base no codigo do Litestream v0.3.13:
#   litestream.go  WALHeaderSize = 32; WALFrameHeaderSize = 24
#                  func calcWALSize(pageSize int, n int) int64 { return int64(WALHeaderSize + ((WALFrameHeaderSize + pageSize) * n)) }
#   db.go          DefaultMinCheckpointPageN = 1000
#                  (DB.Sync) } else if newWALSize >= calcWALSize(db.pageSize, db.MinCheckpointPageN) { checkpoint = true
# DB.Close cancela db.ctx e faz um Sync final; se esse Sync faz checkpoint, execCheckpoint reabre o read lock com
# tx.ExecContext(db.ctx) ja cancelado e o erro sai embrulhado como "release read lock: context canceled".

$P7_LIMITE_PAGINAS = 1000   # DefaultMinCheckpointPageN do Litestream v0.3.13 (litestream.yml nao muda)

function P7-Campo($O, [string]$K) {
    # Le um campo de hashtable/ordered ou de objeto (JSON) sem quebrar no StrictMode quando ele falta.
    if ($null -eq $O) { return $null }
    if ($O -is [System.Collections.IDictionary]) { if ($O.Contains($K)) { return $O[$K] }; return $null }
    $p = $O.PSObject.Properties[$K]; if ($p) { return $p.Value }; return $null
}

function P7-LimiteWal([int]$PageSize, [int]$Paginas = $P7_LIMITE_PAGINAS) {
    # calcWALSize do Litestream: tamanho, em bytes, de um WAL com $Paginas quadros.
    return [long](32 + ([long]$PageSize + 24) * $Paginas)
}

function P7-PaginasWal($Bytes, $PageSize) {
    # Quadros inteiros num WAL de $Bytes (cabecalho de 32 bytes; cada quadro = 24 + page_size). $null sem dado valido.
    if ($null -eq $Bytes -or "$Bytes" -eq '' -or $null -eq $PageSize -or [int]$PageSize -lt 512) { return $null }
    $b = [long]$Bytes
    if ($b -le 32) { return [long]0 }
    return [long][math]::Floor(($b - 32) / ([long]$PageSize + 24))
}

function P7-Utc([string]$T) {
    # Horario RFC 3339 (docker logs --timestamps, docker inspect) -> 'yyyy-MM-ddTHH:mm:ss.fffZ' (UTC, ms). $null se ilegivel.
    if ("$T" -notmatch '(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?Z') { return $null }
    $f = "$($Matches[2])".PadRight(3, '0').Substring(0, 3)
    return "$($Matches[1]).${f}Z"
}

function P7-Seg([string]$De, [string]$Ate) {
    # Segundos de $De ate $Ate (dois horarios de P7-Utc). $null se faltar algum.
    if (-not $De -or -not $Ate) { return $null }
    $fmt = 'yyyy-MM-ddTHH:mm:ss.fffZ'; $ci = [Globalization.CultureInfo]::InvariantCulture
    $st = [Globalization.DateTimeStyles]::AdjustToUniversal -bor [Globalization.DateTimeStyles]::AssumeUniversal
    return [math]::Round(([DateTime]::ParseExact($Ate, $fmt, $ci, $st) - [DateTime]::ParseExact($De, $fmt, $ci, $st)).TotalSeconds, 3)
}

function P7-WalDoLog([string[]]$Linhas) {
    # Ultimo 'wal segment written' do Litestream: position=<geracao>/<indice>:<offset> e sz=<bytes>. O fim do segmento
    # (offset + sz) e o tamanho do WAL-sombra daquele indice depois do ultimo envio. $null se nao houver.
    $u = $null
    foreach ($l in @($Linhas)) {
        if ("$l" -match 'msg="wal segment written".*\bposition=([0-9a-f]{16})/([0-9a-f]{8}):(\d+).*\bsz=(\d+)') {
            $u = @{ geracao = $Matches[1]; indice = $Matches[2]; bytes = [long]$Matches[3] + [long]$Matches[4] }
        }
    }
    return $u
}

function P7-ErroCheckpoint($Erros) {
    # O erro da hipotese entre as linhas ERROR do Litestream depois do SIGTERM. $null (NAO_VERIFICADO) se elas nao foram
    # contadas (Litestream inativo ou sem linha de SIGTERM).
    if ($null -eq $Erros) { return $null }
    return [bool](@($Erros | Where-Object { "$_" -match 'checkpoint: mode=\w+ err=release read lock: context canceled' }).Count)
}

function P7-Marcos([string[]]$Linhas, $Erros) {
    # Horarios (UTC, do relogio do Docker) dos marcos do desligamento no log do container (docker logs --timestamps).
    # settle_ini/settle_fim: eventos JSON do app (janela de assentamento, src/studio/shutdown.py).
    $m = [ordered]@{ signal_ls = $null; sigterm_app = $null; interrompidas = $null; settle_ini = $null; settle_fim = $null; ls_shutdown = $null; erros = @() }
    $pad = [ordered]@{ signal_ls = 'signal received, litestream shutting down'; sigterm_app = 'SIGTERM: parando';
        interrompidas = 'marcadas como interrompidas'; settle_ini = '"event": "settle_start"'; settle_fim = '"event": "settle_end"';
        ls_shutdown = 'litestream shut down' }
    foreach ($l in @($Linhas)) {
        foreach ($k in @($pad.Keys)) { if (-not $m[$k] -and "$l".Contains($pad[$k])) { $m[$k] = P7-Utc ("$l" -split '\s', 2)[0] } }
    }
    foreach ($e in @($Erros)) {
        if (-not $e) { continue }
        $msg = if ("$e" -match 'msg="([^"]+)"') { $Matches[1] } else { 'error' }
        $m.erros += "$(P7-Utc ("$e" -split '\s', 2)[0]) $msg"
    }
    return $m
}

function P7-LinhaDoTempo($Marcos, [string]$Stop, [string]$Finished) {
    # Uma linha: horario do docker stop (relogio do Windows) e, relativo ao "signal received" do Litestream (relogio do
    # Docker), cada marco do log e o fim do container. Os dois relogios podem divergir alguns ms.
    $ref = $Marcos.signal_ls
    $p = @("stop=$(if ($Stop) { $Stop } else { '?' })", "signal_ls=$(if ($ref) { $ref } else { '?' })")
    $ci = [Globalization.CultureInfo]::InvariantCulture   # ponto decimal, independente da cultura do Windows
    $rel = { param($t) if (-not $t) { '?' } elseif (-not $ref) { $t } else { [string]::Format($ci, '{0:+0.000;-0.000} s', (P7-Seg $ref $t)) } }
    foreach ($k in @('sigterm_app', 'interrompidas', 'settle_ini', 'settle_fim', 'ls_shutdown')) { $p += "$k=$(& $rel (P7-Campo $Marcos $k))" }
    foreach ($e in @($Marcos.erros)) { $t, $msg = "$e" -split ' ', 2; $p += "ERROR($msg)=$(& $rel $t)" }
    $p += "finished=$(& $rel $Finished)"
    return ($p -join ' | ')
}

function P7-Settle([string[]]$Linhas) {
    # Janela de assentamento do app (STUDIO_SHUTDOWN_SETTLE_S), lida dos eventos JSON do log do container:
    #   settle_start / settle_end (com settle_s, duration_ms, interrupted) ou settle_skipped (settle = 0).
    # settle_s = $null quando nao ha nenhum desses eventos (imagem antiga, sem o settle, ou o app nao chegou ao fim da drenagem).
    $o = [ordered]@{ settle_s = $null; inicio = $null; fim = $null; duracao_s = $null; interrompido = $null; estado = 'ausente' }
    foreach ($l in @($Linhas)) {
        $t = "$l"
        if ($t -notmatch '"event":\s*"settle_(start|end|skipped)"') { continue }
        $ev = $Matches[1]
        $ts = P7-Utc ($t -split '\s', 2)[0]
        $ss = if ($t -match '"settle_s":\s*(-?[0-9.]+)') { [double]::Parse($Matches[1], [Globalization.CultureInfo]::InvariantCulture) } else { $null }
        switch ($ev) {
            'skipped' { $o.settle_s = [double]0; $o.duracao_s = [double]0; $o.estado = 'desativado' }
            'start' { if (-not $o.inicio) { $o.inicio = $ts }; if ($null -ne $ss) { $o.settle_s = $ss }; $o.estado = 'sem_fim' }
            'end' {
                $o.fim = $ts; if ($null -ne $ss) { $o.settle_s = $ss }
                if ($t -match '"duration_ms":\s*([0-9.]+)') { $o.duracao_s = [math]::Round([double]::Parse($Matches[1], [Globalization.CultureInfo]::InvariantCulture) / 1000, 3) }
                if ($t -match '"interrupted":\s*(true|false)') { $o.interrompido = ($Matches[1] -eq 'true') }
                $o.estado = if ($o.interrompido) { 'interrompido' } else { 'completo' }
            }
        }
    }
    return $o
}

function P7-SettleTexto($S) {
    # Uma linha legivel do settle de uma rodada.
    switch ($S.estado) {
        'ausente' { return 'ausente (nenhum evento settle_* no log: imagem sem o settle?)' }
        'desativado' { return 'desativado (STUDIO_SHUTDOWN_SETTLE_S=0)' }
        'sem_fim' { return "$($S.settle_s) s, iniciado as $($S.inicio) e SEM settle_end (processo morto antes do fim?)" }
        default { return "$($S.settle_s) s, durou $($S.duracao_s) s$(if ($S.interrompido) { ', INTERROMPIDO por segundo sinal' })" }
    }
}

function P7-SettleResumo($Rodadas) {
    # "settle_s: 3 em a1, a2 / ausente em a3" (agrupa as rodadas pelo valor).
    $g = [ordered]@{}
    foreach ($r in @($Rodadas | Where-Object { $_ })) {
        $v = P7-Campo $r 'settle_s'; $k = if ($null -eq $v -or "$v" -eq '') { 'ausente' } else { "$v" }
        if (-not $g.Contains($k)) { $g[$k] = @() }
        $g[$k] += "$(P7-Campo $r 'rodada')"
    }
    if (-not $g.Count) { return 'settle_s: sem rodadas' }
    return 'settle_s: ' + (($g.Keys | ForEach-Object { "$_ em $($g[$_] -join ', ')" }) -join ' / ')
}

function P7-EscolheWal($Sonda, $DoLog) {
    # Tamanho do WAL no FECHAMENTO, por ordem de confianca:
    #   sombra  = ultimo indice do WAL-sombra do Litestream no volume parado (copiado no Sync final do DB.Close);
    #   log     = fim do ultimo 'wal segment written' (o mesmo dado, visto pelo envio);
    #   arquivo = o studio.sqlite3-wal no volume parado. Pouco confiavel: o SQLite costuma APAGAR o -wal quando a ultima
    #             conexao fecha, e depois de um reinicio do WAL o arquivo guarda o tamanho maximo, nao o conteudo atual.
    $sb = P7-Campo $Sonda 'sombra_bytes'; $wa = P7-Campo $Sonda 'wal_arquivo_bytes'
    if ($null -ne $sb) { return @{ bytes = [long]$sb; fonte = 'sombra' } }
    if ($DoLog) { return @{ bytes = [long]$DoLog.bytes; fonte = 'log' } }
    if ($null -ne $wa) { return @{ bytes = [long]$wa; fonte = 'arquivo' } }
    return @{ bytes = $null; fonte = 'nenhuma' }
}

function P7-Hipotese($WalBytes, $PageSize, $ErroCheckpoint, [int]$LimitePaginas = $P7_LIMITE_PAGINAS) {
    # Previsto: erro de checkpoint no fechamento  <=>  wal_bytes >= calcWALSize(page_size, 1000).
    # classe: consistente | contraexemplo | indeterminada (falta WAL, page_size ou contagem de erros).
    $pg = P7-PaginasWal $WalBytes $PageSize
    $lim = if ($null -ne $PageSize -and [int]$PageSize -ge 512) { P7-LimiteWal ([int]$PageSize) $LimitePaginas } else { $null }
    $o = [ordered]@{ paginas = $pg; limite_paginas = $LimitePaginas; limite_bytes = $lim; previsto = $null; observado = $ErroCheckpoint; classe = 'indeterminada'; motivo = '' }
    if ($null -eq $pg -or $null -eq $lim) { $o.motivo = 'WAL ou page_size desconhecido'; return $o }
    if ($null -eq $ErroCheckpoint) { $o.motivo = 'erros do Litestream NAO_VERIFICADO'; return $o }
    $o.previsto = ([long]$WalBytes -ge $lim)
    if ($o.previsto -eq [bool]$ErroCheckpoint) { $o.classe = 'consistente'; return $o }
    $o.classe = 'contraexemplo'
    $o.motivo = if ($o.previsto) { "WAL com $pg paginas (>= $LimitePaginas) e SEM erro de checkpoint" } else { "erro de checkpoint com WAL de $pg paginas (< $LimitePaginas)" }
    return $o
}

function P7-Conclusao($Rodadas) {
    # "hipotese consistente em N de M rodadas / contraexemplos: ..." (M exclui as indeterminadas, listadas a parte).
    $x = @($Rodadas | Where-Object { $_ })
    $con = @($x | Where-Object { (P7-Campo $_ 'hipotese') -eq 'consistente' })
    $ctr = @($x | Where-Object { (P7-Campo $_ 'hipotese') -eq 'contraexemplo' })
    $ind = @($x | Where-Object { (P7-Campo $_ 'hipotese') -notin @('consistente', 'contraexemplo') })
    $t = "hipotese consistente em $($con.Count) de $($con.Count + $ctr.Count) rodadas / contraexemplos: "
    $mot = { param($r) $m = P7-Campo $r 'hipotese_motivo'; if ($m) { "$m" } else { 'sem medicao' } }
    $t += if ($ctr.Count) { ($ctr | ForEach-Object { "$(P7-Campo $_ 'rodada') ($(& $mot $_))" }) -join '; ' } else { 'nenhum' }
    if ($ind.Count) { $t += ' / indeterminadas: ' + (($ind | ForEach-Object { "$(P7-Campo $_ 'rodada') ($(& $mot $_))" }) -join '; ') }
    return $t
}

function P7-Tabela($Rodadas) {
    # Tabela final das rodadas "a" (texto de largura fixa para o log).
    $f = '{0,-6} {1,-7} {2,10} {3,-8} {4,8} {5,8} {6,5} {7,8} {8,10} {9,-14} {10}'
    $l = @(($f -f 'rodada', 'carga', 'wal_bytes', 'fonte', 'wal_pag', 'limite', 'saida', 'settle_s', 'erros_ls', 'resultado', 'hipotese'))
    foreach ($r in @($Rodadas | Where-Object { $_ })) {
        $v = { param($k) $x = P7-Campo $r $k; if ($null -eq $x -or "$x" -eq '') { '?' } else { "$x" } }
        $el = & $v 'erros_litestream'; if ($el -like 'NAO_VERIFICADO*') { $el = 'NAO_VERIF' }
        $l += ($f -f (& $v 'rodada'), (& $v 'carga'), (& $v 'wal_bytes'), (& $v 'wal_fonte'), (& $v 'wal_paginas'), (& $v 'limite_paginas'),
            (& $v 'saida'), (& $v 'settle_s'), $el, (& $v 'resultado'), (& $v 'hipotese'))
    }
    return , $l
}

function P7-Carga([string]$Nivel) {
    # So o ritmo dos cadastros do ensaio (o servidor nao muda): escritores em paralelo e pausa entre cadastros.
    switch ($Nivel) {
        'baixa' { return @{ escritores = 1; pausa_ms = 1000 } }
        'normal' { return @{ escritores = 1; pausa_ms = 0 } }
        'alta' { return @{ escritores = 3; pausa_ms = 0 } }
        default { throw "carga invalida: '$Nivel' (baixa | normal | alta)" }
    }
}

function P7-Tipos([string[]]$Tipos) {
    # -Tipos: aceita 'a','c' ou 'a,c' (powershell -File entrega "a,c" como UMA string). b depende do volume de a.
    $t = @(@($Tipos) | ForEach-Object { "$_" -split '[,\s]+' } | Where-Object { $_ } | ForEach-Object { $_.ToLowerInvariant() } | Select-Object -Unique)
    if (-not $t.Count) { throw '-Tipos vazio (use a, b e/ou c)' }
    foreach ($x in $t) { if ($x -notin @('a', 'b', 'c')) { throw "-Tipos invalido: '$x' (use a, b e/ou c)" } }
    if ($t -contains 'b' -and $t -notcontains 'a') { throw "-Tipos recusado: 'b' (reinicio no mesmo volume) depende da rodada 'a'; use -Tipos a,b" }
    return , @(@('a', 'b', 'c') | Where-Object { $t -contains $_ })
}
