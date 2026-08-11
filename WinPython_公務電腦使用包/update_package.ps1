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
    "rest_time_automation_config.json",
    "work_log_defaults.json"
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

function Get-DutyGuiEntrypointToken {
    param([object]$Process)

    if (-not $Process -or -not $Process.CommandLine) {
        return ""
    }
    $match = [regex]::Match(
        [string]$Process.CommandLine,
        '(?i)(?:"(?<quoted>[^"]*duty_gui\.pyw?)"|(?<bare>[^\s"]*duty_gui\.pyw?))(?=$|\s)'
    )
    if (-not $match.Success) {
        return ""
    }
    if ($match.Groups["quoted"].Success) {
        return $match.Groups["quoted"].Value
    }
    return $match.Groups["bare"].Value
}

function Test-IsPossiblePackageDutyGuiProcess {
    param([object]$Process)

    $entrypoint = Get-DutyGuiEntrypointToken -Process $Process
    if (-not $entrypoint) {
        return $false
    }
    if (-not [System.IO.Path]::IsPathRooted($entrypoint)) {
        # A bare or relative entrypoint may have been launched with packageDir as
        # its working directory. Treat it as ours so updating fails closed.
        return $true
    }
    try {
        $entrypointDirectory = [System.IO.Path]::GetDirectoryName(
            [System.IO.Path]::GetFullPath($entrypoint)
        )
        $normalizedPackageDir = [System.IO.Path]::GetFullPath($packageDir).TrimEnd([char]92, [char]47)
        $normalizedEntrypointDir = $entrypointDirectory.TrimEnd([char]92, [char]47)
        return [string]::Equals(
            $normalizedEntrypointDir,
            $normalizedPackageDir,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    } catch {
        # If an apparent absolute path cannot be normalized, do not risk
        # overwriting files while it might still belong to this package.
        return $true
    }
}

function Get-RunningDutyGuiProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { Test-IsPossiblePackageDutyGuiProcess -Process $_ }
}

function Test-IsQtDutyGuiProcess {
    param([object]$Process)

    $entrypoint = Get-DutyGuiEntrypointToken -Process $Process
    if (-not $entrypoint -or -not (Test-IsPossiblePackageDutyGuiProcess -Process $Process)) {
        return $false
    }
    return [string]::Equals(
        [System.IO.Path]::GetFileName($entrypoint),
        "duty_gui.pyw",
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Send-UpdateLogoutEvent {
    $pipe = $null
    $readResult = $null
    try {
        $pipe = [System.IO.Pipes.NamedPipeClientStream]::new(
            ".",
            "TYFD.SinpoSmart.DutyAutomation.Qt",
            [System.IO.Pipes.PipeDirection]::InOut,
            [System.IO.Pipes.PipeOptions]::Asynchronous
        )
        $pipe.Connect(1500)
        $bytes = [System.Text.Encoding]::UTF8.GetBytes("update_prepare`n")
        $pipe.Write($bytes, 0, $bytes.Length)
        $pipe.Flush()

        $buffer = New-Object byte[] 64
        $readResult = $pipe.BeginRead($buffer, 0, $buffer.Length, $null, $null)
        if (-not $readResult.AsyncWaitHandle.WaitOne(1500)) {
            Write-Warning "Could not prepare the running app for update: command server timeout."
            return "timeout"
        }
        $count = $pipe.EndRead($readResult)
        if ($count -le 0) {
            Write-Warning "Could not prepare the running app for update: empty response."
            return "failed"
        }
        $response = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $count).Trim().ToLowerInvariant()
        if ($response -notin @("ready", "busy", "failed")) {
            Write-Warning "Could not prepare the running app for update: invalid response '$response'."
            return "failed"
        }
        Write-Host "Update preparation: $response"
        return $response
    } catch {
        Write-Warning "Could not prepare the running app for update: $_"
        return "failed"
    } finally {
        if ($readResult -and $readResult.AsyncWaitHandle) {
            $readResult.AsyncWaitHandle.Dispose()
        }
        if ($pipe) {
            $pipe.Dispose()
        }
    }
}

function Stop-RunningDutyGui {
    param(
        [object[]]$Processes = @(),
        [int]$ExpectedProcessId = 0,
        [switch]$Ready
    )

    if (-not $Ready) {
        Write-Warning "Refused to stop SinpoSmart without a ready update handshake."
        return $false
    }

    $processes = @($Processes)
    if ($processes.Count -ne 1 -or $ExpectedProcessId -le 0) {
        Write-Warning "Refused to stop SinpoSmart because exactly one handshaken Qt process is required."
        return $false
    }

    $process = $processes[0]
    if (
        -not (Test-IsQtDutyGuiProcess -Process $process) -or
        [int]$process.ProcessId -ne $ExpectedProcessId
    ) {
        Write-Warning "Refused to stop SinpoSmart because the supplied process is not the handshaken Qt duty_gui.pyw process."
        return $false
    }

    $currentProcesses = @(Get-RunningDutyGuiProcesses)
    if ($currentProcesses.Count -eq 0) {
        try {
            $remainingProcess = [System.Diagnostics.Process]::GetProcessById($ExpectedProcessId)
            $remainingProcess.Dispose()
            Write-Warning "Refused to update because handshaken process $ExpectedProcessId still exists but could not be classified safely."
            return $false
        } catch [System.ArgumentException] {
            Write-Host "The handshaken SinpoSmart process $ExpectedProcessId exited cleanly."
            return $true
        } catch {
            Write-Warning "Could not confirm whether handshaken process $ExpectedProcessId exited: $_"
            return $false
        }
    }
    if (
        $currentProcesses.Count -ne 1 -or
        -not (Test-IsQtDutyGuiProcess -Process $currentProcesses[0]) -or
        [int]$currentProcesses[0].ProcessId -ne $ExpectedProcessId
    ) {
        Write-Warning "Refused to stop SinpoSmart because the running GUI process set changed after the update handshake."
        return $false
    }

    Write-Host "Closing running SinpoSmart app so the updated files can load..."
    $allClosed = $true
    try {
        Wait-Process -Id $ExpectedProcessId -Timeout 10 -ErrorAction SilentlyContinue
        if (Get-Process -Id $ExpectedProcessId -ErrorAction SilentlyContinue) {
            Stop-Process -Id $ExpectedProcessId -Force -ErrorAction Stop
        }
        if (Get-Process -Id $ExpectedProcessId -ErrorAction SilentlyContinue) {
            $allClosed = $false
            Write-Warning "Process $ExpectedProcessId is still running."
        } else {
            Write-Host "Closed process $ExpectedProcessId."
        }
    } catch {
        $allClosed = $false
        Write-Warning "Could not close process ${ExpectedProcessId}: $_"
    }
    if (-not $allClosed) {
        return $false
    }
    Start-Sleep -Milliseconds 800
    return $true
}

function Start-DutyGui {
    $entrypoint = Join-Path $packageDir "duty_gui.pyw"
    if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) {
        Write-Warning "Could not restart app because the PySide6/QML entrypoint duty_gui.pyw was not found."
        return
    }

    $finder = Join-Path $packageDir "find_winpython.ps1"
    $python = ""
    if (Test-Path -LiteralPath $finder -PathType Leaf) {
        $python = (& powershell -NoProfile -ExecutionPolicy Bypass -File $finder | Select-Object -First 1)
    }
    if (-not $python) {
        Write-Warning "Could not restart app because WinPython python.exe was not found. Set WINPYTHON_DIR or place WinPython beside the package."
        return
    }

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $python
    $startInfo.Arguments = [char]34 + $entrypoint + [char]34
    $startInfo.WorkingDirectory = $packageDir
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    [System.Diagnostics.Process]::Start($startInfo) | Out-Null
    Write-Host "Restarted SinpoSmart app."
}

function Restart-DutyGuiIfRunning {
    param(
        [object[]]$Processes = @(),
        [int]$ExpectedProcessId = 0,
        [switch]$Ready
    )

    if (Stop-RunningDutyGui -Processes $Processes -ExpectedProcessId $ExpectedProcessId -Ready:$Ready) {
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
        "rescue_video\救護影片分類GUI.py",
        "rescue_video\classify_rescue_video.py",
        "duty_rehearsal.py",
        "compare_rehearsal_records.py",
        "check_environment.py",
        "requirements.txt",
        "work_log_defaults.json"
    )
    $backupDirectories = @(
        "app_core",
        "qt_app"
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

    foreach ($relativeDirectory in $backupDirectories) {
        $sourceDirectory = Join-Path $SourceDir $relativeDirectory
        if (-not (Test-Path -LiteralPath $sourceDirectory -PathType Container)) {
            continue
        }
        $sourceRoot = $SourceDir.TrimEnd([char]92) + [string][char]92
        foreach ($sourceFile in @(Get-ChildItem -LiteralPath $sourceDirectory -Recurse -File -Force)) {
            $relative = $sourceFile.FullName.Substring($sourceRoot.Length)
            if (Test-SkipPackagePath -RelativePath $relative) {
                continue
            }
            $target = Join-Path $StageDir $relative
            $targetDir = Split-Path -Parent $target
            if (-not (Test-Path -LiteralPath $targetDir)) {
                New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
            }
            Copy-Item -LiteralPath $sourceFile.FullName -Destination $target -Force
            $copied += 1
        }
    }

    $manifestPath = Join-Path $StageDir "backup-manifest.txt"
    @(
        "Created: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "Source: $SourceDir",
        "Files: $copied",
        "Directories: $($backupDirectories -join ', ')",
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
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "duty_gui.pyw") } |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $sourceDir -and (Test-Path -LiteralPath (Join-Path $extractDir "duty_gui.pyw"))) {
        $sourceDir = $extractDir
    }
    if (-not $sourceDir -or -not (Test-Path -LiteralPath $sourceDir -PathType Container)) {
        throw "Update zip does not contain a valid package folder."
    }

    $requiredQtPackageFiles = @(
        "duty_gui.pyw",
        "qt_app\main.py",
        "qt_app\qml\Main.qml",
        "qt_app\qml\components\AppleButton.qml",
        "qt_app\qml\components\AppleCheckBox.qml",
        "qt_app\qml\components\AppleComboBox.qml",
        "qt_app\qml\components\AppleDialog.qml",
        "qt_app\qml\components\AppleTabButton.qml",
        "qt_app\qml\components\AppleTextArea.qml",
        "qt_app\qml\components\AppleTextField.qml",
        "qt_app\qml\components\AuditSummaryCard.qml",
        "qt_app\qml\components\DataSectionTitle.qml",
        "qt_app\qml\components\DataTableCell.qml",
        "qt_app\qml\components\DangerButton.qml",
        "qt_app\qml\components\DutyActionButton.qml",
        "qt_app\qml\components\DutyTaskCard.qml",
        "qt_app\qml\components\DutyTaskStatusPill.qml",
        "qt_app\qml\components\FormFieldTitle.qml",
        "qt_app\qml\components\PrimaryButton.qml",
        "qt_app\qml\components\SettingsButton.qml",
        "qt_app\qml\components\StrongHeaderTitle.qml",
        "qt_app\qml\components\ToolAddButton.qml",
        "qt_app\qml\components\ToolBrowseButton.qml",
        "qt_app\qml\components\ToolCloseButton.qml",
        "qt_app\qml\components\ToolDateStepButton.qml",
        "qt_app\qml\components\ToolFieldLabel.qml",
        "qt_app\qml\components\ToolFormCard.qml",
        "qt_app\qml\components\ToolMonthCombo.qml",
        "qt_app\qml\components\ToolPanelContent.qml",
        "qt_app\qml\components\ToolPanelHeader.qml",
        "qt_app\qml\components\ToolPanelTitle.qml",
        "qt_app\qml\components\ToolRemoveButton.qml",
        "qt_app\qml\components\ToolRunButton.qml",
        "qt_app\qml\components\ToolSectionTitle.qml",
        "qt_app\qml\components\ToolSidePanel.qml",
        "qt_app\qml\components\ToolStatusBar.qml",
        "qt_app\qml\components\WorkLogValueControl.qml",
        "qt_app\qml\components\qmldir",
        "qt_app\qml\dialogs\AccountManagerWindow.qml",
        "qt_app\qml\dialogs\RescueVideoWindow.qml",
        "qt_app\qml\dialogs\ActionConfirmations.qml",
        "qt_app\qml\dialogs\qmldir",
        "qt_app\qml\pages\DutySheetToolPanel.qml",
        "qt_app\qml\pages\RestTimeToolPanel.qml",
        "qt_app\qml\pages\MonthlyBaseToolPanel.qml",
        "qt_app\qml\pages\DailyVehicleToolPanel.qml",
        "qt_app\qml\pages\AuditFilterPanel.qml",
        "qt_app\qml\pages\WorkLogSettingsPanel.qml",
        "qt_app\qml\pages\DutyQuickToolsPanel.qml",
        "qt_app\qml\pages\DutyOperationBar.qml",
        "qt_app\qml\pages\DutyTaskArea.qml",
        "qt_app\qml\pages\SessionHeader.qml",
        "qt_app\qml\pages\qmldir",
        "qt_app\qml\styles\Design.qml",
        "qt_app\qml\styles\qmldir",
        "qt_app\workers\operational_sync_worker.py",
        "app_core\operational_sync_service.py",
        "app_core\credential_repository.py"
    )
    foreach ($relative in $requiredQtPackageFiles) {
        $requiredPath = Join-Path $sourceDir $relative
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "Update zip is missing required PySide6/QML file: $relative"
        }
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

    $runningDutyGuiProcesses = @(Get-RunningDutyGuiProcesses)
    $wasRunning = $runningDutyGuiProcesses.Count -gt 0
    if ($wasRunning) {
        if ($runningDutyGuiProcesses.Count -ne 1) {
            throw "Update postponed because exactly one SinpoSmart GUI process must be running. No process was stopped."
        }
        $runningQtProcess = $runningDutyGuiProcesses[0]
        if (-not (Test-IsQtDutyGuiProcess -Process $runningQtProcess)) {
            throw "Update postponed because the running SinpoSmart GUI is not the Qt duty_gui.pyw app. No process was stopped."
        }
        $handshakenProcessId = [int]$runningQtProcess.ProcessId
        $prepareResult = Send-UpdateLogoutEvent
        if ($prepareResult -ne "ready") {
            throw "Update postponed because the running SinpoSmart app did not report ready ($prepareResult). The app remains open."
        }
        if (-not (Stop-RunningDutyGui -Processes $runningDutyGuiProcesses -Ready -ExpectedProcessId $handshakenProcessId)) {
            throw "Update postponed because the running SinpoSmart app could not be closed safely."
        }
    }
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
