$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcherCandidates = @(
    (Join-Path $projectDir "RUN_DUTY_GUI_WINPYTHON.vbs"),
    (Join-Path $projectDir "start_duty_gui_no_console.vbs")
)
$launcher = $launcherCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $launcher) {
    throw "Cannot find a no-console launcher in $projectDir"
}

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "SinpoSmart.lnk"
$iconPath = Join-Path $projectDir "duty_tray_icon.ico"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $env:WINDIR "System32\wscript.exe"
$shortcut.Arguments = '"' + $launcher + '"'
$shortcut.WorkingDirectory = $projectDir
$shortcut.Description = "Start SinpoSmart duty automation after Windows login"
if (Test-Path -LiteralPath $iconPath) {
    $shortcut.IconLocation = $iconPath
}
$shortcut.Save()

Write-Host "Installed startup shortcut:"
Write-Host $shortcutPath
