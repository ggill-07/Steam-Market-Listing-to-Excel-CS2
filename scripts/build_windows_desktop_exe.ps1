param(
    [string]$Name = "smte-desktop"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$sourceScript = Join-Path $repoRoot "src\smte_desktop.py"
$iconIco = Join-Path $repoRoot "assets\smte_desktop_icon.ico"
$iconPng = Join-Path $repoRoot "assets\smte_desktop_icon.png"
$buildDir = Join-Path $repoRoot "build"
$distDir = Join-Path $repoRoot "dist"
$exePath = Join-Path $distDir "$Name.exe"

if (-not (Test-Path -LiteralPath $sourceScript)) {
    throw "Could not find desktop source script at $sourceScript"
}

if (-not (Test-Path -LiteralPath $iconIco)) {
    throw "Could not find desktop icon at $iconIco"
}

if (-not (Test-Path -LiteralPath $iconPng)) {
    throw "Could not find desktop icon at $iconPng"
}

if (Test-Path -LiteralPath $exePath) {
    Write-Host "Removing previous desktop executable: $exePath"

    $removed = $false
    for ($attempt = 1; $attempt -le 10; $attempt++) {
        try {
            Remove-Item -LiteralPath $exePath -Force
            $removed = $true
            break
        }
        catch {
            if ($attempt -eq 10) {
                throw "Could not remove $exePath. Close any running copy of the desktop app or choose a different -Name value, then try again."
            }
            Start-Sleep -Milliseconds (200 * $attempt)
        }
    }

    if (-not $removed) {
        throw "Previous desktop executable still exists at $exePath"
    }
}

Write-Host "Building Windows desktop executable from $sourceScript"

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --icon $iconIco `
    --add-data "${iconIco};assets" `
    --add-data "${iconPng};assets" `
    --specpath $buildDir `
    --distpath $distDir `
    --name $Name `
    $sourceScript

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if (Test-Path -LiteralPath $exePath) {
    Write-Host "Built desktop executable: $exePath"
}
else {
    throw "Expected desktop executable was not created at $exePath"
}
