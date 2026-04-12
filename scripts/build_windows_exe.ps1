param(
    [string]$Name = "smte"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$sourceScript = Join-Path $repoRoot "src\steam_market_to_excel.py"
$buildDir = Join-Path $repoRoot "build"
$distDir = Join-Path $repoRoot "dist"
$exePath = Join-Path $distDir "$Name.exe"

if (-not (Test-Path -LiteralPath $sourceScript)) {
    throw "Could not find source script at $sourceScript"
}

# If an older executable already exists, remove it first.
# This makes rebuilds more predictable and avoids stale-success confusion.
if (Test-Path -LiteralPath $exePath) {
    Write-Host "Removing previous executable: $exePath"

    $removed = $false
    for ($attempt = 1; $attempt -le 10; $attempt++) {
        try {
            Remove-Item -LiteralPath $exePath -Force
            $removed = $true
            break
        }
        catch {
            if ($attempt -eq 10) {
                throw "Could not remove $exePath. Close any running copy of the executable or choose a different -Name value, then try again."
            }
            Start-Sleep -Milliseconds (200 * $attempt)
        }
    }

    if (-not $removed) {
        throw "Previous executable still exists at $exePath"
    }
}

Write-Host "Building Windows executable from $sourceScript"

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --specpath $buildDir `
    --distpath $distDir `
    --name $Name `
    $sourceScript

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if (Test-Path -LiteralPath $exePath) {
    Write-Host "Built executable: $exePath"
}
else {
    throw "Expected executable was not created at $exePath"
}
