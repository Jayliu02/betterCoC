$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = "$root\.deps;$root"
& python -m bettercoc @args
exit $LASTEXITCODE
