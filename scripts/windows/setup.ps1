[CmdletBinding()]
param(
    [string]$OperatorPassword,
    [string]$PythonExecutable,
    [string]$NodeExecutable = "node.exe",
    [string]$NpmCli
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$BackendEnv = Join-Path $Root "backend\.env"

function Get-PlainText([Security.SecureString]$Value) {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

Write-Host "Checking Python..."
$PythonForSetupArgs = @()
$PythonForSetup = if (Test-Path $VenvPython) {
    $VenvPython
} elseif ($PythonExecutable) {
    $PythonExecutable
} else {
    if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) {
        throw "Python 3.13-3.15 is required. Install Python from python.org, including the py launcher."
    }
$SupportedLauncher = @("-3.15", "-3.14", "-3.13") | Where-Object {
        & py.exe $_ -c "import sys" 2>$null
        $LASTEXITCODE -eq 0
    } | Select-Object -First 1
    if (-not $SupportedLauncher) {
        throw "Python 3.13-3.15 is required. Install Python from python.org, including the py launcher."
    }
    $PythonForSetupArgs = @($SupportedLauncher)
    "py.exe"
}
if (-not (Get-Command $PythonForSetup -ErrorAction SilentlyContinue)) {
    throw "Python 3.13-3.15 is required. Install Python from python.org, including the py launcher."
}
$VersionArgs = @($PythonForSetupArgs + @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"))
$Version = & $PythonForSetup @VersionArgs
$Parts = $Version.Split(".")
if ([int]$Parts[0] -ne 3 -or [int]$Parts[1] -lt 13 -or [int]$Parts[1] -gt 15) {
    throw "Python 3.13-3.15 is required; py -3 selected $Version."
}

Write-Host "Checking Node.js..."
$Node = Get-Command $NodeExecutable -ErrorAction SilentlyContinue
$Npm = if ($NpmCli) { Test-Path $NpmCli } else { [bool](Get-Command npm.cmd -ErrorAction SilentlyContinue) }
if (-not $Node -or -not $Npm) { throw "Node.js 24.22.0 LTS or 26.12.0 Current with npm is required." }
$NodeVersion = [Version]((& $NodeExecutable --version).TrimStart("v"))
$NodeSupported = ($NodeVersion.Major -eq 24 -and $NodeVersion -ge [Version]"24.22.0") -or `
    ($NodeVersion.Major -eq 26 -and $NodeVersion -ge [Version]"26.12.0") -or $NodeVersion.Major -gt 26
if (-not $NodeSupported) { throw "Node.js 24.22.0 LTS or 26.12.0 Current is required. Detected Node.js $NodeVersion." }

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating the private Python environment..."
    & $PythonForSetup @PythonForSetupArgs -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
}
Write-Host "Installing backend dependencies..."
& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $Root "backend\requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed." }

if (-not (Test-Path $BackendEnv)) {
    if (-not $OperatorPassword) {
        $OperatorPassword = Get-PlainText (Read-Host "Choose an operator password for provider and production access" -AsSecureString)
    }
    if ($OperatorPassword.Length -lt 12) { throw "The operator password must contain at least 12 characters." }
    $env:STUDIOPILOT_SETUP_PASSWORD = $OperatorPassword
    try {
        $OperatorHash = & $VenvPython -c "import os; from werkzeug.security import generate_password_hash; print(generate_password_hash(os.environ['STUDIOPILOT_SETUP_PASSWORD']))"
    } finally {
        Remove-Item Env:STUDIOPILOT_SETUP_PASSWORD -ErrorAction SilentlyContinue
    }
    $Generated = & $VenvPython -c "import secrets; from cryptography.fernet import Fernet; print(secrets.token_urlsafe(48)); print(Fernet.generate_key().decode()); print(secrets.token_urlsafe(48))"
    @(
        "APP_ENV=development"
        "SECRET_KEY=$($Generated[0])"
        "DATABASE_URL=sqlite:///automator.db"
        "UPLOAD_FOLDER=uploads"
        "GENERATED_FOLDER=generated"
        "MAX_CONTENT_LENGTH=2147483648"
        "GOOGLE_CLIENT_SECRETS_FILE="
        "TOKEN_ENCRYPTION_KEY=$($Generated[1])"
        "PUBLIC_BASE_URL="
        "FRONTEND_URL=http://127.0.0.1:5000"
        "CORS_ORIGINS=http://127.0.0.1:5000,http://localhost:5000"
        "LOCAL_AUTH_BYPASS=true"
        "OPERATOR_PASSWORD_HASH=$OperatorHash"
        "OPENAI_API_KEY="
        "OPENAI_MODEL=gpt-4o-mini"
        "OPENAI_TRANSCRIPTION_MODEL=whisper-1"
        "FFMPEG_PATH=ffmpeg"
        "WORKER_POLL_SECONDS=5"
        "JOB_MAX_RETRIES=3"
        "JOB_LEASE_SECONDS=300"
        "JOB_VERIFY_SECONDS=30"
        "STALE_WORKER_SECONDS=120"
        "MAX_DASHBOARD_ITEMS=200"
        "HAI_CONNECTOR_ENABLED=false"
        "HAI_CONNECTOR_TOKEN=$($Generated[2])"
        "PORT=5000"
        "LOG_LEVEL=INFO"
    ) | Set-Content -LiteralPath $BackendEnv -Encoding utf8
    Write-Host "Created backend\.env with local secrets."
} else {
    Write-Host "Kept the existing backend\.env unchanged."
}

Write-Host "Installing and building the interface..."
Push-Location (Join-Path $Root "frontend")
try {
    if ($NpmCli) {
        & $NodeExecutable $NpmCli ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        & $NodeExecutable $NpmCli run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    } else {
        & npm.cmd ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    }
} finally { Pop-Location }

Write-Host "Creating/upgrading the database..."
Push-Location (Join-Path $Root "backend")
try {
    & $VenvPython -m flask --app app db upgrade
    $MigrationExit = $LASTEXITCODE
}
finally { Pop-Location }
if ($MigrationExit -ne 0) { throw "Database migration failed." }

Write-Host "Setup complete. Start StudioPilot with scripts\windows\start.ps1"
