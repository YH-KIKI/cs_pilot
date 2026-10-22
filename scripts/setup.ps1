# Run: powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22.12 or newer.' }
    $nodeVersion = [version]((& node -p 'process.versions.node').Trim())
    if ($nodeVersion -lt [version]'22.12.0') { throw 'Node.js 22.12 or newer is required.' }
    $uvPath = Join-Path $projectRoot '.tools\uv.exe'
    if (-not (Test-Path -LiteralPath $uvPath)) {
        New-Item -ItemType Directory -Path .tools -Force | Out-Null
        $release = Invoke-RestMethod 'https://api.github.com/repos/astral-sh/uv/releases/latest'
        $asset = $release.assets | Where-Object name -eq 'uv-x86_64-pc-windows-msvc.zip'
        if (-not $asset) { throw 'Official uv Windows x64 release not found.' }
        $archive = Join-Path $projectRoot '.tools\uv-windows.zip'
        Invoke-WebRequest $asset.browser_download_url -OutFile $archive -UseBasicParsing
        if (-not $asset.digest -or -not $asset.digest.StartsWith('sha256:')) {
            throw 'Download checksum is missing.'
        }
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $asset.digest.Substring(7)) {
            throw 'uv download checksum mismatch.'
        }
        Expand-Archive -LiteralPath $archive -DestinationPath .tools -Force
    }
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.tools\python'
    $env:UV_PYTHON_BIN_DIR = Join-Path $projectRoot '.tools\bin'
    $env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'
    & $uvPath python install 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
    & $uvPath sync --locked
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    & $uvPath run python -m scripts.init_orders_db
    if ($LASTEXITCODE -ne 0) { throw 'SQLite initialization failed.' }
    Push-Location frontend
    try {
        & npm.cmd ci --cache ..\.cache\npm
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        & npm.cmd run typecheck
        if ($LASTEXITCODE -ne 0) { throw 'Type check failed.' }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
    if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
    Write-Output 'Setup complete. See README for start commands.'
} finally { Pop-Location }
