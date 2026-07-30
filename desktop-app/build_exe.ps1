# Requires: PowerShell on Windows
# Usage: .\build_exe.ps1
# Output: dist/SeedreamDesktop.exe + copy to Desktop

param(
    [switch]$SkipDesktopCopy
)

$ErrorActionPreference = 'Stop'

Set-Location -Path (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "[build] Working dir: $(Get-Location)"

function Test-Venv {
    param([string]$PythonPath)
    if (!(Test-Path $PythonPath)) {
        return $false
    }
    try {
        & $PythonPath -c "import sys; print(sys.executable)" *> $null
        return $true
    } catch {
        return $false
    }
}

if (!(Test-Path .venv) -or !(Test-Venv ".\.venv\Scripts\python.exe")) {
    Write-Host "[build] Recreating virtual environment..."
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue .venv
    Write-Host "[build] Creating virtual environment..."
    python -m venv .venv
}

Write-Host "[build] Activating virtual environment..."
. .venv\Scripts\Activate.ps1

Write-Host "[build] Installing dependencies..."
python -m pip install --upgrade pip > $null
python -m pip install -r requirements.txt > $null
python -m pip install pyinstaller==6.10.0 > $null

if (!(Test-Path "icon-placeholder.png")) {
    Write-Host "[build] Generating icon-placeholder.png..."
    python make_icon.py
}

if (!(Test-Path "icon.ico")) {
    Write-Host "[build] Generating icon.ico..."
    python -c "from PIL import Image; Image.open('icon-placeholder.png').save('icon.ico', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
}

if (!(Test-Path "$PSScriptRoot\..\server\__init__.py")) {
    throw "Expected server package in $PSScriptRoot\..\server"
}

Write-Host "[build] Cleaning previous builds..."
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist

Write-Host "[build] Stopping previous SeedreamDesktop if running..."
Get-Process -Name "SeedreamDesktop" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

Write-Host "[build] Building executable..."
python -m PyInstaller --noconfirm --clean --distpath "$PSScriptRoot\dist" --workpath "$PSScriptRoot\build" SeedreamDesktop.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$exePath = Join-Path $PSScriptRoot "dist\SeedreamDesktop.exe"
if (!(Test-Path $exePath)) {
    throw "Build finished but exe not found: $exePath"
}

Write-Host "[build] Done. App: $exePath"

if (-not $SkipDesktopCopy) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $desktopExe = Join-Path $desktop "SeedreamDesktop.exe"
    Write-Host "[build] Copying to Desktop: $desktopExe"
    Copy-Item -Path $exePath -Destination $desktopExe -Force

    $exampleSrc = Join-Path $PSScriptRoot "secrets.example.json"
    $secretsSrc = Join-Path $PSScriptRoot "secrets.json"
    $desktopSecrets = Join-Path $desktop "secrets.json"
    if ((Test-Path $secretsSrc) -and -not (Test-Path $desktopSecrets)) {
        Copy-Item -Path $secretsSrc -Destination $desktopSecrets -Force
        Write-Host "[build] Copied secrets.json to Desktop (first run)"
    } elseif (-not (Test-Path $desktopSecrets)) {
        Copy-Item -Path $exampleSrc -Destination $desktopSecrets -Force
        Write-Host "[build] Created empty secrets.json on Desktop - set Replicate token in Settings"
    }

    $shortcutPath = Join-Path $desktop "SeedreamDesktop.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $desktopExe
    $shortcut.WorkingDirectory = $desktop
    $shortcut.IconLocation = "$desktopExe,0"
    $shortcut.Description = "Seedream Studio"
    $shortcut.Save()
    Write-Host "[build] Shortcut updated: $shortcutPath"
}
