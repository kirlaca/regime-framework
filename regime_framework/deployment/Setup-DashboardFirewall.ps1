<#
.SYNOPSIS
    Windows Firewall szabaly letrehozasa/frissitese es ellenorzese a RegimeFramework
    web-dashboardhoz (RegimeFramework_DashboardWeb.exe) -- csak egyetlen ismert IP-rol
    engedi be a portot, UGYANUGY, ahogy az RDP jelenleg is csak egy IP-rol erheto el.

.DESCRIPTION
    NINCS jelszo/token a dashboard alkalmazasban -- a vedelmet KIZAROLAG ez a tuzfalszabaly
    adja. Futtasd a VPS-en, Rendszergazdakent (Adminisztratorkent), MIELOTT publikusan
    elerhetove tennéd a portot.

    A script:
      1. Rendszergazdai jogosultsag ellenorzese (leall, ha nincs).
      2. Ha nem adsz meg -AllowedIP-et, megprobalja automatikusan kiolvasni a mar meglevo
         RDP-szabaly(ok) IP-korlatozasat (Remote Desktop tuzfal-csoport), es UGYANAZT az
         IP-t/CIDR-t hasznalja -- igy nem kell ketszer beirnod.
      3. Letrehozza VAGY frissiti a megadott nevu bejovo szabalyt (TCP, megadott port,
         csak az AllowedIP-rol, Allow).
      4. Ellenorzo blokk: kiirja a vegleges allapotot (engedelyezve/irany/protokoll/port/
         forras-IP), es PASS/FAIL osszegzest ad.
      5. FIGYELMEZTET, hogy ez CSAK a Windows Firewallt allitja be -- ha a VPS egy felho-
         szolgaltatonal fut (Azure/AWS/DigitalOcean/stb.), a szolgaltato SAJAT tuzfalat/
         security groupjat/NSG-jet KULON, ennel a scriptnel kivul kell ugyanigy korlatozni,
         kulonben a felho-oldali szabaly barhonnan beengedne a forgalmat meg akkor is, ha a
         Windows Firewall szukebb.

.PARAMETER Port
    A dashboard portja. Alapertelmezett: 8765 (RegimeFramework_DashboardWeb.exe alapertelmezese).

.PARAMETER AllowedIP
    A publikus IP-cim (vagy CIDR, pl. 203.0.113.10/32), amelyrol a hozzaferest engedelyezni
    akarod. Ha kihagyod, a script megprobalja a meglevo RDP-szabalybol kiolvasni.

.PARAMETER RuleName
    A tuzfalszabaly megjelenitett neve. Alapertelmezett: "RegimeFramework Dashboard Web (<Port>)".

.PARAMETER VerifyOnly
    Ha meg van adva, a script NEM hoz letre/modosit szabalyt, csak ellenorzi es kiirja a
    jelenlegi allapotot.

.PARAMETER Force
    Ha egy azonos nevu szabaly mar letezik ELTERO beallitasokkal, felulirja megerositas nelkul.

.EXAMPLE
    .\Setup-DashboardFirewall.ps1
    Automatikusan kiolvassa az RDP-szabalybol az engedelyezett IP-t, es arra allitja be a
    8765-os portot is.

.EXAMPLE
    .\Setup-DashboardFirewall.ps1 -Port 8765 -AllowedIP "203.0.113.10/32"
    Explicit IP-vel allitja be a szabalyt.

.EXAMPLE
    .\Setup-DashboardFirewall.ps1 -VerifyOnly
    Csak megnezi, mi a jelenlegi allapot, nem valtoztat semmin.
#>

[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$AllowedIP,
    [string]$RuleName,
    [switch]$VerifyOnly,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if (-not $RuleName) {
    $RuleName = "RegimeFramework Dashboard Web ($Port)"
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-RdpAllowedIP {
    <#
        Megprobalja kiolvasni a meglevo RDP (Remote Desktop) bejovo tuzfalszabaly(ok)
        forras-IP-korlatozasat, hogy a dashboard-szabaly UGYANAZT hasznalhassa.
        Nem tobb, csak "best effort" -- ha nem talal egyertelmu, "Any"-tol elteru
        korlatozast, $null-t ad vissza, es a hivo felnek explicit -AllowedIP-et kell adnia.
    #>
    $rdpRules = Get-NetFirewallRule -DisplayGroup "Remote Desktop" -Direction Inbound -Enabled True -ErrorAction SilentlyContinue |
        Where-Object { $_.Action -eq "Allow" }

    if (-not $rdpRules) {
        Write-Warning "Nem talalhato aktiv, engedelyezo RDP-szabaly -- nem tudom automatikusan kikovetkeztetni az IP-t."
        return $null
    }

    $scopes = foreach ($rule in $rdpRules) {
        (Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule).RemoteAddress
    }
    $uniqueScopes = $scopes | Where-Object { $_ -and $_ -ne "Any" } | Select-Object -Unique

    if (-not $uniqueScopes) {
        Write-Warning "A talalt RDP-szabaly(ok) forras-IP-je 'Any' (nincs korlatozva) -- ez a script NEM tudja innen atvenni a szukitest. Add meg explicit -AllowedIP parametert."
        return $null
    }
    if ($uniqueScopes.Count -gt 1) {
        Write-Warning "Tobb, ELTERO IP-korlatozasu RDP-szabalyt talaltam ($($uniqueScopes -join ', ')) -- nem egyertelmu, melyiket hasznaljam. Add meg explicit -AllowedIP parametert."
        return $null
    }
    return $uniqueScopes[0]
}

function Get-RuleState {
    param([string]$Name)
    $rule = Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue
    if (-not $rule) { return $null }
    $addressFilter = Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule
    $portFilter = Get-NetFirewallPortFilter -AssociatedNetFirewallRule $rule
    [PSCustomObject]@{
        Rule          = $rule
        Enabled       = $rule.Enabled
        Direction     = $rule.Direction
        Action        = $rule.Action
        Protocol      = $portFilter.Protocol
        LocalPort     = $portFilter.LocalPort
        RemoteAddress = $addressFilter.RemoteAddress
    }
}

function Write-VerificationReport {
    param([string]$Name, [int]$ExpectedPort, [string]$ExpectedIP)

    Write-Host ""
    Write-Host "--- Ellenorzes: '$Name' ---" -ForegroundColor Cyan
    $state = Get-RuleState -Name $Name

    if (-not $state) {
        Write-Host "  HIANYZIK -- nincs ilyen nevu tuzfalszabaly." -ForegroundColor Red
        return $false
    }

    $checks = @(
        @{ Label = "Engedelyezve";  Ok = ($state.Enabled -eq "True");        Value = $state.Enabled }
        @{ Label = "Irany";         Ok = ($state.Direction -eq "Inbound");   Value = $state.Direction }
        @{ Label = "Muvelet";       Ok = ($state.Action -eq "Allow");        Value = $state.Action }
        @{ Label = "Protokoll";     Ok = ($state.Protocol -eq "TCP");        Value = $state.Protocol }
        @{ Label = "Helyi port";    Ok = ($state.LocalPort -contains "$ExpectedPort" -or $state.LocalPort -eq "$ExpectedPort"); Value = ($state.LocalPort -join ", ") }
        @{ Label = "Forras-IP";     Ok = ($state.RemoteAddress -notcontains "Any" -and ($state.RemoteAddress -join ",") -match [regex]::Escape($ExpectedIP)); Value = ($state.RemoteAddress -join ", ") }
    )

    $allOk = $true
    foreach ($c in $checks) {
        $mark = if ($c.Ok) { "OK" } else { $allOk = $false; "HIBA" }
        $color = if ($c.Ok) { "Green" } else { "Red" }
        Write-Host ("  [{0,-4}] {1,-14}: {2}" -f $mark, $c.Label, $c.Value) -ForegroundColor $color
    }

    if ($state.RemoteAddress -contains "Any") {
        Write-Host "  FIGYELEM: a forras-IP jelenleg 'Any' -- ez azt jelenti, HOGY BARKI eleri a portot!" -ForegroundColor Yellow
    }

    Write-Host ""
    if ($allOk) {
        Write-Host "OSSZESITES: PASS -- a szabaly a varakozas szerint mukodik." -ForegroundColor Green
    } else {
        Write-Host "OSSZESITES: FAIL -- lasd a fenti HIBA sorokat." -ForegroundColor Red
    }
    return $allOk
}

# ------------------------------------------------------------------ main

if (-not (Test-IsAdministrator)) {
    Write-Error "Ez a script Rendszergazdai (Administrator) jogosultsagot igenyel -- inditsd ujra 'Futtatas rendszergazdakent'-tel."
    exit 1
}

if ($VerifyOnly) {
    if (-not $AllowedIP) {
        Write-Host "VerifyOnly mod: nincs -AllowedIP megadva, csak a szabaly letezeset/alapallapotat nezem meg (forras-IP egyezes nem ellenorizheto)." -ForegroundColor Yellow
        $AllowedIP = "*"
    }
    $ok = Write-VerificationReport -Name $RuleName -ExpectedPort $Port -ExpectedIP $AllowedIP
    exit $(if ($ok) { 0 } else { 1 })
}

if (-not $AllowedIP) {
    Write-Host "Nincs -AllowedIP megadva -- probalom kiolvasni a meglevo RDP-szabalybol..."
    $AllowedIP = Get-RdpAllowedIP
    if (-not $AllowedIP) {
        Write-Error "Nem sikerult automatikusan megallapitani az engedelyezett IP-t. Futtasd ujra explicit -AllowedIP '<ip-cim>' parameterrel."
        exit 1
    }
    Write-Host "  -> Az RDP-szabalybol atvett forras-IP: $AllowedIP" -ForegroundColor Green
}

$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($existing) {
    if (-not $Force) {
        Write-Host "Mar letezik '$RuleName' nevu szabaly -- frissitem a beallitasokat (uj port/IP)." -ForegroundColor Yellow
    }
    $existing | Set-NetFirewallRule -Enabled True -Direction Inbound -Action Allow -Profile Any
    $existing | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -RemoteAddress $AllowedIP
    $existing | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol TCP -LocalPort $Port
    Write-Host "Szabaly frissitve: '$RuleName'" -ForegroundColor Green
} else {
    New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $Port -RemoteAddress $AllowedIP -Profile Any | Out-Null
    Write-Host "Uj szabaly letrehozva: '$RuleName'" -ForegroundColor Green
}

$ok = Write-VerificationReport -Name $RuleName -ExpectedPort $Port -ExpectedIP $AllowedIP

Write-Host ""
Write-Host "FONTOS: ez CSAK a Windows Firewallt allitotta be. Ha ez a gep egy felho-VPS" -ForegroundColor Yellow
Write-Host "(Azure/AWS/DigitalOcean/stb.), a szolgaltato SAJAT tuzfalat/security groupjat/NSG-jet" -ForegroundColor Yellow
Write-Host "KULON, ugyanerre az IP-re/portra kell szukitened -- kulonben az onnan johetne barhonnan." -ForegroundColor Yellow

exit $(if ($ok) { 0 } else { 1 })
