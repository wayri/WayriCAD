[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$AppArgs)
$ErrorActionPreference = 'Stop'
$entry = Join-Path $PSScriptRoot 'entrypoint.py'
$candidates = @()
$py = Get-Command py.exe -ErrorAction SilentlyContinue
if ($py) { $candidates += ,@($py.Source, '-3') }
$python = Get-Command python.exe -ErrorAction SilentlyContinue
if ($python -and $python.Source -notlike '*\WindowsApps\*') { $candidates += ,@($python.Source) }
$base = Join-Path $env:ProgramFiles 'KiCad'
if (Test-Path $base) {
    $found = Get-ChildItem -LiteralPath $base -Directory | Sort-Object Name -Descending
    foreach ($dir in $found) {
        foreach ($name in @('python.exe','python3.exe')) {
            $file = Join-Path $dir.FullName ('bin\'+$name)
            if (Test-Path $file) { $candidates += ,@($file) }
        }
    }
}
foreach ($candidate in $candidates) {
    $exe = $candidate[0]
    $prefix = @()
    if ($candidate.Count -gt 1) { $prefix = @($candidate[1..($candidate.Count-1)]) }
    try {
        & $exe @prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & $exe @prefix $entry @AppArgs
            exit $LASTEXITCODE
        }
    } catch { }
}
Write-Host 'Python 3.10+ could not be found. Install Python for Windows or configure KiCad''s external Python interpreter.' -ForegroundColor Yellow
Write-Host 'Then rerun this launcher. Core BOM use has no extra packages; advanced 3D previews have optional requirements-preview.txt.'
exit 1
