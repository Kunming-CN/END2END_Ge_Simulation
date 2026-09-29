# Explicit metadata recovery entry. Never invokes runtime checks or simulations.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Name,[switch]$DryRun,[switch]$Json)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $PSScriptRoot 'native_recovery.ps1')
try{$result=Invoke-NativeRecovery $root ('.local/runs/'+$Name) -DryRun:$DryRun;$code=0}
catch{$result=[ordered]@{status='blocked';message=$_.Exception.Message;simulations_started=0;runtime_readiness_checked=$false};$code=2}
if($Json){$result|ConvertTo-Json -Depth 12}else{$result|Format-List;Write-Output 'Metadata only; no calculation, per-group resume or complete-waveform replay.'}
exit $code
