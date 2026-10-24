#Requires -Version 5.1
<#
.SYNOPSIS
  Git-mv SyncCut flat root modules into the synccut/ package layout (preserves history).

.USAGE
  From repo root:
    powershell -ExecutionPolicy Bypass -File .\infra\scripts\migrate_to_package.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))

function Ensure-Dir([string]$Path) {
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Git-Mv([string]$Src, [string]$Dst) {
    if (-not (Test-Path $Src)) {
        Write-Warning "SKIP (missing): $Src"
        return
    }
    $dstDir = Split-Path -Parent $Dst
    Ensure-Dir $dstDir
    if (Test-Path $Dst) {
        Write-Warning "SKIP (exists): $Dst"
        return
    }
    Write-Host "git mv $Src -> $Dst"
    git mv -- "$Src" "$Dst"
}

Write-Host "=== SyncCut package migration (git mv) ==="
Write-Host "CWD: $(Get-Location)"

# --- Package root (config / paths) ---
Git-Mv "config.py"              "synccut/config.py"
Git-Mv "paths.py"               "synccut/paths.py"

# --- core ---
Git-Mv "sync_engine.py"         "synccut/core/sync_engine.py"
Git-Mv "drift.py"               "synccut/core/drift.py"
Git-Mv "confidence.py"          "synccut/core/confidence.py"
Git-Mv "robustness.py"          "synccut/core/robustness.py"
Git-Mv "camera_switch.py"       "synccut/core/camera_switch.py"

# --- ai ---
Git-Mv "rough_cut.py"           "synccut/ai/rough_cut.py"

# --- media ---
Git-Mv "extract.py"             "synccut/media/extract.py"
if (Test-Path "ffmpeg_bin") {
    Git-Mv "ffmpeg_bin"         "synccut/media/ffmpeg_bin"
}

# --- export ---
Git-Mv "timeline_builder.py"    "synccut/export/timeline_builder.py"
Git-Mv "fcp7_exporter.py"       "synccut/export/fcp7_exporter.py"
Git-Mv "export_switch_timeline.py" "synccut/export/switch_timeline.py"

# --- api ---
Git-Mv "job_manager.py"         "synccut/api/job_manager.py"
Git-Mv "db.py"                  "synccut/api/db.py"
# app.py stays as a thin root shim; routes live under synccut/api/routes.py (created separately)
if (Test-Path "templates") {
    # Move template files into package (directory may already exist)
    Ensure-Dir "synccut/api/templates"
    Get-ChildItem "templates" -File | ForEach-Object {
        Git-Mv $_.FullName.Substring((Get-Location).Path.Length + 1).Replace("\", "/") `
               ("synccut/api/templates/" + $_.Name)
    }
}
if (Test-Path "static") {
    Ensure-Dir "synccut/api/static"
    # Prefer moving the whole tree if git can; otherwise file-by-file
    $staticChildren = Get-ChildItem "static" -Force
    if ($staticChildren.Count -gt 0) {
        git mv -- static/* synccut/api/static/ 2>$null
        if ($LASTEXITCODE -ne 0) {
            Get-ChildItem "static" -Recurse -File | ForEach-Object {
                $rel = $_.FullName.Substring((Resolve-Path "static").Path.Length + 1).Replace("\", "/")
                Git-Mv ("static/" + $rel) ("synccut/api/static/" + $rel)
            }
        }
    }
}

# --- desktop ---
Git-Mv "synccut_gui.py"         "synccut/desktop/gui.py"

# --- cli ---
Git-Mv "synccut.py"             "synccut/cli/main.py"

# --- infra ---
if (Test-Path "Dockerfile") {
    Git-Mv "Dockerfile"         "infra/Dockerfile"
}
if (Test-Path "build_installer.ps1") {
    Git-Mv "build_installer.ps1" "infra/scripts/build_installer.ps1"
}
if (Test-Path "Procfile") {
    Git-Mv "Procfile"           "infra/Procfile"
}
if (Test-Path "synccut.spec") {
    Git-Mv "synccut.spec"       "infra/synccut.spec"
}

Write-Host ""
Write-Host "=== Migration complete. Next: fix imports + recreate root app.py shim. ==="
git status --short
