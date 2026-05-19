$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$skillRoot = Join-Path $projectRoot "skill"
$installer = Join-Path $skillRoot "install-skills-from-cloud.ps1"

if (-not (Test-Path -LiteralPath $skillRoot)) {
  throw "Cloud skill folder not found: $skillRoot"
}

if (-not (Test-Path -LiteralPath $installer)) {
  throw "Skill installer not found: $installer"
}

$skillFiles = Get-ChildItem -LiteralPath $skillRoot -Recurse -Filter "SKILL.md" -File
$skills = $skillFiles | ForEach-Object {
  $folder = Split-Path -Parent $_.FullName
  [PSCustomObject]@{
    Name = Split-Path -Leaf $folder
    Relative = $folder.Substring($skillRoot.Length).TrimStart("\")
  }
} | Sort-Object Name, Relative

if ($skills.Count -eq 0) {
  throw "No valid skills found in: $skillRoot"
}

Write-Host "Cloud skills found:"
foreach ($skill in $skills) {
  Write-Host " - $($skill.Name) [$($skill.Relative)]"
}

& PowerShell -ExecutionPolicy Bypass -File $installer
