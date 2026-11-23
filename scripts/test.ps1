$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = "$root\.deps;$root;$root\tests"
$env:PYTHONIOENCODING = "utf-8"
python -m unittest discover -s "$root\tests" -v
exit $LASTEXITCODE
