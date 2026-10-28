$ErrorActionPreference = 'Stop'
$d01ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $d01ProjectRoot
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'uv is required. See https://docs.astral.sh/uv/getting-started/installation/'
    }
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        uv venv --python 3.11 --no-project .venv
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create the project environment.' }
    }
    & '.venv/Scripts/python.exe' -c "import sys; assert sys.version_info[:2] == (3,11); assert sys.prefix != sys.base_prefix"
    if ($LASTEXITCODE -ne 0) { throw 'G0 requires an isolated Python 3.11 environment.' }
    uv pip sync --python .venv/Scripts/python.exe requirements/g0-windows-py311.lock.txt --torch-backend cu128 --require-hashes --link-mode=copy
    if ($LASTEXITCODE -ne 0) { throw 'Dependency sync failed.' }
    uv pip check --python .venv/Scripts/python.exe
    if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency check failed.' }
} finally {
    Pop-Location
}
