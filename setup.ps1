param(
    [switch]$NoStartup,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$main = Join-Path $project "main.py"
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $pythonCommand) {
    throw "Python 3.10 or newer was not found on PATH."
}

$python = $pythonCommand.Source
& $python --version
if ($LASTEXITCODE -ne 0) {
    throw "Python could not be started."
}
& $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.10 or newer is required."
}
& $python $main --once | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Codex usage validation failed. Run 'codex.cmd login' and try again."
}

if (-not $NoStartup) {
    & $python $main --install-startup
    if ($LASTEXITCODE -ne 0) {
        throw "The Windows startup entry could not be installed."
    }
}

if (-not $NoLaunch) {
    $pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
    if (Test-Path -LiteralPath $pythonw) {
        Start-Process -FilePath $pythonw -ArgumentList ('"' + $main + '"') -WorkingDirectory $project -WindowStyle Hidden
    } else {
        Start-Process -FilePath $python -ArgumentList ('"' + $main + '"') -WorkingDirectory $project -WindowStyle Hidden
    }
}

Write-Host "Codex Usage Overlay setup completed."
