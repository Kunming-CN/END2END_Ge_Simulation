param([switch]$NoOpen)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $root
$page=Join-Path $root '.local/workspace/index.html'
function Assert-WorkspaceLocation {
  foreach($relative in @('.local','.local/workspace','.local/workspace/index.html')){
    $candidate=Join-Path $root $relative
    if(Test-Path -LiteralPath $candidate){
      if((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Linked workspace path refused'}
    }
  }
}
Assert-WorkspaceLocation
$exe=$null; $prefix=@()
if($env:SITE_PYTHON -and (Test-Path -LiteralPath $env:SITE_PYTHON -PathType Leaf)){$exe=$env:SITE_PYTHON}
if(!$exe){
  $python=Get-Command python.exe -ErrorAction SilentlyContinue
  if($python -and $python.CommandType -eq 'Application' -and $python.Source -notmatch 'WindowsApps'){$exe=$python.Source}
}
if(!$exe){
  $pv=Join-Path $env:ProgramFiles 'ParaView 6.1.1/bin/pvpython.exe'
  if(Test-Path -LiteralPath $pv){$exe=$pv;$prefix=@('--no-mpi','--disable-registry')}
}
if($exe){
  & $exe @prefix (Join-Path $PSScriptRoot 'build_local_dashboard.py')
  if($LASTEXITCODE -ne 0){throw 'Workspace indexing failed; existing evidence was preserved.'}
}elseif(!(Test-Path -LiteralPath $page)){
  throw 'An installed Python is needed to create this index. Run python tools/build_local_dashboard.py; no packages or simulations are installed by this launcher.'
}else{Write-Host 'Python unavailable; opening the previously generated local index.'}
Assert-WorkspaceLocation
if($NoOpen){Write-Output 'Workspace index ready; browser opening suppressed by -NoOpen.'}else{Start-Process -FilePath $page}
