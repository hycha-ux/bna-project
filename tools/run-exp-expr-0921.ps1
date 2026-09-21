# Expression-relax experiment, 2026-09-21 (Yeonseo confirmed via Buildy).
#   control    : nasolabial selfie x2, expression lock kept (default path)
#   experiment : nasolabial selfie x2, BNA_EXP_RELAX=expression (mouth state kept, key moves one step)
# Both arms: Before severity fixed to moderate and age fixed to 40s, so a 2-set run cannot land one arm
# on an old severity by chance (09-21 c8 lesson). Arms run one after the other, never together:
# the image quota is 8/min and two batches side by side would hit 429.
# Detached on purpose - a run started inside a Claude session dies with the session (09-09 lesson).
#
# Usage: powershell -ExecutionPolicy Bypass -File tools\run-exp-expr-0921.ps1 [-Dry]
# NOTE: ASCII only (PowerShell 5.1 reads .ps1 as CP949 here).
param([switch]$Dry)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot 'run-selfie-batches.ps1'
$log = 'C:\Users\medib\teemo\out\exp-expr-0921'
$common = @('-Treatments', 'nasolabial', '-Count', '2', '-Fix', 'age=40s', '-CostCap', '5')
$env:BNA_EXP_SEVERITY = 'moderate'

if ($Dry) {
  "dry: control    -> $runner $($common -join ' ') -LogFile $log-control.log  (BNA_EXP_RELAX unset, BNA_EXP_SEVERITY=moderate)"
  "dry: experiment -> $runner $($common -join ' ') -LogFile $log-relax.log    (BNA_EXP_RELAX=expression, BNA_EXP_SEVERITY=moderate)"
  exit 0
}

Remove-Item Env:BNA_EXP_RELAX -ErrorAction SilentlyContinue
& powershell -ExecutionPolicy Bypass -File $runner @common -LogFile "$log-control.log"
$env:BNA_EXP_RELAX = 'expression'
& powershell -ExecutionPolicy Bypass -File $runner @common -LogFile "$log-relax.log"
"done $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File -LiteralPath "$log-done.txt" -Encoding utf8
