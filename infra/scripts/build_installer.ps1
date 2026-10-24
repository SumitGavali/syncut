<#
.SYNOPSIS
    Builds the SyncCut standalone package and creates a self-contained Windows portable installer/zip.
.DESCRIPTION
    Runs PyInstaller with synccut.spec, ensuring FFmpeg/ffprobe, web templates,
    and Python dependencies are fully packaged so it can run on any Windows PC
    without Python installed.
#>

param(
    [switch]$SkipBuild = $false
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $ProjectRoot

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  SyncCut Windows Standalone Packager        " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# 1. Verify ffmpeg binaries
$ffmpegDir = Join-Path $ProjectRoot "synccut\media\ffmpeg_bin"
$ffmpegExe = Join-Path $ffmpegDir "ffmpeg.exe"
$ffprobeExe = Join-Path $ffmpegDir "ffprobe.exe"

if (-not (Test-Path $ffmpegExe) -or -not (Test-Path $ffprobeExe)) {
    Write-Host "[!] Checking system ffmpeg..." -ForegroundColor Yellow
    $sysFfmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
    $sysFfprobe = (Get-Command ffprobe -ErrorAction SilentlyContinue).Source
    if ($sysFfmpeg -and $sysFfprobe) {
        New-Item -ItemType Directory -Path $ffmpegDir -Force | Out-Null
        Copy-Item $sysFfmpeg $ffmpegExe
        Copy-Item $sysFfprobe $ffprobeExe
        Write-Host "[+] Copied ffmpeg binaries into ffmpeg_bin/" -ForegroundColor Green
    } else {
        Write-Error "FFmpeg/ffprobe binaries not found. Please place ffmpeg.exe and ffprobe.exe into ffmpeg_bin/."
    }
}

# 2. Run PyInstaller
if (-not $SkipBuild) {
    Write-Host "[*] Building SyncCut executable with PyInstaller..." -ForegroundColor Cyan
    pyinstaller --clean --noconfirm infra\synccut.spec
    if ($LASTEXITCODE -ne 0) {
        Write-Error "PyInstaller build failed with exit code $LASTEXITCODE."
    }
}

# 3. Verify dist folder
$distDir = Join-Path $ProjectRoot "dist\SyncCut"
$exePath = Join-Path $distDir "SyncCut.exe"

if (-not (Test-Path $exePath)) {
    Write-Error "Build output SyncCut.exe not found in $distDir."
}

Write-Host "[+] Build successful: $exePath" -ForegroundColor Green

# 4. Create Desktop Launcher and Readme in dist
$readmePath = Join-Path $distDir "README-LOCAL.txt"
@"
SyncCut — Local-First Audio Sync & Multi-Camera Rough Cut
=========================================================

HOW TO RUN:
1. Double-click SyncCut.exe
2. Your default web browser will automatically open at:
   http://127.0.0.1:<port>/app
3. Drop your audio/video footage and run Sync.

PRIVACY & FOOTAGE:
- Footage NEVER leaves your machine.
- All audio processing and sync runs locally on your computer.
- No Python installation required.
"@ | Out-File -FilePath $readmePath -Encoding utf8

# 5. Create Standalone Distribution Zip (Windows Portable Installer package)
$zipOutput = Join-Path $ProjectRoot "dist\SyncCut-Windows-x64.zip"
if (Test-Path $zipOutput) {
    Remove-Item -Force $zipOutput
}

Write-Host "[*] Creating distribution zip: $zipOutput ..." -ForegroundColor Cyan
Compress-Archive -Path "$distDir\*" -DestinationPath $zipOutput -Force

Write-Host "=============================================" -ForegroundColor Green
Write-Host "  SyncCut Packaging Completed!              " -ForegroundColor Green
Write-Host "  Portable Package: $zipOutput              " -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
