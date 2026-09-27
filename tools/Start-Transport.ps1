# Start or resume the prepared Geant4-only campaign in an independent process.
param([string]$Campaign='.local/cs137-1m',[switch]$Worker,[int]$MaxChunks=0,[string]$HandoffOwner='')
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')); Set-Location $root
if($Campaign -notmatch '^\.local/[A-Za-z0-9_/-]+$' -or $MaxChunks -lt 0 -or $HandoffOwner -notmatch '^[A-Za-z0-9_-]*$'){throw 'Invalid campaign arguments'}
$folder=[IO.Path]::GetFullPath((Join-Path $root $Campaign))
if(!$folder.StartsWith((Join-Path $root '.local')+[IO.Path]::DirectorySeparatorChar)){throw 'Campaign escapes project'}
if(!(Test-Path (Join-Path $folder 'config.json'))){throw 'Prepare and test this campaign first'}
if(!$Worker){
  $prior=Join-Path $folder 'launcher.json'
  if(Test-Path $prior){
    $old=Get-Content $prior -Raw|ConvertFrom-Json
    $p=Get-Process -Id $old.pid -ErrorAction SilentlyContinue
    if($p -and $p.StartTime.ToUniversalTime().ToString('o') -eq $old.process_start_utc){Write-Output "Existing independent worker PID $($p.Id)"; return}
  }
  $stamp=Get-Date -Format 'yyyyMMdd-HHmmssfff'
  $arguments='-NoProfile -ExecutionPolicy Bypass -File "'+$PSCommandPath+'" -Campaign "'+$Campaign+'" -Worker -MaxChunks '+$MaxChunks
  if($HandoffOwner){$arguments+=' -HandoffOwner "'+$HandoffOwner+'"'}
  $p=Start-Process -FilePath (Get-Command powershell.exe).Source -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $folder ($stamp+'.stdout.log')) -RedirectStandardError (Join-Path $folder ($stamp+'.stderr.log')) -PassThru
  $info=[ordered]@{pid=$p.Id;process_start_utc=$p.StartTime.ToUniversalTime().ToString('o');campaign=$Campaign;started_utc=(Get-Date).ToUniversalTime().ToString('o')}
  [IO.File]::WriteAllText($prior,($info|ConvertTo-Json))
  Write-Output ($info|ConvertTo-Json -Compress)
  Write-Output ('Progress: '+(Join-Path $folder 'progress.html'))
  return
}
$ErrorActionPreference='Continue'; $code=1
$env:OPENBLAS_NUM_THREADS='1'; $env:OMP_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'
try {
  $commandArgs=@('python','-u','-B','../tools/long_transport.py','run','--campaign',$Campaign)
  if($MaxChunks -gt 0){$commandArgs+=@('--max-chunks',[string]$MaxChunks)}
  & (Join-Path $root 'transport/Run.cmd') @commandArgs
  $code=$LASTEXITCODE
} catch {
  Write-Error $_; $code=1
} finally {
  $result=[ordered]@{pid=$PID;exit_code=$code;finished_utc=(Get-Date).ToUniversalTime().ToString('o')}
  [IO.File]::WriteAllText((Join-Path $folder 'launcher-exit.json'),($result|ConvertTo-Json))
  # Reconcile only the explicitly assigned private supervisor owner after exit.
  if($HandoffOwner){
    try {
      $statePath=Join-Path $root '.local/autonomy/state.json'
      $ownerPath=Join-Path $root '.local/autonomy/lock/owner.txt'
      $state=Get-Content $statePath -Raw|ConvertFrom-Json
      if($state.owner -eq $HandoffOwner -and (Get-Content $ownerPath -Raw).Trim() -eq $HandoffOwner){
        $progress=Get-Content (Join-Path $folder 'progress.json') -Raw|ConvertFrom-Json
        $state.status='ready';$state.owner=$null;$state.worker_sessions=@();$state.supervisor_pid=$null
        $state.current_step="Standalone transport exited: $($progress.status); $($progress.completed_decays)/$($progress.target_decays); exit=$code"
        $state.safe_next_step="Inspect $Campaign/progress.json, COMPLETE.json and DONE chunks. Reuse verified chunks; do not restart from zero. No automatic SSD/readout."
        $state.finished_utc=$result.finished_utc;$state.heartbeat_utc=$result.finished_utc
        $temporary=$statePath+'.worker-'+$PID
        [IO.File]::WriteAllText($temporary,($state|ConvertTo-Json -Depth 8))
        [IO.File]::Replace($temporary,$statePath,($statePath+'.before-worker-'+$PID))
        Remove-Item -LiteralPath $ownerPath
        Remove-Item -LiteralPath (Split-Path $ownerPath) -ErrorAction Stop
      }
    } catch {Write-Warning ('Private state reconciliation needs inspection: '+$_.Exception.Message)}
  }

}
exit $code
