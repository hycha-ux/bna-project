# Registers the generation-request poller as a scheduled task (every 1 minute, all day).
# ASCII only on purpose: Windows PowerShell 5.1 reads .ps1 as CP949 and mangles Korean.
# Run again after changing the schedule, then re-dump the XML:
#   powershell -NoProfile -File ops\register-genpoller-task.ps1
#   powershell -NoProfile -Command "Export-ScheduledTask -TaskName 'TeemoBnaGenPoller' | Set-Content ops\task-defs\TeemoBnaGenPoller.xml -Encoding UTF8"
$ErrorActionPreference = 'Stop'
$name = 'TeemoBnaGenPoller'
$node = 'C:\Program Files\nodejs\node.exe'
$root = 'C:\Users\medib\bna-project'

$action = New-ScheduledTaskAction -Execute $node -Argument "$root\ops\gen-poller.mjs" -WorkingDirectory $root
# Daily trigger + 1-minute repetition. Do NOT use `schtasks /sc minute /du` - that makes a
# one-off trigger that quietly stops after today (registration and NextRunTime look fine).
$trigger = New-ScheduledTaskTrigger -Daily -At 00:01
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At 00:01 `
  -RepetitionInterval (New-TimeSpan -Minutes 1) `
  -RepetitionDuration (New-TimeSpan -Hours 23 -Minutes 58)).Repetition
# Laptop: default DisallowStartIfOnBatteries would silently skip runs on battery power.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
  -Description 'B&A: pick up generation requests written by the cloud dashboard and run them on this PC' -Force | Out-Null
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State
(Get-ScheduledTask -TaskName $name).Triggers | ForEach-Object { $_.CimClass.CimClassName + ' rep=' + $_.Repetition.Interval }
