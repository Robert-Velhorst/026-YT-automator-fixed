[CmdletBinding()]
param(
    [switch]$Public,
    [string]$NgrokDomain,
    [int]$Port = 5000,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Backend = Join-Path $Root "backend"
$Runtime = Join-Path $Root ".runtime"
$StateFile = Join-Path $Runtime "processes.json"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$EnvFile = Join-Path $Backend ".env"

function Test-PortAvailable([int]$Candidate) {
    $Listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Candidate)
    $Listener.Server.ExclusiveAddressUse = $true
    try { $Listener.Start(); return $true }
    catch { return $false }
    finally { $Listener.Stop() }
}

function Stop-OwnedTree([int]$RootId) {
    $Processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $Ids = [Collections.Generic.List[int]]::new()
    $Queue = [Collections.Generic.Queue[int]]::new()
    $Queue.Enqueue($RootId)
    while ($Queue.Count) {
        $Current = $Queue.Dequeue()
        $Ids.Add($Current)
        foreach ($Child in $Processes | Where-Object { $_.ParentProcessId -eq $Current }) { $Queue.Enqueue($Child.ProcessId) }
    }
    for ($Index = $Ids.Count - 1; $Index -ge 0; $Index--) {
        Stop-Process -Id $Ids[$Index] -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path $Python) -or -not (Test-Path $EnvFile) -or -not (Test-Path (Join-Path $Root "frontend\dist\index.html"))) {
    throw "StudioPilot is not set up. Run scripts\windows\setup.ps1 first."
}
if (Test-Path $StateFile) { throw "StudioPilot already has a runtime state file. Run scripts\windows\stop.ps1 first." }
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
if ($Port -lt 1024 -or $Port -gt 65535) { throw "Port must be between 1024 and 65535." }
$RequestedPort = $Port
while (-not (Test-PortAvailable $Port) -and $Port -lt 65535) { $Port++ }
if ($Port -ne $RequestedPort) { Write-Warning "Port $RequestedPort is in use; using $Port instead." }

$Started = [ordered]@{}
$PublicUrl = $null
try {
    if ($Public) {
        $Ngrok = Get-Command ngrok.exe -ErrorAction SilentlyContinue
        if (-not $Ngrok) { throw "ngrok is required for -Public. Install it and run ngrok config add-authtoken first." }
        $HashLine = Select-String -LiteralPath $EnvFile -Pattern '^OPERATOR_PASSWORD_HASH=(.+)$'
        if (-not $HashLine -or -not $HashLine.Matches[0].Groups[1].Value) {
            throw "Public mode requires OPERATOR_PASSWORD_HASH in backend\.env. Re-run setup or add a Werkzeug password hash."
        }
        $NgrokApiPort = 4040
        while (-not (Test-PortAvailable $NgrokApiPort) -and $NgrokApiPort -lt 65535) { $NgrokApiPort++ }
        $DefaultNgrokConfig = Join-Path $env:LOCALAPPDATA "ngrok\ngrok.yml"
        if (-not (Test-Path $DefaultNgrokConfig)) { throw "The default ngrok configuration was not found. Run ngrok config add-authtoken first." }
        $NgrokOverride = Join-Path $Runtime "ngrok-agent.yml"
        @("version: 3", "agent:", "  web_addr: 127.0.0.1:$NgrokApiPort") | Set-Content -LiteralPath $NgrokOverride -Encoding ascii
        $Arguments = @("http", "$Port", "--log=stdout", "--config", $DefaultNgrokConfig, "--config", $NgrokOverride)
        if ($NgrokDomain) { $Arguments += "--url=$NgrokDomain" }
        $NgrokProcess = Start-Process -FilePath $Ngrok.Source -ArgumentList $Arguments -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $Runtime "ngrok.out.log") -RedirectStandardError (Join-Path $Runtime "ngrok.err.log")
        $Started.ngrok = $NgrokProcess.Id
        for ($attempt = 0; $attempt -lt 120 -and -not $PublicUrl; $attempt++) {
            Start-Sleep -Milliseconds 500
            if ($NgrokProcess.HasExited) { break }
            try {
                $Tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:$NgrokApiPort/api/tunnels" -TimeoutSec 2
                $PublicUrl = ($Tunnels.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1).public_url
            } catch { }
        }
        if (-not $PublicUrl) { throw "ngrok did not expose an HTTPS tunnel. Check .runtime\ngrok.err.log for endpoint or account conflicts." }
        $env:APP_ENV = "production"
        $env:PUBLIC_BASE_URL = $PublicUrl
        $env:FRONTEND_URL = $PublicUrl
        $env:CORS_ORIGINS = $PublicUrl
        $env:LOCAL_AUTH_BYPASS = "false"
    } else {
        $env:APP_ENV = "development"
        $env:PUBLIC_BASE_URL = ""
        $env:FRONTEND_URL = "http://127.0.0.1:$Port"
        $env:CORS_ORIGINS = "http://127.0.0.1:$Port,http://localhost:$Port"
        $env:LOCAL_AUTH_BYPASS = "true"
    }
    $env:PORT = "$Port"

    Push-Location $Backend
    try {
        & $Python -m flask --app app db upgrade
        $MigrationExit = $LASTEXITCODE
    }
    finally { Pop-Location }
    if ($MigrationExit -ne 0) { throw "Database migration failed." }

    $Api = Start-Process -FilePath $Python -ArgumentList @("-m", "waitress", "--listen=127.0.0.1:$Port", "app:app") `
        -WorkingDirectory $Backend -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Runtime "api.out.log") `
        -RedirectStandardError (Join-Path $Runtime "api.err.log")
    $Started.api = $Api.Id
    $Worker = Start-Process -FilePath $Python -ArgumentList @("worker.py") -WorkingDirectory $Backend -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $Runtime "worker.out.log") -RedirectStandardError (Join-Path $Runtime "worker.err.log")
    $Started.worker = $Worker.Id

    $Healthy = $false
    for ($attempt = 0; $attempt -lt 120 -and -not $Healthy; $attempt++) {
        Start-Sleep -Milliseconds 500
        try { $Healthy = (Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2).status -eq "healthy" } catch { }
    }
    if (-not $Healthy) { throw "The API did not become healthy. Check .runtime\api.err.log." }

    [ordered]@{
        started_at = [DateTime]::UtcNow.ToString("o")
        root = $Root
        port = $Port
        ngrok_api_port = $NgrokApiPort
        public_url = $PublicUrl
        processes = $Started
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $StateFile -Encoding utf8

    $Url = if ($PublicUrl) { $PublicUrl } else { "http://127.0.0.1:$Port" }
    Write-Host "StudioPilot is running at $Url"
    if ($OpenBrowser) { Start-Process $Url }
} catch {
    foreach ($Id in $Started.Values) {
        Stop-OwnedTree $Id
    }
    if (Test-Path -LiteralPath $StateFile) { [IO.File]::Delete($StateFile) }
    throw
}
