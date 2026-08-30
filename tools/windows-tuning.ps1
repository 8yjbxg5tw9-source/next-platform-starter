<#
.SYNOPSIS
  Windows tarafinda oyun gecikmesini (jitter) artiran ayarlari kapatir.

.DESCRIPTION
  Bu betik ping'i "sihirli" sekilde dusurmez. Yaptigi sey, senin kontrolunde olan
  ve gereksiz yere gecikme ekleyen Windows davranislarini kapatmak:

    1. Wi-Fi adaptorunun guc tasarrufu icin kendini kapatmasi  -> ani 30-200 ms sicismalari
    2. Gucl planinda "Kablosuz Bagdastirici Ayari" -> Güç Tasarrufu Modu -> Maksimum Performans
    3. Receive Segment Coalescing (RSC) -> paketleri biriktirip gecikme ekler
    4. MMCSS ag kisitlamasi (NetworkThrottlingIndex / SystemResponsiveness)
    5. Game DVR arka plan kaydi
    6. Delivery Optimization (Windows Update P2P) -> evdeki hatti doyurur, bufferbloat yapar

  Butun degisiklikler geri alinabilir:  .\windows-tuning.ps1 -Undo
  Once ne yapacagini gormek icin:      .\windows-tuning.ps1 -DryRun
  Once/sonra karsilastirmasi icin:     .\windows-tuning.ps1 -Report

.NOTES
  Yonetici olarak calistirilmali. Ag ayarlarini degistirir; ethernet/Wi-Fi kisa
  bir an kesilebilir. Oyun kapaliyken calistir.
#>

#Requires -RunAsAdministrator
[CmdletBinding()]
param(
  [switch]$DryRun,
  [switch]$Undo,
  [switch]$Report
)

$ErrorActionPreference = 'Continue'

function Write-Step {
  param([string]$Msg)
  Write-Host "  -> $Msg" -ForegroundColor DarkCyan
}

function Apply {
  param([string]$What, [scriptblock]$Action)
  if ($DryRun) {
    Write-Step "[DRYRUN] $What"
    return
  }
  try {
    & $Action
    Write-Step "$What  [OK]"
  }
  catch {
    Write-Host "  !! $What  [ATLANDI] $($_.Exception.Message)" -ForegroundColor Yellow
  }
}

function Show-Report {
  Write-Host "`n=== MEVCUT DURUM ===" -ForegroundColor Cyan

  $mm = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile'
  if (Test-Path $mm) {
    $p = Get-ItemProperty -Path $mm
    Write-Host ("NetworkThrottlingIndex : {0}   (0xffffffff = kisitlama kapali)" -f $p.NetworkThrottlingIndex)
    Write-Host ("SystemResponsiveness   : {0}   (10 = oyunlara daha cok pay)" -f $p.SystemResponsiveness)
  }

  try {
    Get-NetAdapterRsc -ErrorAction Stop |
      Select-Object Name, IPv4Enabled, IPv6Enabled |
      Format-Table -AutoSize | Out-Host
  } catch { Write-Host 'RSC bilgisi alinamadi.' }

  try {
    Get-NetAdapter -Physical -ErrorAction Stop |
      Where-Object { $_.Status -eq 'Up' } |
      ForEach-Object {
        $pm = $_ | Get-NetAdapterPowerManagement -ErrorAction SilentlyContinue
        Write-Host ("Adaptor '{0}': AllowComputerToTurnOffDevice = {1}" -f $_.Name, $pm.AllowComputerToTurnOffDevice)
      }
  } catch { Write-Host 'Adaptor guc yonetimi bilgisi alinamadi.' }

  Write-Host "`n=== FRANKFURT TABAN OLCUMU (100 istek) ===" -ForegroundColor Cyan
  $target = 's3.eu-central-1.amazonaws.com'
  try {
    $r = Test-Connection -ComputerName $target -Count 100 -ErrorAction Stop
    $times = $r | ForEach-Object { $_.ResponseTime } | Sort-Object
    $avg = ($times | Measure-Object -Average).Average
    Write-Host ("min = {0} ms   ort = {1} ms   max = {2} ms   n = {3}" -f `
      $times[0], [math]::Round($avg, 1), $times[-1], $times.Count)
    Write-Host "min degeri senin fiziksel tabanin. Onemli olan max-min farki (jitter)."
  } catch {
    Write-Host "Olculemedi: $($_.Exception.Message)"
    Write-Host 'ICMP (ping) engellenmis olabilir. Ping Lab sayfasindaki HTTP olcumunu kullan.'
  }
}

function Set-Registry {
  param([string]$Path, [string]$Name, $Value, [string]$Type = 'DWord')
  if (-not (Test-Path $Path)) { New-Item -Path $Path -Force | Out-Null }
  New-ItemProperty -Path $Path -Name $Name -Value $Value -PropertyType $Type -Force | Out-Null
}

if ($Report) { Show-Report; return }

$verb = if ($Undo) { 'GERI ALINIYOR' } else { 'UYGULANIYOR' }
Write-Host "`n=== WINDOWS GECIKME AYARLARI - $verb ===" -ForegroundColor Cyan
if ($DryRun) { Write-Host '(DryRun: hicbir sey degistirilmeyecek)' -ForegroundColor Yellow }

# 1. Wi-Fi/Ethernet adaptorlerinin guc tasarrufu icin kapanmasi
Apply 'Adaptor guc tasarrufu (kendi kendini kapatma) -> Disabled' {
  $adapters = Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' }
  foreach ($a in $adapters) {
    if ($Undo) {
      Set-NetAdapterPowerManagement -Name $a.Name -AllowComputerToTurnOffDevice Enabled -ErrorAction SilentlyContinue
    } else {
      Set-NetAdapterPowerManagement -Name $a.Name -AllowComputerToTurnOffDevice Disabled -ErrorAction SilentlyContinue
    }
  }
}

# 2. Guc plani: kablosuz bagdastirici -> Maksimum Performans (0)
#    GUID: 19cbb8fa-... = Wireless Adapter Settings, 12bbebe6-... = Power Saving Mode
Apply 'Guc plani: kablosuz adaptur -> Maksimum Performans' {
  $val = if ($Undo) { 1 } else { 0 }   # 1 = Orta, 0 = Maksimum Performans
  powercfg /setacvalueindex SCHEME_CURRENT 19cbb8fa-5279-450e-9fac-8a3d5fedd0c1 12bbebe6-58d6-4636-95bb-3217ef867c1a $val | Out-Null
  powercfg /setdcvalueindex SCHEME_CURRENT 19cbb8fa-5279-450e-9fac-8a3d5fedd0c1 12bbebe6-58d6-4636-95bb-3217ef867c1a $val | Out-Null
  powercfg /setactive SCHEME_CURRENT | Out-Null
}

# 3. Receive Segment Coalescing (RSC)
#    RSC birden cok paketi birlestirip ust katmana tek pakette verir. Verim icin iyi,
#    gecikme icin kotu. Oyun icin kapali olmali.
Apply 'Receive Segment Coalescing (RSC) -> kapatiliyor' {
  if ($Undo) {
    Enable-NetAdapterRsc -Name * -IncludeHidden -ErrorAction SilentlyContinue
  } else {
    Disable-NetAdapterRsc -Name * -IncludeHidden -ErrorAction SilentlyContinue
  }
}

# 4. MMCSS
Apply 'MMCSS: NetworkThrottlingIndex / SystemResponsiveness' {
  $mm = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile'
  if ($Undo) {
    Set-Registry -Path $mm -Name 'NetworkThrottlingIndex' -Value 10
    Set-Registry -Path $mm -Name 'SystemResponsiveness'   -Value 20
  } else {
    Set-Registry -Path $mm -Name 'NetworkThrottlingIndex' -Value 4294967295
    Set-Registry -Path $mm -Name 'SystemResponsiveness'   -Value 10
  }
}

Apply 'MMCSS Games gorevi onceligi' {
  $g = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games'
  if (-not (Test-Path $g)) { New-Item -Path $g -Force | Out-Null }
  if ($Undo) {
    Set-Registry -Path $g -Name 'GPU Priority'      -Value 8
    Set-Registry -Path $g -Name 'Priority'          -Value 6
    Set-Registry -Path $g -Name 'Scheduling Category' -Value 'High' -Type 'String'
  } else {
    Set-Registry -Path $g -Name 'GPU Priority'      -Value 8
    Set-Registry -Path $g -Name 'Priority'          -Value 6
    Set-Registry -Path $g -Name 'Scheduling Category' -Value 'High' -Type 'String'
    Set-Registry -Path $g -Name 'SFIO Priority'     -Value 'High' -Type 'String'
  }
}

# 5. Game DVR arka plan kaydi
Apply 'Game DVR arka plan kaydi' {
  if ($Undo) {
    Set-Registry -Path 'HKCU:\System\GameConfigStore' -Name 'GameDVR_Enabled' -Value 1
    Set-Registry -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR' -Name 'AppCaptureEnabled' -Value 1
  } else {
    Set-Registry -Path 'HKCU:\System\GameConfigStore' -Name 'GameDVR_Enabled' -Value 0
    Set-Registry -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR' -Name 'AppCaptureEnabled' -Value 0
  }
}

# 6. Delivery Optimization (Windows Update P2P) -> kapat
Apply 'Delivery Optimization (P2P guncelleme dagitimi)' {
  $do = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\DeliveryOptimization\Config'
  if (-not (Test-Path $do)) { New-Item -Path $do -Force | Out-Null }
  Set-Registry -Path $do -Name 'DownloadMode' -Value $(if ($Undo) { 1 } else { 0 })
}

# 7. DNS onbellegi
Apply 'DNS onbellegi temizlendi' {
  Clear-DnsClientCache
}

Write-Host "`nBitti." -ForegroundColor Green
if (-not $Undo -and -not $DryRun) {
  Write-Host 'Oneri: bilgisayari yeniden baslat, sonra .\windows-tuning.ps1 -Report ile once/sonra min-max farkini karsilastir.' -ForegroundColor Cyan
}
Write-Host ''
Write-Host 'Bunlari betik yapmaz (elle, Wi-Fi profilin icin):' -ForegroundColor Yellow
Write-Host '  netsh wlan show profiles                                        # profil adini bul' -ForegroundColor Yellow
Write-Host '  netsh wlan set profileparameter name="PROFIL" randomizationstate=disable   # MAC rastgelelestirme kapali' -ForegroundColor Yellow
Write-Host '  Router arayuzunde 2.4/5 GHz otomatik gecisini (band steering) kapat.' -ForegroundColor Yellow
Write-Host ''
