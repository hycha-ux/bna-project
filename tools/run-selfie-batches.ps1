# Selfie batch runner for scheduled (session-independent) execution.
#
# Why a scheduled task and not a background shell:
#   2026-09-09 - a background run started inside a Claude session was killed when the
#   session ended (3 of 8 items done, the other two treatments never started).
#   Same rule as the daemon: anything started inside a session dies with it.
#
# Usage (from an ordinary PowerShell, no elevation needed):
#   powershell -ExecutionPolicy Bypass -File tools\run-selfie-batches.ps1 -Treatments nasolabial,filler_nose,filler_neck -Count 8
#
# Seed: 0 (the default) means "pick a fresh one each run" and the chosen value is logged.
#   2026-09-09 - the default used to be a hard-coded 5. plan_batch is deterministic in the seed,
#   so running the same treatment twice produced the SAME roster of people: the two nasolabial
#   batches of 09-09 had items 0000/0002 identical across all 11 person axes, and their faces
#   scored 0.421 / 0.392 ArcFace against each other vs 0.099 for the average pair.
#   Pass -Seed <n> explicitly only when you are trying to reproduce a past run.
#
# NOTE: ASCII only on purpose. Windows PowerShell 5.1 reads .ps1 as CP949 on this PC,
#       so Korean literals here would be silently mangled.

param(
  [string[]]$Treatments = @('nasolabial', 'filler_nose', 'filler_neck'),
  [int]$Count = 8,
  [int]$Seed = 0,
  # Fix variation axes, e.g. -Fix country=korea (repeatable: -Fix country=korea,gender=female)
  [string[]]$Fix = @(),
  # Stop a batch once it has burned this much (USD). 2026-09-10: bna.cli has no cap, so a run
  # that went wrong could only be stopped by hand. tools/run_paid.py takes the cap.
  [double]$CostCap = 10.0,
  # Timeline series, comma separated (e.g. -Series immediate,2w). Empty = single After cut.
  # 2026-09-11: first series run. run_paid.py gained --series the same day; without it there was
  # no way to launch a series batch from a task at all.
  [string]$Series = '',
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
# 0 = no seed was given -> draw one now, and write it to the log so a run can still be reproduced.
if ($Seed -eq 0) { $Seed = Get-Random -Minimum 1 -Maximum 2147483647 }
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
  $argv = @('tools\run_paid.py', '--treatment', $t, '--mode', 'selfie',
            '--count', "$Count", '--seed', "$Seed", '--cost-cap', "$CostCap")
  if ($Series -ne '') { $argv += @('--series', $Series) }
  foreach ($f in $Fix) { $argv += @('--fix', $f) }
  $p = Start-Process -FilePath $py -WorkingDirectory $root -NoNewWindow -Wait -PassThru `
    -ArgumentList $argv `
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
