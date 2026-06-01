$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$finder = Join-Path $projectDir "find_winpython.ps1"
$pythonw = ""
if (Test-Path -LiteralPath $finder) {
    $pythonw = (& powershell -NoProfile -ExecutionPolicy Bypass -File $finder -Windowed | Select-Object -First 1)
}
if (-not $pythonw) {
    $localPythonw = "C:\Users\User\AppData\Local\Python\bin\pythonw.exe"
    if (Test-Path -LiteralPath $localPythonw) {
        $pythonw = $localPythonw
    } else {
        $pythonw = "pythonw.exe"
    }
}

$entrypoint = Join-Path $projectDir "duty_gui.pyw"
if (-not (Test-Path -LiteralPath $entrypoint)) {
    throw "Cannot find duty_gui.pyw in $projectDir"
}

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "SinpoSmart.lnk"
$iconPath = Join-Path $projectDir "duty_tray_icon.ico"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + $entrypoint + '"'
$shortcut.WorkingDirectory = $projectDir
$shortcut.Description = "Start SinpoSmart duty automation after Windows login"
if (Test-Path -LiteralPath $iconPath) {
    $shortcut.IconLocation = $iconPath
}
$shortcut.Save()

Write-Host "Installed startup shortcut:"
Write-Host $shortcutPath
