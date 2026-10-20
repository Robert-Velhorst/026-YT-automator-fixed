[CmdletBinding()]
param()

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Checks = [ordered]@{
    "Python environment" = Test-Path $Python
    "Backend environment" = Test-Path (Join-Path $Root "backend\.env")
    "Built interface" = Test-Path (Join-Path $Root "frontend\dist\index.html")
    "FFmpeg for long transcription" = [bool](Get-Command ffmpeg.exe -ErrorAction SilentlyContinue)
}
if ($Checks["Python environment"] -and $Checks["Backend environment"]) {
    Push-Location (Join-Path $Root "backend")
    try {
        & $Python -c "from app import app; print('Runtime configuration: valid')"
        $Checks["Runtime configuration"] = $LASTEXITCODE -eq 0
        & $Python -m flask --app app db current
        $Checks["Database migration"] = $LASTEXITCODE -eq 0
    } catch { $Checks["Runtime configuration"] = $false }
    finally { Pop-Location }
}
try {
    $RuntimeState = Join-Path $Root ".runtime\processes.json"
    $RuntimePort = if (Test-Path $RuntimeState) { (Get-Content $RuntimeState -Raw | ConvertFrom-Json).port } else { 5000 }
    $Checks["Running API"] = (Invoke-RestMethod -Uri "http://127.0.0.1:$RuntimePort/api/health" -TimeoutSec 2).status -eq "healthy"
} catch { $Checks["Running API"] = $false }

$Checks.GetEnumerator() | ForEach-Object {
    $Label = if ($_.Value) { "OK" } else { "MISSING" }
    Write-Host ("[{0}] {1}" -f $Label, $_.Key)
}
if (-not $Checks["Python environment"] -or -not $Checks["Backend environment"] -or -not $Checks["Built interface"] -or -not $Checks["Runtime configuration"]) { exit 1 }
