$ErrorActionPreference = "Stop"

$remoteVersionUrl = "https://drive.google.com/uc?export=download&id=11iI5g_86MZG0Ck8PdngRjWz8V7fMuikp"
$remoteZipUrl = "https://drive.google.com/uc?export=download&id=1DB6-0fFBaCciV5DaxeNfIqczwfKYhge0"

$packageDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$localVersionPath = Join-Path $packageDir "VERSION.txt"
$parentDir = Split-Path -Parent $packageDir
$backupDir = Join-Path $parentDir "_update_backups"
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

function Copy-UpdateTree {
    param(
        [string]$SourceDir,
        [string]$DestDir
    )

    $skipDirs = @("logs", "runtime_outputs", "tmp", "snapshots", "__pycache__", "artifacts")
    $alwaysSkipFiles = @(
        "duty_sheet_legacy\config.json",
        "duty_sheet_legacy\effortless-leaf-353501-63492cc3ece4.json",
        "daily_vehicle_legacy\.env"
    )
    $preserveIfExistsFiles = @(
        "rest_time_automation_config.json"
    )

    $slash = [string][char]92
    $sourceRoot = $SourceDir.TrimEnd([char]92) + $slash
    Get-ChildItem -LiteralPath $SourceDir -Recurse -File -Force | ForEach-Object {
        $relative = $_.FullName.Substring($sourceRoot.Length)
        $parts = $relative -split "[\\/]"
        if ($parts | Where-Object { $skipDirs -contains $_ }) {
            return
        }
        $target = Join-Path $DestDir $relative
        if ($alwaysSkipFiles -contains $relative) {
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

if (-not (Test-Path -LiteralPath $localVersionPath)) {
    "0" | Set-Content -LiteralPath $localVersionPath -Encoding UTF8
}

$localVersion = (Get-Content -LiteralPath $localVersionPath -Raw -Encoding UTF8).Trim()
$remoteVersion = Get-TextFromUrl -Url $remoteVersionUrl

Write-Host "Local version : $localVersion"
Write-Host "Remote version: $remoteVersion"

if ([string]::CompareOrdinal($remoteVersion, $localVersion) -le 0) {
    Write-Host "Already up to date."
    exit 0
}

try {
    New-Item -ItemType Directory -Path $tempDir | Out-Null
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

    Write-Host "Downloading update package..."
    Invoke-WebRequest -Uri $remoteZipUrl -OutFile $zipPath -UseBasicParsing -MaximumRedirection 5

    if (-not (Test-Path -LiteralPath $zipPath) -or (Get-Item -LiteralPath $zipPath).Length -lt 1024) {
        throw "Downloaded package is missing or too small."
    }

    $backupZip = Join-Path $backupDir "SinpoSmart-package-backup-$stamp.zip"
    Write-Host "Creating backup: $backupZip"
    Compress-Archive -LiteralPath (Join-Path $packageDir "*") -DestinationPath $backupZip -Force

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
    if ($packageVersion -ne $remoteVersion) {
        throw "Update version mismatch. Remote VERSION.txt is $remoteVersion but package VERSION.txt is $packageVersion."
    }

    Copy-UpdateTree -SourceDir $sourceDir -DestDir $packageDir
    $packageVersion | Set-Content -LiteralPath $localVersionPath -Encoding UTF8

    Write-Host "Update completed. Restart the app if it is running."
} finally {
    try {
        if (Test-Path -LiteralPath $tempDir) {
            Remove-Item -LiteralPath $tempDir -Recurse -Force
        }
    } catch {
        Write-Warning "Could not remove temporary update folder: $tempDir"
    }
}
