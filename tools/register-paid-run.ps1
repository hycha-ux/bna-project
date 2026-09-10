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
  [string]$LogFile = 'C:\Users\medib\teemo\out\paid-run.log',
  [switch]$NoStart
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $root 'tools\run-selfie-batches.ps1'
if (-not (Test-Path $runner)) { throw "runner not found: $runner" }

$args = "-ExecutionPolicy Bypass -File `"$runner`" -Treatments $Treatment -Count $Count " +
        "-Seed $Seed -Fix $Fix -CostCap $CostCap -LogFile `"$LogFile`""
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
