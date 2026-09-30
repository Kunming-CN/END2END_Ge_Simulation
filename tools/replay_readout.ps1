[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Name,
  [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_-]{1,80}$')][string]$ReplayName,
  [ValidateSet('AK02','SAP22','both')][string]$Detector='both',
  [string]$ElectronicsProfile='', [switch]$DryRun, [switch]$Json,
  [switch]$CheckpointGroups,[switch]$Resume,[ValidateRange(1,400)][int]$StopAfterGroups)
$ErrorActionPreference='Stop'
if(($Resume -or $PSBoundParameters.ContainsKey('StopAfterGroups')) -and !$CheckpointGroups){throw 'Resume/StopAfterGroups require -CheckpointGroups'}
if($Resume -and $PSBoundParameters.ContainsKey('ElectronicsProfile')){throw 'No ElectronicsProfile override on checkpoint resume'}
if($PSBoundParameters.ContainsKey('ElectronicsProfile') -and !$ElectronicsProfile){throw 'ElectronicsProfile must not be empty'}
$exe=$null;$prefix=@()
if($env:SITE_PYTHON){
  if(!(Test-Path -LiteralPath $env:SITE_PYTHON -PathType Leaf)){throw 'SITE_PYTHON is not an existing interpreter'}
  $exe=$env:SITE_PYTHON
}else{
  $python=Get-Command python.exe -ErrorAction SilentlyContinue
  if($python -and $python.CommandType -eq 'Application' -and $python.Source -notmatch 'WindowsApps'){$exe=$python.Source}
  if(!$exe){$pv=Join-Path $env:ProgramFiles 'ParaView 6.1.1/bin/pvpython.exe';if(Test-Path -LiteralPath $pv -PathType Leaf){$exe=$pv}}
}
if(!$exe){throw 'Existing Python 3.10+ required; nothing installed'}
if([IO.Path]::GetFileName($exe) -ieq 'pvpython.exe'){$prefix=@('--no-mpi','--disable-registry')}
$arguments=@('-B',(Join-Path $PSScriptRoot 'replay_readout.py'),'--name',$Name,'--replay-name',$ReplayName,'--detector',$Detector)
if($ElectronicsProfile){$arguments+=@('--electronics-profile',$ElectronicsProfile)}
if($DryRun){$arguments+='--dry-run'}
if($Json){$arguments+='--json'}
if($CheckpointGroups){$arguments+='--checkpoint-groups'}
if($Resume){$arguments+='--resume'}
if($PSBoundParameters.ContainsKey('StopAfterGroups')){$arguments+=@('--stop-after-groups',$StopAfterGroups)}
& $exe @prefix @arguments
exit $LASTEXITCODE
