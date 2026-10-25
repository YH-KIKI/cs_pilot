$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.tools\python'
$env:UV_PYTHON_BIN_DIR = Join-Path $projectRoot '.tools\bin'
$env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'
$uvPath = Join-Path $projectRoot '.tools\uv.exe'
if (-not (Test-Path -LiteralPath $uvPath)) {
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uvCommand) { throw 'uv not found. See README for setup instructions.' }
    $uvPath = $uvCommand.Source
}
Push-Location $projectRoot
try {
    & $uvPath @args
    $uvExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $uvExit
