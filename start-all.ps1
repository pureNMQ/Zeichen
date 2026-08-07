[CmdletBinding()]
param(
    [int]$FrontendPort = 5173,
    [int]$ApiPort = 8001,
    [int]$McpPort = 8002,
    [int]$DockerTimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'

$repositoryRoot = $PSScriptRoot
$backendRoot = Join-Path $repositoryRoot 'backend'
$frontendRoot = Join-Path $repositoryRoot 'frontend'
$runtimeDirectory = Join-Path $repositoryRoot '.scratch'
# Keep the host-launched API and MCP on the PostgreSQL service started below.
# This environment value takes precedence over any development-only SQLite URL
# that may remain in backend/.env.
$databaseUrl = 'postgresql+psycopg://zeichen:zeichen@localhost:5432/zeichen'
New-Item -ItemType Directory -Force -Path $runtimeDirectory | Out-Null

function Test-ListeningPort {
    param([int]$Port)

    return $null -ne (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-ForListeningPort {
    param(
        [int]$Port,
        [string]$Name,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-ListeningPort -Port $Port) {
            return
        }
        Start-Sleep -Seconds 1
    }

    throw "$Name did not start listening on port $Port. Check .scratch logs."
}

function Start-ServiceProcess {
    param(
        [string]$Name,
        [int]$Port,
        [string]$Executable,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )

    if ($Port -gt 0 -and (Test-ListeningPort -Port $Port)) {
        Write-Host "$Name is already listening on port $Port."
        return
    }

    $stdoutLog = Join-Path $runtimeDirectory "$Name.stdout.log"
    $stderrLog = Join-Path $runtimeDirectory "$Name.stderr.log"
    Remove-Item -LiteralPath $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue
    Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog | Out-Null
    if ($Port -gt 0) {
        Wait-ForListeningPort -Port $Port -Name $Name
        Write-Host "$Name started on port $Port."
    }
    else {
        Write-Host "$Name started."
    }
}

function Wait-ForDocker {
    $deadline = (Get-Date).AddSeconds($DockerTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerReady) {
            return
        }
        Start-Sleep -Seconds 2
    }

    throw 'Docker Desktop did not become ready in time.'
}

function Test-DockerReady {
    $originalErrorActionPreference = $ErrorActionPreference
    try {
        # A stopped Docker daemon exits non-zero. Keep that probe from being
        # promoted to a terminating PowerShell error under this script's Stop mode.
        $ErrorActionPreference = 'Continue'
        & docker version --format '{{.Server.Version}}' *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $originalErrorActionPreference
    }
}

if (-not (Test-DockerReady)) {
    $dockerDesktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        throw 'Docker is unavailable. Start Docker Desktop, then run this script again.'
    }

    Write-Host 'Starting Docker Desktop...'
    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    Wait-ForDocker
}

Write-Host 'Starting PostgreSQL and Cognee...'
& docker compose up -d postgres cognee
if ($LASTEXITCODE -ne 0) {
    throw 'Could not start the Docker Compose services.'
}

$env:DATABASE_URL = $databaseUrl
Write-Host 'Using PostgreSQL database for migrations, API, and MCP.'

$python = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}

Write-Host 'Applying database migrations...'
Push-Location $backendRoot
try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw 'Database migration failed.'
    }
}
finally {
    Pop-Location
}

Start-ServiceProcess -Name 'api' -Port $ApiPort -Executable $python -Arguments @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$ApiPort") -WorkingDirectory $backendRoot
Start-ServiceProcess -Name 'mcp' -Port $McpPort -Executable $python -Arguments @('-m', 'uvicorn', 'app.mcp_server.main:app', '--host', '127.0.0.1', '--port', "$McpPort") -WorkingDirectory $backendRoot
# Cognee improve can exceed an MCP request timeout. Keep it in a durable worker
# process; the MCP tool only submits/polls jobs.
Start-ServiceProcess -Name 'memory-improve-worker' -Port 0 -Executable $python -Arguments @('-m', 'app.workers.memory_improve') -WorkingDirectory $backendRoot
Start-ServiceProcess -Name 'frontend' -Port $FrontendPort -Executable 'npm.cmd' -Arguments @('run', 'dev', '--', '--host', '127.0.0.1', '--port', "$FrontendPort") -WorkingDirectory $frontendRoot

Write-Host ''
Write-Host "Frontend: http://localhost:$FrontendPort"
Write-Host "API:      http://localhost:$ApiPort/api/health"
Write-Host "MCP:      http://localhost:$McpPort/mcp"
Write-Host "Logs:     $runtimeDirectory"
