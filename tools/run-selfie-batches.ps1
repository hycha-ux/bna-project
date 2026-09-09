# Selfie batch runner for scheduled (session-independent) execution.
#
# Why a scheduled task and not a background shell:
#   2026-09-09 - a background run started inside a Claude session was killed when the
#   session ended (3 of 8 items done, the other two treatments never started).
#   Same rule as the daemon: anything started inside a session dies with it.
#
# Usage (from an ordinary PowerShell, no elevation needed):
#   powershell -ExecutionPolicy Bypass -File tools\run-selfie-batches.ps1 -Treatments nasolabial,filler_nose,filler_neck -Count 8 -Seed 5
#
# NOTE: ASCII only on purpose. Windows PowerShell 5.1 reads .ps1 as CP949 on this PC,
#       so Korean literals here would be silently mangled.

param(
  [string[]]$Treatments = @('nasolabial', 'filler_nose', 'filler_neck'),
  [int]$Count = 8,
  [int]$Seed = 5,
  [string]$KeysFile = 'C:\Users\medib\teemo\keys.env',
  [string]$LogFile = 'C:\Users\medib\teemo\out\run-selfie-batches.log'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'

# Keys never touch the log or the command line - they go straight into this process env.
if (-not (Test-Path $KeysFile)) { throw "keys file not found: $KeysFile" }
foreach ($line in Get-Content -LiteralPath $KeysFile -Encoding UTF8) {
  $t = $line.Trim()
  if ($t -eq '' -or $t.StartsWith('#')) { continue }
  $i = $t.IndexOf('=')
  if ($i -lt 1) { continue }
  $name = $t.Substring(0, $i).Trim()
  if ($name -notmatch '^(OPENAI_API_KEY|GEMINI_API_KEY|HIGGSFIELD_API_KEY|HIGGSFIELD_SECRET)$') { continue }
  [Environment]::SetEnvironmentVariable($name, $t.Substring($i + 1).Trim(), 'Process')
}
if (-not $env:OPENAI_API_KEY) { throw 'OPENAI_API_KEY missing - run: node C:\Users\medib\teemo\tools\verify-keys.mjs' }

$env:PYTHONPATH = Join-Path $root 'src'
$env:PYTHONIOENCODING = 'utf-8'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogFile) | Out-Null
"=== run start $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') seed=$Seed count=$Count ===" |
  Out-File -LiteralPath $LogFile -Encoding utf8

foreach ($t in $Treatments) {
  "===== $t $(Get-Date -Format 'HH:mm:ss') =====" | Out-File -LiteralPath $LogFile -Append -Encoding utf8
  & $py -m bna.cli --treatment $t --mode selfie --count $Count --seed $Seed --run 2>&1 |
    Out-File -LiteralPath $LogFile -Append -Encoding utf8
  "----- $t done exit=$LASTEXITCODE $(Get-Date -Format 'HH:mm:ss') -----" |
    Out-File -LiteralPath $LogFile -Append -Encoding utf8
}
"=== run finished $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" |
  Out-File -LiteralPath $LogFile -Append -Encoding utf8
