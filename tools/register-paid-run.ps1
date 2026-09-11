# Register a ONE-SHOT scheduled task for a paid batch run, then start it.
#
# Why a scheduled task: a run started inside a Claude session dies when that session ends
# (2026-09-09, 3 of 8 items done). The batch must outlive the session that ordered it.
#
# NOTE: ASCII only on purpose - Windows PowerShell 5.1 reads .ps1 as CP949 on this PC.
param(
  [string]$TaskName = 'TeemoBnaPaidRun',
  [string]$Treatment = 'nasolabial',
  [int]$Count = 8,
  [int]$Seed = 0,
  [string]$Fix = 'country=korea',
  [double]$CostCap = 10.0,
  [string]$Series = '',
  [string]$LogFile = 'C:\Users\medib\teemo\out\paid-run.log',
  [switch]$NoStart
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $root 'tools\run-selfie-batches.ps1'
if (-not (Test-Path $runner)) { throw "runner not found: $runner" }

# -Command, not -File. With -File every argument is handed over as a literal string, so
# "-Treatments nasolabial,filler_eyelid" arrived as ONE treatment named "nasolabial,filler_eyelid"
# and the run died on KeyError (2026-09-11). -Command parses the comma list into a real array.
$inner = "& '$runner' -Treatments $Treatment -Count $Count " +
         "-Seed $Seed -CostCap $CostCap -LogFile '$LogFile'"
# -Fix is appended only when it has a value. With an empty string the line used to read
# "-Fix  -CostCap 4", and PowerShell then bound "-CostCap" as the value of -Fix: the cost cap
# silently reverted to the 10.0 default. An axis you did not ask to fix must stay unfixed.
if ($Fix -ne '') { $inner += " -Fix $Fix" }
# Series stays quoted: the runner takes it as ONE [string] and passes it to --series as one
# argument. Unquoted, -Command parsed "immediate,1w,2w" into an array, PowerShell flattened it
# back to "immediate 1w 2w", and run_paid.py saw three arguments (2026-09-11).
if ($Series -ne '') { $inner += " -Series '$Series'" }
$args = "-ExecutionPolicy Bypass -Command `"$inner`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $args -WorkingDirectory $root
# One-shot far in the future; we start it by hand right away. The trigger only exists because
# a task needs one - the run happens via Start-ScheduledTask below.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddYears(1)
# This PC is a laptop: without these three the run is silently skipped on battery.
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
       -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $set -Force | Out-Null
Write-Host "registered: $TaskName"
if (-not $NoStart) {
  if (Test-Path $LogFile) { Remove-Item -LiteralPath $LogFile -Force }
  Start-ScheduledTask -TaskName $TaskName
  Write-Host "started. log: $LogFile"
}
