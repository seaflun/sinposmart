param(
    [switch]$AssumeYes
)

$ErrorActionPreference = "Stop"

$releaseBaseUrl = "https://github.com/seaflun/sinposmart/releases/latest/download"
$remoteVersionUrl = "$releaseBaseUrl/sinposmart-version.txt"
$remoteZipUrl = "$releaseBaseUrl/sinposmart-public-package.zip"
$remoteSha256Url = "$releaseBaseUrl/sinposmart-public-package.zip.sha256.txt"

$packageDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$localVersionPath = Join-Path $packageDir "VERSION.txt"
$backupRoot = Join-Path $env:LOCALAPPDATA "SinpoSmart"
$backupDir = Join-Path $backupRoot "update_backups"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$tempDir = Join-Path $env:TEMP "SinpoSmartUpdate-$stamp"
$zipPath = Join-Path $tempDir "package.zip"
$extractDir = Join-Path $tempDir "extract"

function Get-TextFromUrl {
    param([string]$Url)
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -MaximumRedirection 5
    if ($response.Content -is [byte[]]) {
        $text = [System.Text.Encoding]::UTF8.GetString($response.Content)
    } else {
        $text = [string]$response.Content
    }
    return $text.Trim().TrimStart([char]0xFEFF)
}

function Test-VersionText {
    param(
        [string]$Version,
        [switch]$AllowZero
    )

    if ($AllowZero -and $Version -eq "0") {
        return $true
    }
    return $Version -match "^\d{4}\.\d{2}\.\d{2}\.\d{4}$"
}

function Get-Sha256FromText {
    param([string]$Text)
    $firstToken = ($Text.Trim().TrimStart([char]0xFEFF) -split "\s+")[0]
    if ($firstToken -notmatch "^[0-9a-fA-F]{64}$") {
        throw "Remote SHA256 file has an invalid hash: $firstToken"
    }
    return $firstToken.ToLowerInvariant()
}

$skipDirs = @("logs", "runtime_outputs", "tmp", "snapshots", "__pycache__", "artifacts")
$alwaysSkipFiles = @(
    "duty_sheet_legacy\config.json",
    "duty_sheet_legacy/effortless-leaf-353501-63492cc3ece4.json",
    "duty_sheet_legacy\effortless-leaf-353501-63492cc3ece4.json",
    "daily_vehicle_legacy\.env",
    "daily_vehicle_legacy/.env"
)
$preserveIfExistsFiles = @(
    "rest_time_automation_config.json"
)
$skipExtensions = @(".xls", ".xlsx", ".xlsm", ".xlsb", ".zip", ".pyc", ".pyo", ".key", ".pem", ".token", ".jsonl")

function Test-SkipPackagePath {
    param([string]$RelativePath)

    $relativeSlash = $RelativePath -replace "\\", "/"
    $parts = $relativeSlash -split "/"
    if ($parts | Where-Object { $skipDirs -contains $_ }) {
        return $true
    }
    if (($alwaysSkipFiles -contains $RelativePath) -or ($alwaysSkipFiles -contains $relativeSlash)) {
        return $true
    }

    $fileName = [System.IO.Path]::GetFileName($RelativePath)
    if ($fileName -eq "desktop.ini") {
        return $true
    }
    if ($fileName -eq ".env" -or ($fileName.StartsWith(".env.") -and $fileName -ne ".env.example")) {
        return $true
    }

    $extension = [System.IO.Path]::GetExtension($RelativePath).ToLowerInvariant()
    return $skipExtensions -contains $extension
}

function Get-RunningDutyGuiProcesses {
    $packagePath = $packageDir.TrimEnd([char]92)
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match "duty_gui\.pyw?" -and
            $_.CommandLine.Contains($packagePath)
        }
}

function Send-UpdateLogoutEvent {
    $client = $null
    $stream = $null
    $asyncResult = $null
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $asyncResult = $client.BeginConnect("127.0.0.1", 47631, $null, $null)
        if (-not $asyncResult.AsyncWaitHandle.WaitOne(1500)) {
            Write-Warning "Could not report update logout: command server timeout."
            return $false
        }

        $client.EndConnect($asyncResult)
        $stream = $client.GetStream()
        $stream.ReadTimeout = 5000
        $stream.WriteTimeout = 5000
        $bytes = [System.Text.Encoding]::UTF8.GetBytes("update_logout`n")
        $stream.Write($bytes, 0, $bytes.Length)

        $buffer = New-Object byte[] 64
        $count = $stream.Read($buffer, 0, $buffer.Length)
        if ($count -gt 0) {
            $response = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $count).Trim()
            Write-Host "Update logout event: $response"
        }
        return $true
    } catch {
        Write-Warning "Could not report update logout: $_"
        return $false
    } finally {
        if ($stream) {
            $stream.Dispose()
        }
        if ($client) {
            $client.Close()
        }
        if ($asyncResult -and $asyncResult.AsyncWaitHandle) {
            $asyncResult.AsyncWaitHandle.Dispose()
        }
    }
}

function Stop-RunningDutyGui {
    $processes = @(Get-RunningDutyGuiProcesses)
    if (-not $processes) {
        return $false
    }

    Write-Host "Closing running SinpoSmart app so the updated files can load..."
    foreach ($process in $processes) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
            Write-Host "Closed process $($process.ProcessId)."
        } catch {
            Write-Warning "Could not close process $($process.ProcessId): $_"
        }
    }
    Start-Sleep -Milliseconds 800
    return $true
}

function Start-DutyGui {
    $entrypoint = Join-Path $packageDir "duty_gui.pyw"
    if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) {
        $entrypoint = Join-Path $packageDir "duty_gui.py"
    }
    if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) {
        Write-Warning "Could not restart app because duty_gui.pyw/duty_gui.py was not found."
        return
    }

    $finder = Join-Path $packageDir "find_winpython.ps1"
    $pythonw = ""
    if (Test-Path -LiteralPath $finder -PathType Leaf) {
        $pythonw = (& powershell -NoProfile -ExecutionPolicy Bypass -File $finder -Windowed | Select-Object -First 1)
    }
    if (-not $pythonw) {
        Write-Warning "Could not restart app because WinPython pythonw.exe was not found. Set WINPYTHON_DIR or place WinPython beside the package."
        return
    }

    Start-Process -FilePath $pythonw -ArgumentList "`"$entrypoint`"" -WorkingDirectory $packageDir
    Write-Host "Restarted SinpoSmart app."
}

function Restart-DutyGuiIfRunning {
    if (Stop-RunningDutyGui) {
        Start-DutyGui
        return $true
    }
    return $false
}

function Get-WinPythonExe {
    $finder = Join-Path $packageDir "find_winpython.ps1"
    $python = ""
    if (Test-Path -LiteralPath $finder -PathType Leaf) {
        $python = (& powershell -NoProfile -ExecutionPolicy Bypass -File $finder | Select-Object -First 1)
    }
    if (-not $python) {
        throw "Could not run setup because WinPython python.exe was not found. Set WINPYTHON_DIR or place WinPython beside the package."
    }
    return [string]$python
}

function Invoke-SetupAfterUpdate {
    $requirementsPath = Join-Path $packageDir "requirements.txt"
    if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
        Write-Warning "Skipped setup because requirements.txt was not found."
        return
    }

    $python = Get-WinPythonExe
    Push-Location $packageDir
    try {
        Write-Host "Installing or refreshing Python requirements..."
        & $python -m pip install -r $requirementsPath
        if ($LASTEXITCODE -ne 0) {
            throw "pip install failed with exit code $LASTEXITCODE."
        }

        $environmentCheck = Join-Path $packageDir "check_environment.py"
        if (Test-Path -LiteralPath $environmentCheck -PathType Leaf) {
            Write-Host "Running environment check..."
            & $python $environmentCheck
            if ($LASTEXITCODE -ne 0) {
                throw "Environment check failed with exit code $LASTEXITCODE."
            }
        }
    } finally {
        Pop-Location
    }
}

function Copy-UpdateTree {
    param(
        [string]$SourceDir,
        [string]$DestDir
    )

    $slash = [string][char]92
    $sourceRoot = $SourceDir.TrimEnd([char]92) + $slash
    Get-ChildItem -LiteralPath $SourceDir -Recurse -File -Force | ForEach-Object {
        $relative = $_.FullName.Substring($sourceRoot.Length)
        $target = Join-Path $DestDir $relative
        if (Test-SkipPackagePath -RelativePath $relative) {
            Write-Host "Skipped local-only file: $relative"
            return
        }
        if (($preserveIfExistsFiles -contains $relative) -and (Test-Path -LiteralPath $target)) {
            Write-Host "Preserved local file: $relative"
            return
        }

        $targetDir = Split-Path -Parent $target
        if (-not (Test-Path -LiteralPath $targetDir)) {
            New-Item -ItemType Directory -Path $targetDir | Out-Null
        }
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        Write-Host "Updated: $relative"
    }
}

function New-PackageBackup {
    param(
        [string]$SourceDir,
        [string]$BackupZip,
        [string]$StageDir
    )

    if (Test-Path -LiteralPath $StageDir) {
        Remove-Item -LiteralPath $StageDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $StageDir -Force | Out-Null

    $backupFiles = @(
        "VERSION.txt",
        "update_package.ps1",
        "UPDATE_PACKAGE.bat",
        "RUN_DUTY_GUI_WINPYTHON.bat",
        "RUN_DUTY_GUI_WINPYTHON.vbs",
        "duty_gui.py",
        "duty_gui.pyw",
        "duty_sheet_automation.py",
        "daily_vehicle_automation.py",
        "rest_time_automation.py",
        "duty_rehearsal.py",
        "compare_rehearsal_records.py",
        "check_environment.py",
        "requirements.txt",
        "work_log_defaults.json"
    )

    $copied = 0
    foreach ($relative in $backupFiles) {
        if (Test-SkipPackagePath -RelativePath $relative) {
            continue
        }
        $source = Join-Path $SourceDir $relative
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            continue
        }

        $target = Join-Path $StageDir $relative
        $targetDir = Split-Path -Parent $target
        if (-not (Test-Path -LiteralPath $targetDir)) {
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        }
        Copy-Item -LiteralPath $source -Destination $target -Force
        $copied += 1
    }

    $manifestPath = Join-Path $StageDir "backup-manifest.txt"
    @(
        "Created: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "Source: $SourceDir",
        "Files: $copied",
        "",
        ($backupFiles -join [Environment]::NewLine)
    ) | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    Compress-Archive -LiteralPath (Join-Path $StageDir "*") -DestinationPath $BackupZip -Force
    Write-Host "Backup completed: $copied files"
}

if (-not (Test-Path -LiteralPath $localVersionPath)) {
    "0" | Set-Content -LiteralPath $localVersionPath -Encoding UTF8
}

$localVersion = (Get-Content -LiteralPath $localVersionPath -Raw -Encoding UTF8).Trim().TrimStart([char]0xFEFF)
$remoteVersion = Get-TextFromUrl -Url $remoteVersionUrl
$remoteSha256 = Get-Sha256FromText -Text (Get-TextFromUrl -Url $remoteSha256Url)

if (-not (Test-VersionText -Version $localVersion -AllowZero)) {
    throw "Local VERSION.txt has an invalid version: $localVersion"
}
if (-not (Test-VersionText -Version $remoteVersion)) {
    throw "Remote VERSION.txt has an invalid version: $remoteVersion"
}

Write-Host "Local version : $localVersion"
Write-Host "Remote version: $remoteVersion"

if ([string]::CompareOrdinal($remoteVersion, $localVersion) -le 0) {
    Write-Host "Already up to date."
    exit 0
}

Write-Host "Update available: $localVersion -> $remoteVersion"
if (-not $AssumeYes) {
    $answer = Read-Host "Close running app, update, and restart now? (Y/N)"
    if ($answer -notmatch "^[Yy]") {
        Write-Host "Update cancelled."
        exit 0
    }
}

try {
    New-Item -ItemType Directory -Path $tempDir | Out-Null
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

    Write-Host "Downloading update package..."
    Invoke-WebRequest -Uri $remoteZipUrl -OutFile $zipPath -UseBasicParsing -MaximumRedirection 5

    if (-not (Test-Path -LiteralPath $zipPath) -or (Get-Item -LiteralPath $zipPath).Length -lt 1024) {
        throw "Downloaded package is missing or too small."
    }
    $downloadedSha256 = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($downloadedSha256 -ne $remoteSha256) {
        throw "Downloaded package SHA256 mismatch. Expected $remoteSha256 but got $downloadedSha256."
    }

    $backupZip = Join-Path $backupDir "SinpoSmart-package-backup-$stamp.zip"
    Write-Host "Creating backup: $backupZip"
    New-PackageBackup -SourceDir $packageDir -BackupZip $backupZip -StageDir (Join-Path $tempDir "backup-stage")

    New-Item -ItemType Directory -Path $extractDir | Out-Null
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

    $sourceDir = Get-ChildItem -LiteralPath $extractDir -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "duty_gui.py") } |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $sourceDir -and (Test-Path -LiteralPath (Join-Path $extractDir "duty_gui.py"))) {
        $sourceDir = $extractDir
    }
    if (-not $sourceDir -or -not (Test-Path -LiteralPath $sourceDir -PathType Container)) {
        throw "Update zip does not contain a valid package folder."
    }

    $packageVersionPath = Join-Path $sourceDir "VERSION.txt"
    if (-not (Test-Path -LiteralPath $packageVersionPath -PathType Leaf)) {
        throw "Update zip does not contain VERSION.txt."
    }
    $packageVersion = (Get-Content -LiteralPath $packageVersionPath -Raw -Encoding UTF8).Trim().TrimStart([char]0xFEFF)
    if (-not (Test-VersionText -Version $packageVersion)) {
        throw "Update zip VERSION.txt has an invalid version: $packageVersion"
    }
    if ($packageVersion -ne $remoteVersion) {
        throw "Update version mismatch. Remote VERSION.txt is $remoteVersion but package VERSION.txt is $packageVersion."
    }

    Send-UpdateLogoutEvent | Out-Null
    $wasRunning = Stop-RunningDutyGui
    Copy-UpdateTree -SourceDir $sourceDir -DestDir $packageDir
    Invoke-SetupAfterUpdate
    $packageVersion | Set-Content -LiteralPath $localVersionPath -Encoding UTF8
    if ($wasRunning) {
        Start-DutyGui
    }

    Write-Host "Update completed."
} finally {
    try {
        if (Test-Path -LiteralPath $tempDir) {
            Remove-Item -LiteralPath $tempDir -Recurse -Force
        }
    } catch {
        Write-Warning "Could not remove temporary update folder: $tempDir"
    }
}
