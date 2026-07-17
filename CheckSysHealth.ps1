# ==============================================================================
# CheckSysHealth v1.0 - Standalone PowerShell Edition (No Python / No LHM)
# Created by: Duli Software & Antigravity
# Description: Pure native PowerShell system audit & crack detection script.
#              Outputs a self-contained responsive HTML report to Desktop.
#              (Unaccented Vietnamese / English ASCII-safe Edition)
# ==============================================================================

$ErrorActionPreference = "Continue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# 1. Self-Elevation to Administrator via UAC
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "`n [UAC] Yeu cau quyen Administrator de doc thong tin phan cung va ban quyen..." -ForegroundColor Yellow
    try {
        $psArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
        Start-Process powershell -Verb RunAs -ArgumentList $psArgs -ErrorAction Stop
        exit
    } catch {
        Write-Host " [WARNING] Khong the tu dong xin quyen Admin qua UAC (Non-interactive session). Vui long mo powershell voi quyen 'Run as Administrator' va chay lai." -ForegroundColor Red
        # Continue in read-only non-admin mode
    }
}

Write-Host "`n  ╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║       CheckSysHealth v1.0 — Standalone PowerShell Edition    ║" -ForegroundColor Cyan
Write-Host "  ║            Created by Duli Software & Antigravity            ║" -ForegroundColor Cyan
Write-Host "  ║        Cong cu kiem tra & kiem ke he thong Windows           ║" -ForegroundColor Cyan
Write-Host "  ║        Chi doc (Read-Only) | Yeu cau quyen Administrator     ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

# Global Data Object
$ReportData = @{
    Timestamp   = (Get-Date -Format "dd/MM/yyyy HH:mm:ss")
    Hostname    = $env:COMPUTERNAME
    OS          = @{}
    CPU         = @{}
    Motherboard = @{}
    RAM         = @{}
    Disk        = @{}
    Battery     = @{}
    GPU         = @{}
    Network     = @{}
    License     = @{ Windows = @{}; Office = @{} }
    CrackScan   = @{ Findings = @(); RiskLevel = "None" }
}

# ------------------------------------------------------------------------------
# STEP 1: CPU (No Temperature)
# ------------------------------------------------------------------------------
Write-Host " [1/9] Dang thu thap thong tin CPU (Khong do nhiet do)..." -ForegroundColor Cyan
try {
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    $ReportData.CPU = @{
        Name         = if ($cpu.Name) { $cpu.Name.Trim() } else { "Unknown CPU" }
        Manufacturer = $cpu.Manufacturer
        Cores        = $cpu.NumberOfCores
        Threads      = $cpu.NumberOfLogicalProcessors
        MaxClock     = "$($cpu.MaxClockSpeed) MHz"
        LoadPct      = [int]$cpu.LoadPercentage
        ProcessorId  = $cpu.ProcessorId
        Socket       = $cpu.SocketDesignation
    }
} catch {
    $ReportData.CPU = @{ Name = "Error reading CPU info"; LoadPct = 0 }
}

# ------------------------------------------------------------------------------
# STEP 2: MOTHERBOARD & BIOS
# ------------------------------------------------------------------------------
Write-Host " [2/9] Dang thu thap thong tin Mainboard & BIOS..." -ForegroundColor Cyan
try {
    $mb = Get-CimInstance Win32_BaseBoard | Select-Object -First 1
    $bios = Get-CimInstance Win32_BIOS | Select-Object -First 1
    $cs = Get-CimInstance Win32_ComputerSystem | Select-Object -First 1
    
    $biosDateStr = "N/A"
    if ($bios.ReleaseDate) {
        try { $biosDateStr = ([System.Management.ManagementDateTimeConverter]::ToDateTime($bios.ReleaseDate)).ToString("dd/MM/yyyy") } catch { $biosDateStr = $bios.ReleaseDate.ToString() }
    }
    
    # Check SLIC OEM Table
    $hasSlic = "No"
    try {
        $slic = Get-CimInstance -Namespace root\wmi -Class ACPI_SLIC -ErrorAction SilentlyContinue
        if ($slic) { $hasSlic = "Yes (OEM SLIC Table present)" }
    } catch {}

    $ReportData.Motherboard = @{
        Manufacturer     = $mb.Manufacturer
        Model            = $mb.Product
        Serial           = $mb.SerialNumber
        Version          = $mb.Version
        SystemVendor     = $cs.Manufacturer
        SystemModel      = $cs.Model
        BiosVendor       = $bios.Manufacturer
        BiosVersion      = $bios.SMBIOSBIOSVersion
        BiosDate         = $biosDateStr
        HasSLIC          = $hasSlic
    }
} catch {}

# ------------------------------------------------------------------------------
# STEP 3: RAM
# ------------------------------------------------------------------------------
Write-Host " [3/9] Dang thu thap thong tin RAM..." -ForegroundColor Cyan
try {
    $cs = Get-CimInstance Win32_ComputerSystem | Select-Object -First 1
    $totalRamGB = [math]::Round(($cs.TotalPhysicalMemory / 1GB), 1)
    
    $os = Get-CimInstance Win32_OperatingSystem | Select-Object -First 1
    $freeRamGB = [math]::Round(($os.FreePhysicalMemory / 1MB), 1)
    $usedRamGB = [math]::Round(($totalRamGB - $freeRamGB), 1)
    $usedPct = if ($totalRamGB -gt 0) { [math]::Round(($usedRamGB / $totalRamGB) * 100, 1) } else { 0 }

    $sticks = @()
    $memSticks = Get-CimInstance Win32_PhysicalMemory
    foreach ($m in $memSticks) {
        $capGB = [math]::Round(($m.Capacity / 1GB), 1)
        $speed = if ($m.ConfiguredClockSpeed) { "$($m.ConfiguredClockSpeed) MHz" } elseif ($m.Speed) { "$($m.Speed) MHz" } else { "Unknown Speed" }
        $vendor = if ($m.Manufacturer) { $m.Manufacturer.Trim() } else { "Unknown" }
        $part = if ($m.PartNumber) { $m.PartNumber.Trim() } else { "N/A" }
        $slot = if ($m.DeviceLocator) { $m.DeviceLocator.Trim() } else { "Slot" }
        $sticks += @{ Slot = $slot; CapacityGB = $capGB; Vendor = $vendor; Speed = $speed; PartNumber = $part }
    }

    $ReportData.RAM = @{
        TotalGB   = $totalRamGB
        UsedGB    = $usedRamGB
        FreeGB    = $freeRamGB
        UsedPct   = $usedPct
        Sticks    = $sticks
    }
} catch {}

# ------------------------------------------------------------------------------
# STEP 4: STORAGE & SMART
# ------------------------------------------------------------------------------
Write-Host " [4/9] Dang thu thap thong tin O cung & SMART status..." -ForegroundColor Cyan
try {
    $drives = @()
    $diskDrives = Get-CimInstance Win32_DiskDrive
    
    # Check SMART Predict status
    $smartStatusMap = @{}
    try {
        $smartPredicts = Get-CimInstance -Namespace root\wmi -Class MSStorageDriver_FailurePredictStatus -ErrorAction SilentlyContinue
        foreach ($sp in $smartPredicts) {
            $smartStatusMap[$sp.InstanceName] = $sp.PredictFailure
        }
    } catch {}

    foreach ($dd in $diskDrives) {
        $sizeGB = [math]::Round(($dd.Size / 1GB), 1)
        $model = if ($dd.Model) { $dd.Model.Trim() } else { "Unknown Disk" }
        $mediaType = if ($dd.MediaType) { $dd.MediaType } else { "Unknown" }
        if ($model -match "NVMe" -or $dd.Caption -match "NVMe") { $mediaType = "NVMe SSD" }
        elseif ($mediaType -match "SSD") { $mediaType = "SATA SSD" }

        # Check SMART
        $predictFail = $false
        foreach ($key in $smartStatusMap.Keys) {
            if ($key -match $dd.PNPDeviceID) {
                $predictFail = $smartStatusMap[$key]
                break
            }
        }
        $smartHealth = if ($predictFail) { "Bad (Failure Predicted)" } else { "Good (OK)" }

        $drives += @{
            Model       = $model
            SizeGB      = $sizeGB
            MediaType   = $mediaType
            Interface   = $dd.InterfaceType
            SmartHealth = $smartHealth
            Partitions  = $dd.Partitions
        }
    }

    $volumes = @()
    $logDisks = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"
    foreach ($ld in $logDisks) {
        $totalGB = [math]::Round(($ld.Size / 1GB), 1)
        $freeGB  = [math]::Round(($ld.FreeSpace / 1GB), 1)
        $usedGB  = [math]::Round(($totalGB - $freeGB), 1)
        $pct     = if ($totalGB -gt 0) { [math]::Round(($usedGB / $totalGB) * 100, 1) } else { 0 }
        $volumes += @{
            DriveLetter = $ld.DeviceID
            Label       = $ld.VolumeName
            FileSystem  = $ld.FileSystem
            TotalGB     = $totalGB
            UsedGB      = $usedGB
            FreeGB      = $freeGB
            UsedPct     = $pct
        }
    }

    $ReportData.Disk = @{ Drives = $drives; Volumes = $volumes }
} catch {}

# ------------------------------------------------------------------------------
# STEP 5: BATTERY
# ------------------------------------------------------------------------------
Write-Host " [5/9] Dang kiem tra tinh trang Pin (Battery)..." -ForegroundColor Cyan
try {
    $bat = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($bat) {
        $ReportData.Battery.Present = $true
        $ReportData.Battery.Name = if ($bat.Name) { $bat.Name } else { "System Battery" }
        $ReportData.Battery.ChargePct = $bat.EstimatedChargeRemaining
        $ReportData.Battery.Status = $bat.Status
    } else {
        $ReportData.Battery.Present = $false
    }
} catch {
    $ReportData.Battery.Present = $false
}

# ------------------------------------------------------------------------------
# STEP 6: GPU
# ------------------------------------------------------------------------------
Write-Host " [6/9] Dang thu thap thong tin GPU (Card do hoa)..." -ForegroundColor Cyan
try {
    $gpus = @()
    $videoControllers = Get-CimInstance Win32_VideoController
    foreach ($vc in $videoControllers) {
        $vramMB = [math]::Round(($vc.AdapterRAM / 1MB), 0)
        if ($vramMB -lt 0) { $vramMB = "4096+ (64-bit overflow)" }
        $gpus += @{
            Name          = if ($vc.Name) { $vc.Name.Trim() } else { "Standard VGA" }
            Vendor        = $vc.AdapterCompatibility
            VramMB        = $vramMB
            DriverVersion = $vc.DriverVersion
            Resolution    = "$($vc.CurrentHorizontalResolution) x $($vc.CurrentVerticalResolution)"
        }
    }
    $ReportData.GPU = @{ List = $gpus }
} catch {}

# ------------------------------------------------------------------------------
# STEP 7: NETWORK & INTERNET
# ------------------------------------------------------------------------------
Write-Host " [7/9] Dang kiem tra Mang & Internet..." -ForegroundColor Cyan
try {
    $adapters = @()
    $nics = Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled = True"
    foreach ($n in $nics) {
        $ip = if ($n.IPAddress) { ($n.IPAddress | Where-Object { $_ -match "^[0-9\.]+$" }) -join ", " } else { "N/A" }
        $adapters += @{
            Description = $n.Description
            MAC         = $n.MACAddress
            IPAddress   = $ip
            DHCP        = if ($n.DHCPEnabled) { "Yes" } else { "Static/No" }
        }
    }

    # Test internet
    $internetOk = $false
    try {
        $ping = Test-NetConnection -ComputerName "8.8.8.8" -Port 53 -WarningAction SilentlyContinue -InformationLevel Quiet
        $internetOk = $ping
    } catch {}

    $ReportData.Network = @{
        Adapters   = $adapters
        InternetOk = $internetOk
    }
} catch {}

# ------------------------------------------------------------------------------
# STEP 8: LICENSE (WINDOWS & OFFICE)
# ------------------------------------------------------------------------------
Write-Host " [8/9] Dang kiem tra Ban quyen Windows & Microsoft Office..." -ForegroundColor Cyan

# --- Windows OS Info & License ---
try {
    $os = Get-CimInstance Win32_OperatingSystem | Select-Object -First 1
    $ReportData.OS = @{
        ProductName  = $os.Caption.Trim()
        BuildNumber  = $os.BuildNumber
        Architecture = $os.OSArchitecture
        InstallDate  = ([System.Management.ManagementDateTimeConverter]::ToDateTime($os.InstallDate)).ToString("dd/MM/yyyy")
    }
} catch {}

try {
    $winLic = Get-CimInstance SoftwareLicensingProduct -Filter "PartialProductKey is not null and Description like '%Windows%'" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($winLic) {
        $statusMap = @{ 0="Unlicensed"; 1="Licensed (Activated)"; 2="OOB Grace"; 3="OOT Grace"; 4="Non-Genuine Grace"; 5="Notification"; 6="Extended Grace" }
        $ReportData.License.Windows = @{
            Installed  = $true
            Name       = $winLic.Name
            PartialKey = $winLic.PartialProductKey
            Status     = if ($statusMap.ContainsKey($winLic.LicenseStatus)) { $statusMap[$winLic.LicenseStatus] } else { "Unknown ($($winLic.LicenseStatus))" }
            Desc       = $winLic.Description
        }
    } else {
        $ReportData.License.Windows = @{ Installed = $true; Status = "Not Activated / No Partial Key" }
    }
} catch {}

# --- Microsoft Office Info & License (ospp.vbs + WMI Hybrid) ---
try {
    $offInfo = @{ Installed = $false; ProductName = "N/A"; Version = "N/A"; Channel = "N/A"; LicenseType = "N/A"; Status = "Not Installed"; PartialKey = "N/A"; KmsServer = "N/A" }
    
    # 1. Check Click-To-Run Registry
    $c2rPath = "HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration"
    if (Test-Path $c2rPath) {
        $offInfo.Installed = $true
        $offInfo.ProductName = (Get-ItemProperty -Path $c2rPath -Name "ProductReleaseIds" -ErrorAction SilentlyContinue).ProductReleaseIds
        $offInfo.Version     = (Get-ItemProperty -Path $c2rPath -Name "VersionToReport" -ErrorAction SilentlyContinue).VersionToReport
        $cdnBase             = (Get-ItemProperty -Path $c2rPath -Name "CDNBaseUrl" -ErrorAction SilentlyContinue).CDNBaseUrl
        
        $channelMap = @{
            "492350f6-3a01-4f97-b9c0-c7c6ddf67d60" = "Current Channel (Retail)"
            "55336b82-a18d-4dd6-b5f6-9e5095c314a6" = "Monthly Enterprise Channel"
            "7ffbc6bf-bc32-4f92-8982-f9dd17fd3114" = "Semi-Annual Enterprise Channel"
            "64256afe-f5d9-4f86-8936-8840a6a4f5be" = "Current Channel (Preview)"
            "f2e724c1-748f-4b47-8fb8-8e0d210e9208" = "Beta Channel"
        }
        foreach ($guid in $channelMap.Keys) {
            if ($cdnBase -match $guid) { $offInfo.Channel = $channelMap[$guid]; break }
        }
        if ($offInfo.Channel -eq "N/A" -and $cdnBase) { $offInfo.Channel = "Click-To-Run ($cdnBase)" }
    }

    # 2. Query ospp.vbs
    $osppPaths = @(
        "$env:ProgramFiles\Microsoft Office\root\Office16\ospp.vbs",
        "${env:ProgramFiles(x86)}\Microsoft Office\root\Office16\ospp.vbs",
        "$env:ProgramFiles\Microsoft Office\Office16\ospp.vbs"
    )
    foreach ($p in $osppPaths) {
        if (Test-Path $p) {
            $offInfo.Installed = $true
            $output = cscript //Nologo "$p" /dstatus 2>&1
            foreach ($line in ($output -split "`r?`n")) {
                if ($line -match "LICENSE NAME:\s*(.+)") { $offInfo.LicenseType = $Matches[1].Trim() }
                elseif ($line -match "LICENSE DESCRIPTION:\s*(.+)") {
                    $desc = $Matches[1].Trim()
                    if ($offInfo.Channel -eq "N/A" -or $offInfo.Channel -match "Click-To-Run") { $offInfo.Channel = $desc }
                }
                elseif ($line -match "LICENSE STATUS:\s*---(\w+)---") { $offInfo.Status = $Matches[1].Trim() }
                elseif ($line -match "Last 5 characters of installed product key:\s*(\w+)") { $offInfo.PartialKey = $Matches[1].Trim() }
                elseif ($line -match "KMS machine name from DNS:\s*(.+)") { $offInfo.KmsServer = $Matches[1].Trim() }
            }
            break
        }
    }

    # Format Status label
    if ($offInfo.Status -match "LICENSED") { $offInfo.Status = "Licensed (Activated)" }
    elseif ($offInfo.Status -match "NOTIFICATIONS") { $offInfo.Status = "Notification (Expired/Grace Ended)" }
    elseif ($offInfo.Status -match "OOB_GRACE") { $offInfo.Status = "OOB Grace Period" }

    $ReportData.License.Office = $offInfo
} catch {}

# ------------------------------------------------------------------------------
# STEP 9: CRACK & SECURITY AUDIT (14 CHECKS)
# ------------------------------------------------------------------------------
Write-Host " [9/9] Dang quet rui ro bao mat & phat hien cong cu Crack (14 hang muc)..." -ForegroundColor Cyan
$findings = @()

# [Check 1] Hosts file check for KMS redirection
try {
    $hostsPath = "$env:windir\System32\drivers\etc\hosts"
    if (Test-Path $hostsPath) {
        $content = Get-Content $hostsPath -ErrorAction SilentlyContinue
        foreach ($line in $content) {
            if ($line -match "^\s*\d+\.\d+\.\d+\.\d+\s+.*(kms|activate|sls|ospp|msguides|office)" -and $line -notmatch "^\s*#") {
                $findings += @{ Severity="Critical"; Title="Phat hien chan/gia lap domain kich hoat trong file hosts"; Evidence=$line.Trim() }
            }
        }
    }
} catch {}

# [Check 2] Suspicious Scheduled Tasks (excluding standard Microsoft tasks)
try {
    $tasks = Get-ScheduledTask -ErrorAction SilentlyContinue
    $suspKeywords = @("kms", "activate", "activator", "aact", "pico", "kms_vl_all", "ohook", "ospphook")
    foreach ($t in $tasks) {
        $tName = $t.TaskName.ToLower()
        $tPath = $t.TaskPath.ToLower()
        if ($tPath -match "\\microsoft\\windows\\") {
            $isExplicitCrack = $false
            foreach ($kw in @("kmspico", "aact", "autopico", "kms_vl_all", "ohook", "ospphook")) {
                if ($tName -match $kw) { $isExplicitCrack = $true; break }
            }
            if (-not $isExplicitCrack) { continue }
        }
        foreach ($kw in $suspKeywords) {
            if ($tName -match $kw) {
                $findings += @{ Severity="High"; Title="Scheduled Task nghi ngo lien quan den KMS/Crack: '$($t.TaskName)'"; Evidence="Path: $($t.TaskPath)" }
                break
            }
        }
    }
} catch {}

# [Check 3] Port 1688 (KMS Port) listener check
try {
    $conns = Get-NetTCPConnection -LocalPort 1688 -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        foreach ($c in $conns) {
            $procName = (Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue).ProcessName
            if ($procName -notmatch "lsass|system|svchost") {
                $findings += @{ Severity="Critical"; Title="Phat hien tien trinh la dang lang nghe cong KMS (Port 1688)"; Evidence="PID: $($c.OwningProcess) ($procName)" }
            }
        }
    }
} catch {}

# [Check 4] Registry Run Keys & Known Crack paths
try {
    $crackNames = @("kmspico", "aact", "kms_vl_all", "ohook", "secoh-qad", "sppextcomobj")
    $runKeys = @("HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKLM:\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Run")
    foreach ($rk in $runKeys) {
        if (Test-Path $rk) {
            $props = Get-ItemProperty -Path $rk -ErrorAction SilentlyContinue
            if ($props) {
                foreach ($p in $props.PSObject.Properties) {
                    foreach ($cn in $crackNames) {
                        if ($p.Name.ToLower() -match $cn -or "$($p.Value)".ToLower() -match $cn) {
                            $findings += @{ Severity="Critical"; Title="Phat hien cong cu Crack tu khoi dong trong Registry Run key"; Evidence="$($p.Name) = $($p.Value)" }
                        }
                    }
                }
            }
        }
    }

    # Known Paths check
    $crackPaths = @(
        "$env:ProgramFiles\KMSpico", "${env:ProgramFiles(x86)}\KMSpico", "$env:ProgramFiles\AAct Network",
        "$env:SystemDrive\KMS_VL_ALL", "$env:ProgramData\Microsoft\OfficeSoftwareProtectionPlatform\licenses\ohook",
        "$env:windir\System32\SECOH-QAD.exe"
    )
    foreach ($cp in $crackPaths) {
        if (Test-Path $cp) {
            $findings += @{ Severity="Critical"; Title="Phat hien file/thu muc cong cu be khoa (Crack tool) da biet"; Evidence=$cp }
        }
    }
} catch {}

# [Check 5] Office R2V Conversion & KMS Emulation checks
try {
    $off = $ReportData.License.Office
    if ($off.Installed) {
        # Check KMS server pointing to local IP
        if ($off.KmsServer -match "^(127\.|localhost|0\.0\.0\.0|192\.168\.|10\.|172\.)") {
            $findings += @{ Severity="High"; Title="Office cau hinh kich hoat qua KMS Server noi bo (KMS Emulator)"; Evidence="KMS Server: $($off.KmsServer)" }
        }
        # Check Retail to Volume conversion
        $isRetailInstall = $off.ProductName -match "Retail"
        $isVolumeActive  = $off.LicenseType -match "Volume|KMS" -or $off.Channel -match "Volume|KMS"
        if ($isRetailInstall -and $isVolumeActive) {
            $findings += @{ Severity="High"; Title="Phat hien dau hieu chuyen doi Office Retail sang Volume trai phep (C2R-R2V)"; Evidence="Installer: $($off.ProductName) | Active License: $($off.LicenseType)" }
        }
    }
} catch {}

# Determine Risk Level
$critCount = ($findings | Where-Object { $_.Severity -eq "Critical" }).Count
$highCount = ($findings | Where-Object { $_.Severity -eq "High" }).Count
if ($critCount -gt 0) { $ReportData.CrackScan.RiskLevel = "Critical" }
elseif ($highCount -gt 0) { $ReportData.CrackScan.RiskLevel = "High" }
elseif ($findings.Count -gt 0) { $ReportData.CrackScan.RiskLevel = "Medium" }
else { $ReportData.CrackScan.RiskLevel = "None (Safe)" }
$ReportData.CrackScan.Findings = $findings

Write-Host "`n [OK] Hoan tat thu thap du lieu! Dang tao bao cao HTML..." -ForegroundColor Green

# ------------------------------------------------------------------------------
# STEP 10: BUILD & EXPORT HTML REPORT TO DESKTOP
# ------------------------------------------------------------------------------
$desktopPath = [Environment]::GetFolderPath("Desktop")
$htmlFile = "$desktopPath\CheckSysHealth_Report_$($ReportData.Hostname).html"

function Get-Badge($status) {
    if ($status -match "Good|Licensed \(Activated\)|None \(Safe\)|Yes \(OEM") { return "<span class='badge badge-good'>$status</span>" }
    elseif ($status -match "Warn|Notification|OOB|Medium|High") { return "<span class='badge badge-warn'>$status</span>" }
    elseif ($status -match "Bad|Critical|Unlicensed|Failure") { return "<span class='badge badge-danger'>$status</span>" }
    return "<span class='badge badge-unknown'>$status</span>"
}

$htmlContent = @"
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CheckSysHealth Report — $($ReportData.Hostname)</title>
    <style>
        :root {
            --bg: #0f172a; --panel: #1e293b; --border: #334155; --text: #f8fafc; --text-muted: #94a3b8;
            --accent: #38bdf8; --good: #22c55e; --warn: #eab308; --danger: #ef4444; --unknown: #64748b;
        }
        [data-theme="light"] {
            --bg: #f8fafc; --panel: #ffffff; --border: #e2e8f0; --text: #0f172a; --text-muted: #64748b;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { background-color: var(--bg); color: var(--text); padding-bottom: 60px; }
        .header { background: var(--panel); border-bottom: 1px solid var(--border); padding: 20px 40px; display: flex; justify-content: space-between; align-items: center; }
        .header-title { font-size: 1.6rem; font-weight: 700; color: var(--accent); }
        .header-meta { font-size: 0.9rem; color: var(--text-muted); margin-top: 4px; }
        .btn { background: var(--panel); border: 1px solid var(--border); color: var(--text); padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: 600; text-decoration: none; display: inline-block; }
        .btn:hover { border-color: var(--accent); color: var(--accent); }
        .container { max-width: 1200px; margin: 30px auto; padding: 0 20px; }
        .grid-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 30px; }
        .card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 18px; }
        .card-title { font-size: 0.85rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }
        .card-value { font-size: 1.4rem; font-weight: 700; margin-top: 8px; color: var(--text); }
        .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 24px; overflow: hidden; }
        .panel-header { background: rgba(0,0,0,0.15); padding: 14px 20px; font-weight: 700; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
        .panel-body { padding: 20px; }
        .info-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }
        .info-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed var(--border); }
        .info-label { color: var(--text-muted); font-size: 0.9rem; }
        .info-val { font-weight: 600; text-align: right; }
        .badge { padding: 4px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: 700; }
        .badge-good { background: rgba(34,197,94,0.2); color: var(--good); border: 1px solid var(--good); }
        .badge-warn { background: rgba(234,179,8,0.2); color: var(--warn); border: 1px solid var(--warn); }
        .badge-danger { background: rgba(239,68,68,0.2); color: var(--danger); border: 1px solid var(--danger); }
        .badge-unknown { background: rgba(100,116,139,0.2); color: var(--unknown); border: 1px solid var(--unknown); }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { text-align: left; padding: 12px; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
        th { color: var(--text-muted); font-weight: 600; background: rgba(0,0,0,0.1); }
    </style>
</head>
<body>
    <header class="header">
        <div>
            <div class="header-title">CheckSysHealth v1.0 <span style="font-size:1rem;color:var(--text-muted)">| Standalone PowerShell Edition</span></div>
            <div class="header-meta">Hostname: $($ReportData.Hostname) &nbsp;|&nbsp; OS: $($ReportData.OS.ProductName) (Build $($ReportData.OS.BuildNumber)) &nbsp;|&nbsp; Date: $($ReportData.Timestamp)</div>
        </div>
        <div>
            <button class="btn" onclick="document.documentElement.setAttribute('data-theme', document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark')">Theme</button>
            <button class="btn" onclick="window.print()">Print / PDF</button>
        </div>
    </header>

    <div class="container">
        <!-- Dashboard Summary Cards -->
        <div class="grid-cards">
            <div class="card">
                <div class="card-title">Security / Crack Risk Level</div>
                <div class="card-value">$(Get-Badge $ReportData.CrackScan.RiskLevel)</div>
            </div>
            <div class="card">
                <div class="card-title">Windows License Status</div>
                <div class="card-value">$(Get-Badge $ReportData.License.Windows.Status)</div>
            </div>
            <div class="card">
                <div class="card-title">Office License Status</div>
                <div class="card-value">$(Get-Badge $ReportData.License.Office.Status)</div>
            </div>
            <div class="card">
                <div class="card-title">RAM Usage</div>
                <div class="card-value">$($ReportData.RAM.UsedPct)% <span style="font-size:0.9rem;color:var(--text-muted)">($($ReportData.RAM.UsedGB)/$($ReportData.RAM.TotalGB) GB)</span></div>
            </div>
        </div>

        <!-- Security & Crack Scan Panel -->
        <div class="panel">
            <div class="panel-header"><span>Security Audit &amp; Crack Detection Scan</span> $(Get-Badge $ReportData.CrackScan.RiskLevel)</div>
            <div class="panel-body">
                $(if ($ReportData.CrackScan.Findings.Count -eq 0) {
                    "<p style='color:var(--good);font-weight:600;'>[OK] No crack tools, unauthorized activators, or suspicious anomalies detected (Clean System).</p>"
                } else {
                    "<table><thead><tr><th>Severity</th><th>Finding / Risk Title</th><th>Evidence / Details</th></tr></thead><tbody>" +
                    (($ReportData.CrackScan.Findings | ForEach-Object {
                        "<tr><td>$(Get-Badge $_.Severity)</td><td style='font-weight:600;'>$($_.Title)</td><td style='font-family:monospace;color:var(--text-muted);'>$($_.Evidence)</td></tr>"
                    }) -join "") +
                    "</tbody></table>"
                })
            </div>
        </div>

        <!-- CPU Panel -->
        <div class="panel">
            <div class="panel-header"><span>CPU (Processor) — No Temp Measurement</span></div>
            <div class="panel-body info-grid">
                <div class="info-row"><span class="info-label">CPU Name</span><span class="info-val">$($ReportData.CPU.Name)</span></div>
                <div class="info-row"><span class="info-label">Cores / Threads</span><span class="info-val">$($ReportData.CPU.Cores) Cores / $($ReportData.CPU.Threads) Threads</span></div>
                <div class="info-row"><span class="info-label">Max Clock Speed</span><span class="info-val">$($ReportData.CPU.MaxClock)</span></div>
                <div class="info-row"><span class="info-label">Current Load Pct</span><span class="info-val">$($ReportData.CPU.LoadPct)%</span></div>
                <div class="info-row"><span class="info-label">Socket</span><span class="info-val">$($ReportData.CPU.Socket)</span></div>
                <div class="info-row"><span class="info-label">Processor ID</span><span class="info-val">$($ReportData.CPU.ProcessorId)</span></div>
            </div>
        </div>

        <!-- Motherboard Panel -->
        <div class="panel">
            <div class="panel-header"><span>Motherboard &amp; BIOS</span></div>
            <div class="panel-body info-grid">
                <div class="info-row"><span class="info-label">Manufacturer</span><span class="info-val">$($ReportData.Motherboard.Manufacturer)</span></div>
                <div class="info-row"><span class="info-label">Model</span><span class="info-val">$($ReportData.Motherboard.Model)</span></div>
                <div class="info-row"><span class="info-label">System Vendor</span><span class="info-val">$($ReportData.Motherboard.SystemVendor)</span></div>
                <div class="info-row"><span class="info-label">System Model</span><span class="info-val">$($ReportData.Motherboard.SystemModel)</span></div>
                <div class="info-row"><span class="info-label">BIOS Version</span><span class="info-val">$($ReportData.Motherboard.BiosVersion)</span></div>
                <div class="info-row"><span class="info-label">BIOS Date</span><span class="info-val">$($ReportData.Motherboard.BiosDate)</span></div>
                <div class="info-row"><span class="info-label">OEM SLIC Table Present</span><span class="info-val">$(Get-Badge $ReportData.Motherboard.HasSLIC)</span></div>
            </div>
        </div>

        <!-- RAM Panel -->
        <div class="panel">
            <div class="panel-header"><span>RAM (Memory) — Total: $($ReportData.RAM.TotalGB) GB</span></div>
            <div class="panel-body">
                <table>
                    <thead><tr><th>Slot</th><th>Capacity</th><th>Manufacturer</th><th>Speed</th><th>Part Number</th></tr></thead>
                    <tbody>
                        $(($ReportData.RAM.Sticks | ForEach-Object {
                            "<tr><td>$($_.Slot)</td><td><b>$($_.CapacityGB) GB</b></td><td>$($_.Vendor)</td><td>$($_.Speed)</td><td>$($_.PartNumber)</td></tr>"
                        }) -join "")
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Disk & Storage Panel -->
        <div class="panel">
            <div class="panel-header"><span>Storage &amp; SMART Health Status</span></div>
            <div class="panel-body">
                <table>
                    <thead><tr><th>Disk Model</th><th>Size</th><th>Media Type</th><th>Interface</th><th>SMART Health</th></tr></thead>
                    <tbody>
                        $(($ReportData.Disk.Drives | ForEach-Object {
                            "<tr><td><b>$($_.Model)</b></td><td>$($_.SizeGB) GB</td><td>$($_.MediaType)</td><td>$($_.Interface)</td><td>$(Get-Badge $_.SmartHealth)</td></tr>"
                        }) -join "")
                    </tbody>
                </table>
                <h4 style="margin:20px 0 10px;color:var(--text-muted)">Logical Volumes:</h4>
                <table>
                    <thead><tr><th>Drive Letter</th><th>Label</th><th>File System</th><th>Total Size</th><th>Used</th><th>Free</th></tr></thead>
                    <tbody>
                        $(($ReportData.Disk.Volumes | ForEach-Object {
                            "<tr><td><b>$($_.DriveLetter)</b></td><td>$($_.Label)</td><td>$($_.FileSystem)</td><td>$($_.TotalGB) GB</td><td>$($_.UsedGB) GB ($($_.UsedPct)%)</td><td>$($_.FreeGB) GB</td></tr>"
                        }) -join "")
                    </tbody>
                </table>
            </div>
        </div>

        <!-- GPU Panel -->
        <div class="panel">
            <div class="panel-header"><span>GPU (Graphics)</span></div>
            <div class="panel-body">
                <table>
                    <thead><tr><th>GPU Name</th><th>Vendor</th><th>VRAM</th><th>Driver Version</th><th>Current Resolution</th></tr></thead>
                    <tbody>
                        $(($ReportData.GPU.List | ForEach-Object {
                            "<tr><td><b>$($_.Name)</b></td><td>$($_.Vendor)</td><td>$($_.VramMB) MB</td><td>$($_.DriverVersion)</td><td>$($_.Resolution)</td></tr>"
                        }) -join "")
                    </tbody>
                </table>
            </div>
        </div>

        <!-- License Panel -->
        <div class="panel">
            <div class="panel-header"><span>Operating System &amp; Software Licenses</span></div>
            <div class="panel-body info-grid">
                <div class="info-row"><span class="info-label">Windows Product</span><span class="info-val">$($ReportData.License.Windows.Name)</span></div>
                <div class="info-row"><span class="info-label">Activation Status</span><span class="info-val">$(Get-Badge $ReportData.License.Windows.Status)</span></div>
                <div class="info-row"><span class="info-label">Partial Product Key</span><span class="info-val">$($ReportData.License.Windows.PartialKey)</span></div>
                <div class="info-row" style="grid-column: 1 / -1;border-bottom:2px solid var(--border);margin:10px 0;"></div>
                <div class="info-row"><span class="info-label">Microsoft Office Product</span><span class="info-val">$($ReportData.License.Office.ProductName) ($($ReportData.License.Office.Version))</span></div>
                <div class="info-row"><span class="info-label">Update Channel</span><span class="info-val">$($ReportData.License.Office.Channel)</span></div>
                <div class="info-row"><span class="info-label">License Type</span><span class="info-val">$($ReportData.License.Office.LicenseType)</span></div>
                <div class="info-row"><span class="info-label">Activation Status</span><span class="info-val">$(Get-Badge $ReportData.License.Office.Status)</span></div>
                <div class="info-row"><span class="info-label">Partial Product Key</span><span class="info-val">$($ReportData.License.Office.PartialKey)</span></div>
                <div class="info-row"><span class="info-label">KMS Server</span><span class="info-val">$($ReportData.License.Office.KmsServer)</span></div>
            </div>
        </div>

        <!-- Footer -->
        <div style="text-align:center;padding:32px 0;color:var(--text-muted);font-size:.85rem;border-top:1px solid var(--border);margin-top:40px">
            <div style="font-weight:600;color:var(--text)">CheckSysHealth v1.0 &nbsp;—&nbsp; Standalone PowerShell Edition</div>
            <div style="margin-top:6px">Created by Duli Software &amp; Antigravity &nbsp;·&nbsp; Read-Only Audit</div>
        </div>
    </div>
</body>
</html>
"@

# Save with BOM so Windows browsers read UTF-8 properly
[System.IO.File]::WriteAllText($htmlFile, $htmlContent, [System.Text.Encoding]::UTF8)

Write-Host " [SUCCESS] Bao cao da duoc luu tai Desktop: $htmlFile" -ForegroundColor Green
Write-Host " [INFO] Dang mo bao cao trong trinh duyet mac dinh..." -ForegroundColor Cyan

try {
    Start-Process -FilePath $htmlFile
} catch {}
