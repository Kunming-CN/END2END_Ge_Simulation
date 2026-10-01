[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_-]{1,24}$')][string]$Name,
  [switch]$Resume,[switch]$DryRun,[switch]$Json,[ValidateRange(1,2)][int]$StopAfterGroups,[AllowEmptyString()][string]$PrimaryIds)
$ErrorActionPreference='Stop'
if($Resume -and $PSBoundParameters.ContainsKey('PrimaryIds')){throw 'PrimaryIds override is forbidden on Resume'}
$exe=$env:SITE_PYTHON
if(!$exe){$exe=Join-Path $env:ProgramFiles 'ParaView 6.1.1/bin/pvpython.exe'}
if(!(Test-Path -LiteralPath $exe -PathType Leaf)){throw 'Existing Python required; nothing installed'}
$prefix=@();if([IO.Path]::GetFileName($exe) -ieq 'pvpython.exe'){$prefix=@('--no-mpi','--disable-registry')}
$arguments=@('-B',(Join-Path $PSScriptRoot 'native_readout_integration.py'),'--name',$Name)
if($Resume){$arguments+='--resume'}
if($DryRun){$arguments+='--dry-run'}
if($PSBoundParameters.ContainsKey('StopAfterGroups')){$arguments+=@('--stop-after-groups',$StopAfterGroups)}
if($PSBoundParameters.ContainsKey('PrimaryIds')){$arguments+=('--primary-ids='+$PrimaryIds)}
& $exe @prefix @arguments
exit $LASTEXITCODE
