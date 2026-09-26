# Serial nominal Cs137 -> native SSD -> synthetic readout campaign. No installs.
param(
  [Parameter(Mandatory=$true)][ValidatePattern('^\.local/[A-Za-z0-9_/-]+$')][string]$Output,
  [ValidateSet(20,500,10000)][int]$Events=500,
  [ValidateRange(1,2147483647)][int]$Seed=26092631,
  [string]$Pilot='',
  [ValidatePattern('^\.local/[A-Za-z0-9_/-]+$')][string]$Exporter='.local/m2a/cs137-build-v1/cryostat_export'
)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')); Set-Location $root
$localRoot=Join-Path $root '.local'
function Assert-Local([string]$Path) {
  $full=[IO.Path]::GetFullPath((Join-Path $root $Path))
  if(!$full.StartsWith($localRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Path must be below project .local'}
  $p=$full
  while($p -and $p.Length -ge $localRoot.Length){
    if((Test-Path -LiteralPath $p) -and ((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Linked campaign path refused'}
    $p=[IO.Path]::GetDirectoryName($p)
  }
  return $full
}
$out=Assert-Local $Output
if(Test-Path -LiteralPath $out){throw 'Output exists; preserve it and choose a new name'}
$j=(Get-Command julia -ErrorAction Stop).Source
$wrapper=Join-Path $root 'transport/Run.cmd'
$sourceFiles=@('tools/run_native_campaign.ps1','transport/cs137.py','transport/cryostat_export.cc','transport/cryostat_nominal.json','transport/handoff.py','transport/pixi.lock','simulation/native_response.jl','simulation/native_stream.jl','simulation/readout_profiles.jl','simulation/native_readout_profile.json','simulation/native_li_example.jl','simulation/readout.jl','simulation/replay.jl','simulation/run.jl','simulation/Manifest.toml')
$exporterFile=Assert-Local $Exporter
if(!(Test-Path -LiteralPath $exporterFile -PathType Leaf)){throw 'Build cryostat_export and supply its project-relative path with -Exporter'}
$sourceFiles+=@($Exporter,'tools/verify_native_pilot.ps1')
$hashes=[ordered]@{}; foreach($f in $sourceFiles){$hashes[$f]=(Get-FileHash -Algorithm SHA256 (Join-Path $root $f)).Hash.ToLowerInvariant()}
$pilotValidation=$null
if($Events -eq 10000){
  if(!$Pilot){throw '10000 requires a completed 500-decay pilot directory'}
  $pilotDir=Assert-Local $Pilot; $p=Get-Content (Join-Path $pilotDir 'run.json') -Raw|ConvertFrom-Json
  if($p.status -ne 'completed_provisional_native_campaign' -or $p.events_per_model -ne 500){throw 'Pilot is not a completed 500/model campaign'}
  $pilotValidation=& (Join-Path $PSScriptRoot 'verify_native_pilot.ps1') -Pilot $Pilot -Exporter $Exporter | ConvertFrom-Json
  if($pilotValidation.status -ne 'passed'){throw 'Full pilot verification failed'}
  # Launcher/verifier revisions are recorded separately, never rebased into old receipts.
  # The verifier compares every recorded compute dependency and every pilot artifact.
  foreach($f in $sourceFiles){
    if($f -in @('tools/run_native_campaign.ps1','tools/verify_native_pilot.ps1')){continue}
    if($p.source_sha256.PSObject.Properties[$f].Value -ne $hashes[$f]){throw "Pilot source differs: $f"}
  }
  foreach($m in @('AK02','SAP22')){
    $pr=Get-Content (Join-Path $pilotDir ($m+'/response/run.json')) -Raw|ConvertFrom-Json
    if($pr.status -ne 'completed_provisional_native_response' -or $pr.counts.initial_decays -ne 500 -or $pr.counts.groups -lt 1){throw "Pilot has no complete positive native integration: $m"}
    $h=(Get-FileHash -Algorithm SHA256 (Join-Path $pilotDir ($m+'/response/run.json'))).Hash.ToLowerInvariant()
    if($p.models.PSObject.Properties[$m].Value.response_report_sha256 -ne $h){throw 'Pilot report hash mismatch'}
  }
  $estimatedBytes=20*1.5*(Get-ChildItem $pilotDir -Recurse -File|Measure-Object Length -Sum).Sum
  $drive=Get-PSDrive -Name ([IO.Path]::GetPathRoot($out).TrimEnd('\').TrimEnd(':'))
  if($estimatedBytes -gt 0.7*$drive.Free){throw 'Pilot-scaled storage estimate lacks free-space headroom'}
}
New-Item -ItemType Directory -Path $out | Out-Null
$env:OPENBLAS_NUM_THREADS='1'; $env:OMP_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'
$report=[ordered]@{kind='native_campaign_v1';status='running';events_per_model=$Events;seed=$Seed;source_sha256=$hashes;models=[ordered]@{};stages=@();pilot=$Pilot;pilot_verification=$pilotValidation;assumption='Explicit nominal LBNL assembly and isolated reset readout; not as-built, calibrated spectra or continuous acquisition';started_utc=(Get-Date).ToUniversalTime().ToString('o')}
function Save-Report {
  [IO.File]::WriteAllText((Join-Path $out 'run.json'),($report|ConvertTo-Json -Depth 14))
}
function Invoke-Recorded([string]$Label,[string]$Kind,[string[]]$CommandArgs){
  foreach($arg in $CommandArgs){if($arg -match '["&|<>%`\r\n]'){throw 'Unsafe command argument'}}
  $quoted=($CommandArgs|ForEach-Object{'"'+$_+'"'}) -join ' '
  $rec=[ordered]@{stage=$Label;kind=$Kind;arguments=$CommandArgs;status='failed';exit_code=$null}; $timer=[Diagnostics.Stopwatch]::StartNew()
  Write-Output "START $Label"
  try {
    $stdout=Join-Path $out ($Label+'.stdout.log'); $stderr=Join-Path $out ($Label+'.stderr.log')
    if($Kind -eq 'transport'){
      $args='/d /s /c ""'+$wrapper+'" '+$quoted+'"'
      $proc=Start-Process -FilePath (Get-Command cmd.exe -ErrorAction Stop).Source -ArgumentList $args -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -Wait
    }else{
      $proc=Start-Process -FilePath $j -ArgumentList $quoted -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -Wait
    }
    $rec.exit_code=$proc.ExitCode
    if($proc.ExitCode -ne 0){throw "$Label failed with exit $($proc.ExitCode); preserved stdout/stderr in campaign root"}
    $rec.status='complete'
  }finally{
    $timer.Stop(); $rec.wall_seconds=$timer.Elapsed.TotalSeconds; $report.stages+=,$rec; Save-Report
    Write-Output "END $Label exit=$($rec.exit_code) seconds=$($rec.wall_seconds)"
  }
}
Save-Report
try {
  foreach($model in @('AK02','SAP22')){
    New-Item -ItemType Directory -Path (Join-Path $out $model)|Out-Null
    $transport='../'+$Output+'/'+$model+'/transport'; $response=$Output+'/'+$model+'/response'
    Invoke-Recorded ($model+'-prepare') 'transport' @('python','-B','cs137.py','prepare','--model',$model,'--output',$transport,'--exporter',('../'+$Exporter),'--events',[string]$Events,'--seed',[string]$Seed)
    Invoke-Recorded ($model+'-transport') 'transport' @('python','-B','cs137.py','run','--directory',$transport)
    Invoke-Recorded ($model+'-extract') 'transport' @('python','-B','cs137.py','extract','--directory',$transport,'--chunk-size','100')
    Invoke-Recorded ($model+'-check-stream') 'transport' @('python','-B','cs137.py','check-stream','--manifest',($transport+'/stream/manifest.json'))
    $input=$Output+'/'+$model+'/transport/stream/manifest.json'
    Invoke-Recorded ($model+'-native-response') 'julia' @('--startup-file=no','--threads=2','--project=simulation','simulation/native_response.jl','--input',$input,'--output',$response,'--trace-examples','4','--charge-csv','examples','--native-failure-policy','record')
    $rp=Join-Path $root ($response+'/run.json'); $rr=Get-Content $rp -Raw|ConvertFrom-Json
    if($rr.status -notin @('completed_provisional_native_response','completed_with_native_failures') -or $rr.counts.initial_decays -ne $Events -or $rr.counts.initial_primaries -ne $Events){throw 'Native response census/status failure'}
    if($rr.native_failure_policy -ne 'record' -or $null -eq $rr.counts.native_failed_groups -or $null -eq $rr.counts.readout_rejected -or $rr.counts.native_failed_groups -lt 0 -or $rr.counts.readout_rejected -lt 0 -or $rr.counts.accepted+$rr.counts.rejected -ne $rr.counts.groups -or $rr.counts.rejected -ne $rr.counts.native_failed_groups+$rr.counts.readout_rejected){throw 'Native response failure accounting mismatch'}
    if(($rr.status -eq 'completed_with_native_failures') -ne ($rr.counts.native_failed_groups -gt 0)){throw 'Native response failure status mismatch'}
    if($rr.counts.native_failed_groups -gt 0){Write-Warning "$model completed_with_native_failures: $($rr.counts.native_failed_groups) native groups unavailable; $($rr.counts.readout_rejected) electronics rejections. Native anomaly unresolved."}
    $report.models[$model]=[ordered]@{status=$rr.status;counts=$rr.counts;response_report_sha256=(Get-FileHash -Algorithm SHA256 $rp).Hash.ToLowerInvariant();native_seconds=$rr.native_drift_and_charge_seconds;electronics_seconds=$rr.electronics_seconds;response_wall_seconds=$rr.solve_replay_readout_export_wall_seconds;process_peak_rss_bytes=$rr.process_peak_rss_bytes}
    Save-Report
  }
  foreach($f in $sourceFiles){if((Get-FileHash -Algorithm SHA256 (Join-Path $root $f)).Hash.ToLowerInvariant() -ne $hashes[$f]){throw "Campaign source changed: $f"}}
  $report.status='completed_provisional_native_campaign'
  $report.native_failure_policy='record'
  $report.native_failed_groups=($report.models.Values | ForEach-Object {$_.counts.native_failed_groups} | Measure-Object -Sum).Sum
  $report.readout_rejected=($report.models.Values | ForEach-Object {$_.counts.readout_rejected} | Measure-Object -Sum).Sum
  if($report.native_failed_groups -gt 0){$report.status='completed_with_native_failures'}
}catch{
  $report.status='failed'; $report.error=$_.Exception.Message; throw
}finally{
  $report.finished_utc=(Get-Date).ToUniversalTime().ToString('o')
  $report.artifact_bytes=(Get-ChildItem $out -Recurse -File|Measure-Object Length -Sum).Sum
  Save-Report
}
Write-Output "$($report.status): $Events initial Cs137 decays per detector; native_failed_groups=$($report.native_failed_groups); readout_rejected=$($report.readout_rejected); output=$Output"
