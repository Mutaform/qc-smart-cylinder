<#
Build the QC Smart Cylinder extension ZIP.

  powershell -ExecutionPolicy Bypass -File tools/build_release.ps1 [-Release]

The version is read from qc_smart_cylinder/blender_manifest.toml and becomes
part of the archive name, so the two can never disagree.

Output goes to <project>\Dev\dist\ next to the repository (on CI: the checkout
root, because the Pages workflow publishes from there). With -Release the
archive is also copied to <project>\Zip Addon\ and any previous archive there
is moved to Zip Addon\old\.
#>
param(
    [switch]$Release
)

$ErrorActionPreference = "Stop"

$addonId = "qc_smart_cylinder"
$repoRoot = Split-Path -Parent $PSScriptRoot
$addonDir = Join-Path $repoRoot $addonId
$manifest = Join-Path $addonDir "blender_manifest.toml"

if (-not (Test-Path -LiteralPath $manifest)) {
    throw "Missing blender_manifest.toml in $addonDir"
}

$manifestText = [System.IO.File]::ReadAllText($manifest, [System.Text.Encoding]::UTF8)
$versionMatch = [regex]::Match($manifestText, '(?m)^\s*version\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) {
    throw "No version line found in $manifest"
}
$version = $versionMatch.Groups[1].Value

if ($env:GITHUB_ACTIONS -eq 'true') {
    $outRoot = $repoRoot
} else {
    $outRoot = Join-Path (Split-Path -Parent $repoRoot) "Dev"
    if (-not (Test-Path -LiteralPath $outRoot)) {
        New-Item -ItemType Directory -Force -Path $outRoot | Out-Null
    }
}
$distDir = Join-Path $outRoot "dist"
$zipName = "$addonId-$version.zip"
$zipPath = Join-Path $distDir $zipName

if (Test-Path -LiteralPath $distDir) {
    Remove-Item -LiteralPath $distDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $distDir | Out-Null

# Stage a clean copy of the package: no caches, no editor leftovers.
$stagingRoot = Join-Path $distDir "_stage"
$stagingAddon = Join-Path $stagingRoot $addonId
New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null
Copy-Item -LiteralPath $addonDir -Destination $stagingAddon -Recurse -Force

Get-ChildItem -LiteralPath $stagingAddon -Directory -Recurse -Filter "__pycache__" |
    Remove-Item -Recurse -Force

Get-ChildItem -LiteralPath $stagingAddon -File -Recurse |
    Where-Object {
        $_.Extension -in @(".pyc", ".pyo") -or
        $_.Name -in @(".DS_Store", "Thumbs.db") -or
        $_.Name -match "\.blend\d+$"
    } |
    Remove-Item -Force

# blender_manifest.toml must sit at the root of the archive, so the archive is
# built from the *contents* of the package folder, not from the folder itself.
Compress-Archive -Path (Join-Path $stagingAddon "*") -DestinationPath $zipPath -Force
Remove-Item -LiteralPath $stagingRoot -Recurse -Force

Write-Host "Built $zipPath"

if ($Release -and $env:GITHUB_ACTIONS -ne 'true') {
    $zipAddonDir = Join-Path (Split-Path -Parent $repoRoot) "Zip Addon"
    $oldDir = Join-Path $zipAddonDir "old"
    New-Item -ItemType Directory -Force -Path $oldDir | Out-Null

    Get-ChildItem -LiteralPath $zipAddonDir -File -Filter "*.zip" |
        Where-Object { $_.Name -ne $zipName } |
        ForEach-Object {
            Move-Item -LiteralPath $_.FullName -Destination (Join-Path $oldDir $_.Name) -Force
            Write-Host "Moved previous $($_.Name) to old\"
        }

    Copy-Item -LiteralPath $zipPath -Destination (Join-Path $zipAddonDir $zipName) -Force
    Write-Host "Released $(Join-Path $zipAddonDir $zipName)"
}
