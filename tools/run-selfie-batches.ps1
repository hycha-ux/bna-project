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

# From here on, do NOT let a stderr line abort the run.
# 2026-09-09: with ErrorActionPreference='Stop', `& python ... 2>&1 | Out-File` turns the FIRST
# stderr line into a terminating error. mediapipe/insightface print warnings to stderr on import,
# so the task died ~2s in (LastTaskResult=1) while the batch it had already spawned kept a
# half-written progress.json. Start-Process with file redirection keeps the streams as plain text.
$ErrorActionPreference = 'Continue'

foreach ($t in $Treatments) {
  "===== $t $(Get-Date -Format 'HH:mm:ss') =====" | Out-File -LiteralPath $LogFile -Append -Encoding utf8
  $so = "$LogFile.$t.out"
  $se = "$LogFile.$t.err"
  $p = Start-Process -FilePath $py -WorkingDirectory $root -NoNewWindow -Wait -PassThru `
    -ArgumentList @('-m', 'bna.cli', '--treatment', $t, '--mode', 'selfie',
                    '--count', "$Count", '--seed', "$Seed", '--run') `
    -RedirectStandardOutput $so -RedirectStandardError $se
  foreach ($f in @($so, $se)) {
    if (Test-Path $f) { Get-Content -LiteralPath $f | Out-File -LiteralPath $LogFile -Append -Encoding utf8
                        Remove-Item -LiteralPath $f -Force }
  }
  "----- $t done exit=$($p.ExitCode) $(Get-Date -Format 'HH:mm:ss') -----" |
    Out-File -LiteralPath $LogFile -Append -Encoding utf8
}
"=== run finished $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" |
  Out-File -LiteralPath $LogFile -Append -Encoding utf8
