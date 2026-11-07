<#
  Funcoes PURAS de avaliacao do passo 7 do ensaio (desligamento sob carga). Sem docker, sem rede: recebem texto/objetos
  e devolvem o veredito. Carregadas por scripts\ensaio_backup.ps1 e testadas em scripts\test_ensaio_backup.ps1.
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

function P7-ErrosLitestream([string[]]$Linhas) {
    # Linhas do docker logs (com ou sem --timestamps). Conta so DEPOIS da linha "SIGTERM: parando" do app (fronteira pelo
    # proprio log, sem comparar relogios). Linhas JSON sao do app; as demais (Litestream/entrypoint) com "error" contam.
    # Sem a linha de SIGTERM: $null (NAO_VERIFICADO).
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
