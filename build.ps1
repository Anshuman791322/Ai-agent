param(
    [switch]$Clean,
    [switch]$BuildInstaller,
    [switch]$NoVenv
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

function Resolve-Python {
    param([bool]$UseVenv)

    if (-not $UseVenv) {
        return "python"
    }

    $venvPath = Join-Path $projectRoot ".venv"
    $pythonExe = Join-Path $venvPath "Scripts\python.exe"

    if (-not (Test-Path $pythonExe)) {
        Write-Host "Creating virtual environment at $venvPath"
        python -m venv $venvPath
    }

    return $pythonExe
}

$python = Resolve-Python -UseVenv:(-not $NoVenv)

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $projectRoot "build")
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $projectRoot "dist")
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $projectRoot "installer-output")
}

& $python -m pip install --upgrade pip wheel
& $python -m pip install -r requirements.txt pyinstaller
& $python -m PyInstaller --noconfirm jarvis_local.spec

$distDir = Join-Path $projectRoot "dist\JARVIS Local"
if (-not (Test-Path $distDir)) {
    throw "Packaged output was not created at $distDir"
}

Write-Host "Packaged app created at $distDir"

if ($BuildInstaller) {
    $programFilesX86 = ${env:ProgramFiles(x86)}
    $innoBase = if ($programFilesX86) { $programFilesX86 } else { $env:ProgramFiles }
    $isccCandidates = @(
        (Join-Path $innoBase "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    $iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not (Test-Path $iscc)) {
        throw "Inno Setup 6 was not found at $iscc"
    }

    & $iscc (Join-Path $projectRoot "installer.iss")
    Write-Host "Installer created in $(Join-Path $projectRoot 'installer-output')"
}
