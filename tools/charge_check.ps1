# Interpreter selection only: no readiness probes, installs or run reservation.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Name,
  [ValidateSet('AK02','SAP22','both')][string]$Detector='both',[switch]$Json)
$ErrorActionPreference='Stop'
$exe=$null; $prefix=@()
if($env:SITE_PYTHON){
  if(!(Test-Path -LiteralPath $env:SITE_PYTHON -PathType Leaf)){throw 'SITE_PYTHON is not an existing interpreter; no fallback attempted'}
  $exe=$env:SITE_PYTHON
}else{
  $python=Get-Command python.exe -ErrorAction SilentlyContinue
  if($python -and $python.CommandType -eq 'Application' -and $python.Source -notmatch 'WindowsApps'){$exe=$python.Source}
  if(!$exe){
    $pv=Join-Path $env:ProgramFiles 'ParaView 6.1.1/bin/pvpython.exe'
    if(Test-Path -LiteralPath $pv -PathType Leaf){$exe=$pv}
  }
}
if(!$exe){throw 'Use an existing Python 3.10+ via SITE_PYTHON or PATH; see tools/CHARGE_REUSE.md. Nothing installed.'}
if([IO.Path]::GetFileName($exe) -ieq 'pvpython.exe'){$prefix=@('--no-mpi','--disable-registry')}
$arguments=@('-B',(Join-Path $PSScriptRoot 'charge_check.py'),'--name',$Name,'--detector',$Detector)
if($Json){$arguments+='--json'}
& $exe @prefix @arguments
exit $LASTEXITCODE
