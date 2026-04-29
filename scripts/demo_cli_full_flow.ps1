param(
    [switch]$ResetDb,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$ArgsList = @("scripts\demo_cli_full_flow.py", "--port", "$Port")
if ($ResetDb) {
    $ArgsList += "--reset-db"
}

python @ArgsList
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
