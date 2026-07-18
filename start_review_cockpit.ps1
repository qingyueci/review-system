$ErrorActionPreference = "Stop"

$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcherLog = Join-Path $rootDir "review-cockpit-launcher.log"
$siteUrl = "https://fupan-cockpit.junxicai1.chatgpt.site"
$statusUrl = "http://127.0.0.1:8765/api/status"
$expectedServiceVersion = "1.3.0"

function Write-LauncherLog {
    param([string]$Message)
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $launcherLog -Value $line -Encoding UTF8
}

function Find-BackendDirectory {
    $directory = Get-ChildItem -LiteralPath $rootDir -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "run_cockpit.py") } |
        Select-Object -First 1

    if (-not $directory) {
        throw "Cannot find the local review service directory."
    }
    return $directory.FullName
}

function Read-ServiceToken {
    param([string]$TokenPath)
    if (-not (Test-Path -LiteralPath $TokenPath)) {
        return ""
    }
    return (Get-Content -LiteralPath $TokenPath -Raw -Encoding UTF8).Trim()
}

function Get-ReviewServiceInfo {
    param([string]$Token)
    if ([string]::IsNullOrWhiteSpace($Token)) {
        return $null
    }

    try {
        return Invoke-RestMethod `
            -Uri $statusUrl `
            -Headers @{ "X-Review-Token" = $Token } `
            -TimeoutSec 2
    }
    catch {
        return $null
    }
}

function Test-ReviewService {
    param([string]$Token)
    $response = Get-ReviewServiceInfo -Token $Token
    return (
        $null -ne $response -and
        $response.ok -eq $true -and
        $response.service_version -eq $expectedServiceVersion
    )
}

function Stop-OutdatedReviewService {
    param([string]$Token)
    $response = Get-ReviewServiceInfo -Token $Token
    if ($null -eq $response -or $response.ok -ne $true) {
        return
    }
    if ($response.service_version -eq $expectedServiceVersion) {
        return
    }

    $processIds = Get-NetTCPConnection `
        -LocalAddress "127.0.0.1" `
        -LocalPort 8765 `
        -State Listen `
        -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $processIds) {
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Write-LauncherLog ("Outdated local service stopped. PID={0}." -f $processId)
    }
    Start-Sleep -Milliseconds 500
}

try {
    Write-LauncherLog "Startup requested."
    $backendDir = Find-BackendDirectory
    $pythonPath = Join-Path $backendDir ".venv\Scripts\python.exe"
    $requirementsPath = Join-Path $backendDir "requirements.txt"
    $tokenPath = Join-Path $backendDir "data\service_token.txt"

    if (-not (Test-Path -LiteralPath $pythonPath)) {
        Write-Host "[Review Cockpit] Preparing the local environment..."
        & py -m venv (Join-Path $backendDir ".venv")
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create the local Python environment."
        }
    }

    & $pythonPath -c "import fastapi, uvicorn" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[Review Cockpit] Installing missing local components..."
        & $pythonPath -m pip install --timeout 30 -r $requirementsPath
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install the local components."
        }
    }

    $token = Read-ServiceToken -TokenPath $tokenPath
    $serviceReady = Test-ReviewService -Token $token

    if (-not $serviceReady) {
        Stop-OutdatedReviewService -Token $token
        $serviceOutputLog = Join-Path $backendDir "data\service-output.log"
        $serviceErrorLog = Join-Path $backendDir "data\service-error.log"
        $arguments = @(
            "-m", "uvicorn",
            "review_app.api:app",
            "--host", "127.0.0.1",
            "--port", "8765",
            "--log-level", "warning",
            "--no-access-log"
        )

        $process = Start-Process `
            -FilePath $pythonPath `
            -ArgumentList $arguments `
            -WorkingDirectory $backendDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $serviceOutputLog `
            -RedirectStandardError $serviceErrorLog `
            -PassThru
        Write-LauncherLog ("Local service process started. PID={0}." -f $process.Id)

        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            Start-Sleep -Milliseconds 500
            $token = Read-ServiceToken -TokenPath $tokenPath
            if (Test-ReviewService -Token $token) {
                $serviceReady = $true
                break
            }
            if ($process.HasExited) {
                break
            }
        }
    }
    else {
        Write-LauncherLog "Reusing the running local service."
    }

    if (-not $serviceReady) {
        throw "The local service did not become ready within 20 seconds."
    }

    $escapedToken = [Uri]::EscapeDataString($token)
    $openUrl = "{0}/#token={1}" -f $siteUrl, $escapedToken
    Start-Process -FilePath $openUrl
    Write-LauncherLog "Local service ready. Browser open requested."
    exit 0
}
catch {
    $message = $_.Exception.Message
    Write-LauncherLog ("Startup failed: {0}" -f $message)
    Write-Host ("[Review Cockpit] {0}" -f $message) -ForegroundColor Red
    exit 1
}
