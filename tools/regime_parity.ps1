<#
  regime_parity.ps1 -- a két élő EA (IC USTEC, Pepperstone NAS100) rezsim-besorolásának bárónkénti naplózása.
  Forrás: D:\XM\production\tools\regime_parity\ ; kiadás: releases/regime_parity/<dátum>/.
  Futtatás: ütemezett feladat percenként, SYSTEM fiókként (a vps_check mintájára).

  Cél (2026-09-29, A javaslata, a felhasználó döntése): a Pepperstone (RF_TF_EA) vs IC (v2.01) párhuzam
  kiegészítéseként mérni, hány bárnál tér el a két terminál rezsimje — a C7-ablakban (az IC 2026-09-29 00:19-es
  újraindítása után ~2026-10-09-ig) és utána (feed-alapszint).

  Működés: csak OLVASSA a két heartbeat-fájlt (FileShare.ReadWrite, az EA írhatja közben). Ha a két bár-idő
  (a Pepperstone-é -OffsetMinutes-szel eltolva) azonos, és ezt a bárt még nem naplóztuk, egy sort fűz a CSV-hez.
  A kereskedést, az EA-kat és a terminálokat nem érinti.
  A-kritika (2026-09-29): J1 -- félig írt heartbeat (az EA csonkolva újraírja) ne adjon hamis eltérést: csak
  mind a 4 mező kitöltött, ismert értékével ír; J2 -- eltérő szerveridő ne okozzon néma kiesést: a bár-idő
  eltérését (percben) diag-sorba írja, ha változott, és munkamenet közben 30 perc sor nélkül -> hibasor.
  A munkamenet (16:30-23:50) az IC (master) szerveridejével értendő.
#>
param([string]$OutDir = 'C:\MT5-Demo\MONITOR\regime_parity',
      [string]$CommonDir = 'C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\Common\Files',
      [int]$OffsetMinutes = 0)

$ErrorActionPreference = 'Stop'
$Files = [ordered]@{ ic = 'RegimeFramework_heartbeat_USTEC_101001.txt'; pep = 'RegimeFramework_heartbeat_NAS100_101001.txt' }
$Csv = Join-Path $OutDir 'regime_parity.csv'
$ErrLog = Join-Path $OutDir 'regime_parity_errors.log'
$Diag = Join-Path $OutDir 'regime_parity_diag.log'
$StateFile = Join-Path $OutDir 'regime_parity_state.txt'
$Known = @('TRENDING', 'TRANSITIONAL', 'RANGING', 'UNKNOWN')
$Fmt = 'yyyy.MM.dd HH:mm:ss'

function Read-Heartbeat([string]$path) {
  $fs = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
  try { $txt = (New-Object IO.StreamReader($fs, [Text.Encoding]::Default)).ReadToEnd() } finally { $fs.Close() }
  $kv = @{}
  foreach ($line in ($txt -split "`r?`n")) { $i = $line.IndexOf('='); if ($i -gt 0) { $kv[$line.Substring(0, $i)] = $line.Substring($i + 1).Trim() } }
  return $kv
}
function Log-Err([string]$m) { Add-Content -Path $ErrLog -Value ("[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $m) -Encoding UTF8 }
function Get-State { $s = @{}; if (Test-Path $StateFile) { foreach ($l in Get-Content $StateFile) { $i = $l.IndexOf('='); if ($i -gt 0) { $s[$l.Substring(0, $i)] = $l.Substring($i + 1) } } }; return $s }
function Save-State($s) { Set-Content -Path $StateFile -Value ($s.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -Encoding ASCII }
function In-Session([datetime]$t) { $m = $t.Hour * 60 + $t.Minute; return ($m -ge 990 -and $m -le 1430) }   # 16:30-23:50 (IC szerveridő)

try {
  if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }
  $hb = @{}
  foreach ($k in $Files.Keys) { $hb[$k] = Read-Heartbeat (Join-Path $CommonDir $Files[$k]) }
  # J1: félig írt fájl -> most semmit, a következő perc újrapróbálja
  foreach ($k in $Files.Keys) {
    if (-not $hb[$k]['last_bar_time'] -or -not $hb[$k]['current_vol_band'] -or ($Known -notcontains $hb[$k]['current_regime'])) { exit 0 }
  }
  $icBar = [datetime]::ParseExact($hb.ic['last_bar_time'], $Fmt, $null)
  $pepBar = [datetime]::ParseExact($hb.pep['last_bar_time'], $Fmt, $null).AddMinutes(-$OffsetMinutes)
  $state = Get-State
  # J2a: a bár-idő eltérése (percben) -- csak változáskor naplózva
  $diffMin = [int]($pepBar - $icBar).TotalMinutes
  if ("$diffMin" -ne $state['last_diff']) {
    Add-Content -Path $Diag -Value ("[{0:yyyy-MM-dd HH:mm:ss}] bar-ido elteres (pep-offset - ic) = {1} perc (ic {2}, pep {3}, offset {4})" -f `
      (Get-Date), $diffMin, $hb.ic['last_bar_time'], $hb.pep['last_bar_time'], $OffsetMinutes) -Encoding ASCII
    $state['last_diff'] = "$diffMin"; Save-State $state
  }
  # J2b: munkamenet közben 30 perc sor nélkül -> hibasor (bárónként egyszer)
  $lastLogged = $null
  if (Test-Path $Csv) { $tail = Get-Content $Csv -Tail 1; if ($tail -and $tail -notlike 'bar_time*') { $lastLogged = [datetime]::ParseExact($tail.Split(',')[0], $Fmt, $null) } }
  if ($lastLogged -and (In-Session $icBar) -and ($icBar - $lastLogged).TotalMinutes -gt 30 -and $state['gap_flag'] -ne $hb.ic['last_bar_time']) {
    Log-Err ("30 percnel regebben nincs uj sor munkamenet kozben (utolso {0:yyyy.MM.dd HH:mm}, IC bar {1}, bar-ido elteres {2} perc)" -f $lastLogged, $hb.ic['last_bar_time'], $diffMin)
    $state['gap_flag'] = $hb.ic['last_bar_time']; Save-State $state
  }
  if ($diffMin -ne 0) { exit 0 }                                    # még nem ugyanazon a báron
  if ($lastLogged -and $lastLogged -eq $icBar) { exit 0 }            # ezt a bárt már naplóztuk
  if (-not (Test-Path $Csv)) {
    Set-Content -Path $Csv -Value 'bar_time,ic_regime,pep_regime,ic_vol,pep_vol,same_regime,logged_at' -Encoding ASCII
  }
  $same = [int]($hb.ic['current_regime'] -eq $hb.pep['current_regime'])
  $row = '{0},{1},{2},{3},{4},{5},{6:yyyy-MM-dd HH:mm:ss}' -f $hb.ic['last_bar_time'], $hb.ic['current_regime'], $hb.pep['current_regime'],
         $hb.ic['current_vol_band'], $hb.pep['current_vol_band'], $same, (Get-Date)
  Add-Content -Path $Csv -Value $row -Encoding ASCII
} catch {
  Log-Err $_.Exception.Message
  exit 1
}
