# Read-only progress monitor. Closing this window does not stop transport.
param([string]$Campaign='.local/cs137-1m',[switch]$Once)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if($Campaign -notmatch '^\.local/[A-Za-z0-9_/-]+$'){throw 'Invalid campaign path'}
$folder=[IO.Path]::GetFullPath((Join-Path $root $Campaign))
if(!$folder.StartsWith((Join-Path $root '.local')+[IO.Path]::DirectorySeparatorChar)){throw 'Campaign outside project'}
do {
  try {
    $p=Get-Content (Join-Path $folder 'progress.json') -Raw|ConvertFrom-Json
    $age=((Get-Date).ToUniversalTime()-[datetime]::Parse($p.heartbeat_utc).ToUniversalTime()).TotalSeconds
    if(!$Once){Clear-Host}
    Write-Host 'Cs137: Geant4 transport only; closing this monitor does not stop the job.'
    Write-Host (Get-Content (Join-Path $folder 'progress.txt') -Raw)
    Write-Host ('Heartbeat age: '+[math]::Round($age)+' seconds')
    if($age -gt 90 -and $p.status -eq 'running'){Write-Warning 'Stale heartbeat. Inspect the worker; do not assume it is still running.'}
    if(Test-Path (Join-Path $folder 'launcher-exit.json')){
      $e=Get-Content (Join-Path $folder 'launcher-exit.json') -Raw|ConvertFrom-Json
      Write-Host ('Most recent launcher exit: '+$e.exit_code+' at '+$e.finished_utc)
    }
  } catch {Write-Warning ('Progress not available yet: '+$_.Exception.Message)}
  if(!$Once){Start-Sleep -Seconds 5}
} while(!$Once)
