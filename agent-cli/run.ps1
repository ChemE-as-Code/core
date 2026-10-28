# Windows counterpart of run.sh: runs agent.py with ANTHROPIC_API_KEY from the environment
# (set it once as a user variable: [Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', '...', 'User')).
#   .\run.ps1 --task-file tasks\x.md --cwd .. --budget 5
#   .\run.ps1 -Jobs jobs\night.json --total 150      # the supervisor (jobs.py) instead
# (no param() block: every argument is passed through unchanged, so --help etc. reach the Python script)
$ErrorActionPreference = 'Stop'
if (-not $env:ANTHROPIC_API_KEY) {
    $env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY', 'User')
}
if (-not $env:ANTHROPIC_API_KEY) { Write-Error 'ANTHROPIC_API_KEY is not set (user environment variable).' }
Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue  # another project's venv must not shadow ours
$env:PYTHONIOENCODING = 'utf-8'
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force logs | Out-Null
if ($args.Count -ge 2 -and $args[0] -eq '-Jobs') {
    $rest = if ($args.Count -gt 2) { $args[2..($args.Count - 1)] } else { @() }
    uv run jobs.py $args[1] @rest
} else {
    uv run agent.py @args
}
exit $LASTEXITCODE
