param([switch]$NoBrowser, [ValidateRange(0,65535)][int]$Port=0)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$python = $env:SITE_PYTHON
if (-not $python) {
    $pv = Join-Path $env:ProgramFiles 'ParaView 6.1.1\bin\pvpython.exe'
    if (Test-Path -LiteralPath $pv -PathType Leaf) { $python = $pv }
    else {
        $found = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($found) { $python = $found.Source }
    }
}
if (-not $python -or -not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'An existing Python 3.10+ is required. Set SITE_PYTHON for this launch; nothing is installed automatically. See tools/site_guide.html.'
}
$argv = @()
if ((Split-Path -Leaf $python) -eq 'pvpython.exe') { $argv += @('--no-mpi','--disable-registry') }
$argv += @('-B', (Join-Path $PSScriptRoot 'local_ui.py'), '--port', "$Port")
if ($NoBrowser) { $argv += '--no-browser' }
$env:SITE_PYTHON = $python # This launcher process and its children only.
& $python @argv
exit $LASTEXITCODE
