# Serial nominal Cs137 -> native SSD -> synthetic readout campaign. No installs.
param(
  [Parameter(Mandatory=$true)][ValidatePattern('^\.local/[A-Za-z0-9_/-]+$')][string]$Output,
  [ValidateSet(20,500,10000)][int]$Events=500,
  [ValidateRange(1,2147483647)][int]$Seed=26092631,
  [ValidateSet('AK02','SAP22')][string[]]$Models=@('AK02','SAP22'),
  [string]$Pilot='',
  [ValidatePattern('^\.local/[A-Za-z0-9_/-]+$')][string]$Exporter='.local/m2a/cs137-build-v1/cryostat_export',
  [ValidatePattern('^[A-Za-z0-9_.\/-]*$')][string]$ScenarioFile='',
  [switch]$Resume
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
function Acquire-RunLock([string]$Directory){
  $path=Join-Path $Directory 'run.lock'
  try{return [IO.File]::Open($path,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
  catch{throw "Another process owns this campaign lock: $path"}
}
$out=Assert-Local $Output
$Models=@($Models|Select-Object -Unique); if($Models.Count -lt 1){throw 'Select at least one model'}
$existingReport=$null; $runLock=$null
if(Test-Path -LiteralPath $out){
  if(!$Resume){throw 'Output exists; preserve it and choose a new name, or use -Resume'}
  $runLock=Acquire-RunLock $out
  $runFile=Join-Path $out 'run.json'; if(!(Test-Path $runFile -PathType Leaf)){throw 'Resume requires an existing run.json; preserve the directory'}
  $existingReport=Get-Content $runFile -Raw|ConvertFrom-Json
  if($existingReport.kind -ne 'native_campaign_v1'){throw 'Resume run kind mismatch'}
}else{
  if($Resume){throw 'Resume requested but output does not exist'}
}
$j=(Get-Command julia -ErrorAction Stop).Source
$wrapper=Join-Path $root 'transport/Run.cmd'
$sourceFiles=@('tools/run_native_campaign.ps1','transport/cs137.py','transport/cryostat_export.cc','transport/cryostat_nominal.json','transport/handoff.py','transport/pixi.lock','simulation/native_response_guarded.jl','simulation/native_boundary_guard.jl','simulation/native_response.jl','simulation/native_stream.jl','simulation/readout_profiles.jl','simulation/native_readout_profile.json','simulation/native_li_example.jl','simulation/readout.jl','simulation/replay.jl','simulation/run.jl','simulation/Manifest.toml')
$scenarioId=''; if($ScenarioFile){
  $scenarioPath=[IO.Path]::GetFullPath((Join-Path $root $ScenarioFile))
  if(!$scenarioPath.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or !(Test-Path $scenarioPath -PathType Leaf)){throw 'ScenarioFile must be an existing project file'}
  $scenarioDoc=Get-Content $scenarioPath -Raw|ConvertFrom-Json; $scenarioId=[string]$scenarioDoc.id; if(!$scenarioId){throw 'ScenarioFile has no id'}
  $sourceFiles+=,$ScenarioFile
}
$exporterFile=Assert-Local $Exporter
if(!(Test-Path -LiteralPath $exporterFile -PathType Leaf)){throw 'Build cryostat_export and supply its project-relative path with -Exporter'}
$sourceFiles+=@($Exporter,'tools/verify_native_pilot.ps1')
$hashes=[ordered]@{}; foreach($f in $sourceFiles){$hashes[$f]=(Get-FileHash -Algorithm SHA256 (Join-Path $root $f)).Hash.ToLowerInvariant()}
if($existingReport){
  $recordedModels=if($existingReport.PSObject.Properties['detectors']){@($existingReport.detectors)}else{@($existingReport.models.PSObject.Properties.Name)}
  if($existingReport.events_per_model -ne $Events -or $existingReport.seed -ne $Seed -or (($recordedModels|Sort-Object) -join ',') -ne (($Models|Sort-Object) -join ',')){throw 'Resume configuration differs from existing run'}
  foreach($f in $sourceFiles){
    $p=$existingReport.source_sha256.PSObject.Properties[$f]
    if(!$p -or $p.Value -ne $hashes[$f]){throw "Resume source changed: $f"}
  }
  $recordedScenario=if($existingReport.PSObject.Properties['scenario'] -and $null -ne $existingReport.scenario){[string]$existingReport.scenario.file}else{''}
  if($recordedScenario -ne $ScenarioFile){throw 'Resume scenario binding differs from existing run'}
}
$pilotValidation=$null
if($Events -eq 10000){
  if(!$Pilot){throw '10000 requires a completed 500-decay pilot directory'}
  $pilotDir=Assert-Local $Pilot; $p=Get-Content (Join-Path $pilotDir 'run.json') -Raw|ConvertFrom-Json
  if($p.status -ne 'completed_provisional_native_campaign' -or $p.events_per_model -ne 500){throw 'Pilot is not a completed 500/model campaign'}
  $pilotValidation=& (Join-Path $PSScriptRoot 'verify_native_pilot.ps1') -Pilot $Pilot -Exporter $Exporter -Models $Models | ConvertFrom-Json
  if($pilotValidation.status -ne 'passed'){throw 'Full pilot verification failed'}
  # Launcher/verifier revisions are recorded separately, never rebased into old receipts.
  # The verifier compares every recorded compute dependency and every pilot artifact.
  foreach($f in $sourceFiles){
    if($f -in @('tools/run_native_campaign.ps1','tools/verify_native_pilot.ps1')){continue}
    if($p.source_sha256.PSObject.Properties[$f].Value -ne $hashes[$f]){throw "Pilot source differs: $f"}
  }
  foreach($m in $Models){
    $pr=Get-Content (Join-Path $pilotDir ($m+'/response/run.json')) -Raw|ConvertFrom-Json
    if($pr.status -ne 'completed_provisional_native_response' -or $pr.counts.initial_decays -ne 500 -or $pr.counts.groups -lt 1){throw "Pilot has no complete positive native integration: $m"}
    $h=(Get-FileHash -Algorithm SHA256 (Join-Path $pilotDir ($m+'/response/run.json'))).Hash.ToLowerInvariant()
    if($p.models.PSObject.Properties[$m].Value.response_report_sha256 -ne $h){throw 'Pilot report hash mismatch'}
  }
  $estimatedBytes=20*1.5*(Get-ChildItem $pilotDir -Recurse -File|Measure-Object Length -Sum).Sum
  $drive=Get-PSDrive -Name ([IO.Path]::GetPathRoot($out).TrimEnd('\').TrimEnd(':'))
  if($estimatedBytes -gt 0.7*$drive.Free){throw 'Pilot-scaled storage estimate lacks free-space headroom'}
}
if(!$existingReport){New-Item -ItemType Directory -Path $out | Out-Null; $runLock=Acquire-RunLock $out}
$env:OPENBLAS_NUM_THREADS='1'; $env:OMP_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'
$modelsMap=[ordered]@{}; $oldStages=@(); $resumeCount=0; $started=(Get-Date).ToUniversalTime().ToString('o')
$scenarioBinding=if($ScenarioFile){[ordered]@{id=$scenarioId;file=$ScenarioFile;sha256=$hashes[$ScenarioFile]}}else{$null}
if($existingReport){
  foreach($p in $existingReport.models.PSObject.Properties){$modelsMap[$p.Name]=$p.Value}
  $oldStages=@($existingReport.stages); $resumeCount=if($existingReport.PSObject.Properties['resume_count']){[int]$existingReport.resume_count+1}else{1}; $started=$existingReport.started_utc
}
$report=[ordered]@{kind='native_campaign_v1';status='running';events_per_model=$Events;seed=$Seed;detectors=$Models;scenario=$scenarioBinding;source_sha256=$hashes;models=$modelsMap;stages=$oldStages;pilot=$Pilot;pilot_verification=$pilotValidation;resume_count=$resumeCount;assumption='Explicit nominal LBNL assembly and isolated reset readout; not as-built, calibrated spectra or continuous acquisition';started_utc=$started}
function Save-Report {
  $target=Join-Path $out 'run.json'; $temp=$target+'.partial-'+$PID+'-'+[DateTime]::UtcNow.Ticks
  $json=$report|ConvertTo-Json -Depth 14
  [IO.File]::WriteAllText($temp,$json,(New-Object Text.UTF8Encoding($false)))
  $fs=[IO.File]::Open($temp,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
  try{$fs.Flush($true)}finally{$fs.Dispose()}
  $backup=$target+'.backup-'+$PID+'-'+[DateTime]::UtcNow.Ticks
  try{
    for($attempt=0;$attempt -lt 3;$attempt++){
      try{
        if(Test-Path $target -PathType Leaf){
          [IO.File]::Replace($temp,$target,$backup,$true)
          if(Test-Path $backup -PathType Leaf){Remove-Item $backup -Force}
        }else{[IO.File]::Move($temp,$target)}
        return
      }catch{
        if($attempt -eq 2){throw}
        Start-Sleep -Milliseconds (100*($attempt+1))
      }
    }
  }finally{
    if(Test-Path $temp -PathType Leaf){Remove-Item $temp -Force -ErrorAction SilentlyContinue}
    if(Test-Path $backup -PathType Leaf){Remove-Item $backup -Force -ErrorAction SilentlyContinue}
  }
}
function Invoke-Recorded([string]$Label,[string]$Kind,[string[]]$CommandArgs){
  foreach($arg in $CommandArgs){if($arg -match '["&|<>%`\r\n]'){throw 'Unsafe command argument'}}
  $quoted=($CommandArgs|ForEach-Object{'"'+$_+'"'}) -join ' '
  $rec=[ordered]@{stage=$Label;kind=$Kind;arguments=$CommandArgs;status='failed';exit_code=$null}; $timer=[Diagnostics.Stopwatch]::StartNew()
  Write-Output "START $Label"
  try {
    $logLabel=$Label; $attempt=1
    while((Test-Path (Join-Path $out ($logLabel+'.stdout.log'))) -or (Test-Path (Join-Path $out ($logLabel+'.stderr.log')))){$attempt++;$logLabel=$Label+'.resume'+$attempt}
    $rec.log_prefix=$logLabel
    $stdout=Join-Path $out ($logLabel+'.stdout.log'); $stderr=Join-Path $out ($logLabel+'.stderr.log')
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
function Hash-Lower([string]$Path){(Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()}
function Add-Reused([string]$Label,[string]$Kind,[string]$Evidence){
  $report.stages+=,[ordered]@{stage=$Label;kind=$Kind;status='reused_verified';exit_code=0;evidence=$Evidence;wall_seconds=0}
  Save-Report; Write-Output "REUSE $Label ($Evidence)"
}
function Validate-Prepared([string]$Model,[string]$Directory){
  $file=Join-Path $Directory 'prepared.json'; if(!(Test-Path $file -PathType Leaf)){return $false}
  $m=Get-Content $file -Raw|ConvertFrom-Json
  if($m.kind -ne 'cs137_prepared_v1' -or $m.model_id -ne $Model -or $m.primary_count -ne $Events -or $m.seed -ne $Seed){throw "Prepared input configuration mismatch: $Model"}
  foreach($p in $m.files_sha256.PSObject.Properties){$f=Join-Path $Directory $p.Name;if(!(Test-Path $f -PathType Leaf) -or (Hash-Lower $f) -ne $p.Value){throw "Prepared artifact changed: $Model/$($p.Name)"}}
  foreach($p in $m.upstream_sha256.PSObject.Properties){$f=Join-Path $root ('.local/transport/LBNL/'+$p.Name);if(!(Test-Path $f -PathType Leaf) -or (Hash-Lower $f) -ne $p.Value){throw "LBNL upstream changed/missing: $($p.Name)"}}
  return $true
}
function Validate-Transport([string]$Directory){
  $file=Join-Path $Directory 'run.json'; if(!(Test-Path $file -PathType Leaf)){return $false}
  $r=Get-Content $file -Raw|ConvertFrom-Json
  $prepared=Join-Path $Directory 'prepared.json';$truth=Join-Path $Directory 'truth.lh5'
  if($r.status -ne 'complete' -or !(Test-Path $truth -PathType Leaf) -or $r.prepared_sha256 -ne (Hash-Lower $prepared) -or $r.source_lh5_sha256 -ne (Hash-Lower $truth)){throw 'Completed transport receipt/hash mismatch'}
  return $true
}
function Validate-Response([string]$Model,[string]$Directory,[string]$ExpectedReportHash=''){
  $file=Join-Path $Directory 'run.json'; if(!(Test-Path $file -PathType Leaf)){return $null}
  if($ExpectedReportHash -and (Hash-Lower $file) -ne $ExpectedReportHash){throw "Saved native response receipt hash changed: $Model"}
  $r=Get-Content $file -Raw|ConvertFrom-Json
  if($r.status -notin @('completed_provisional_native_response','completed_with_native_failures') -or $r.model_id -ne $Model -or $r.counts.initial_decays -ne $Events -or $r.counts.initial_primaries -ne $Events){throw "Native response receipt mismatch: $Model"}
  $modelDir=Split-Path $Directory -Parent
  $manifest=Join-Path $modelDir 'transport/stream/manifest.json'; if(!(Test-Path $manifest -PathType Leaf) -or $r.input_sha256 -ne (Hash-Lower $manifest)){throw "Native response input binding mismatch: $Model"}
  $transportRun=Join-Path $modelDir 'transport/run.json'; $tr=Get-Content $transportRun -Raw|ConvertFrom-Json
  if($r.source_lh5_sha256 -ne $tr.source_lh5_sha256){throw "Native response raw-source binding mismatch: $Model"}
  $profilePath=Join-Path $root 'simulation/native_readout_profile.json'
  if($r.profile_sha256 -ne (Hash-Lower $profilePath)){throw "Native response profile binding mismatch: $Model"}
  $modelPath=Join-Path $root ('models/'+$Model+'.yaml')
  if($r.model_sha256 -ne (Hash-Lower $modelPath)){throw "Native response model binding mismatch: $Model"}
  foreach($p in $r.artifacts.PSObject.Properties){
    if([IO.Path]::GetFileName($p.Name) -ne $p.Name){throw "Unsafe response artifact name: $($p.Name)"}
    $artifact=Join-Path $Directory $p.Name
    if(!(Test-Path $artifact -PathType Leaf) -or (Hash-Lower $artifact) -ne $p.Value){throw "Native response artifact changed: $Model/$($p.Name)"}
  }
  foreach($p in $r.source_sha256.PSObject.Properties){
    if([IO.Path]::GetFileName($p.Name) -ne $p.Name){throw "Unsafe native source name: $($p.Name)"}
    $source=Join-Path $root ('simulation/'+$p.Name)
    if(!(Test-Path $source -PathType Leaf) -or (Hash-Lower $source) -ne $p.Value){throw "Native response source changed: simulation/$($p.Name)"}
  }
  if($r.boundary_guard.kind -ne 'ssd_0_11_8_boundary_guard_v1' -or !$r.boundary_guard.installed -or $r.boundary_guard.package_files_modified){throw "Native boundary guard provenance missing: $Model"}
  if($r.guard_wrapper_sha256 -ne (Hash-Lower (Join-Path $root 'simulation/native_response_guarded.jl')) -or $r.guard_source_sha256 -ne (Hash-Lower (Join-Path $root 'simulation/native_boundary_guard.jl'))){throw "Native boundary guard source binding mismatch: $Model"}
  return $r
}
Save-Report
try {
  foreach($model in $Models){
    $modelDir=Join-Path $out $model; if(!(Test-Path $modelDir)){New-Item -ItemType Directory -Path $modelDir|Out-Null}
    $transport='../'+$Output+'/'+$model+'/transport'; $response=$Output+'/'+$model+'/response'
    $transportFull=Join-Path $modelDir 'transport'; $responseFull=Join-Path $modelDir 'response'
    if($Resume -and (Validate-Prepared $model $transportFull)){Add-Reused ($model+'-prepare') 'transport' 'prepared.json + hashes'}
    else {
      if(Test-Path $transportFull){throw "$model transport directory exists without a reusable prepared stage; preserve it and inspect"}
      Invoke-Recorded ($model+'-prepare') 'transport' @('python','-B','cs137.py','prepare','--model',$model,'--output',$transport,'--exporter',('../'+$Exporter),'--events',[string]$Events,'--seed',[string]$Seed)
      if(!(Validate-Prepared $model $transportFull)){throw "$model prepare did not produce a reusable receipt"}
    }
    if($Resume -and (Validate-Transport $transportFull)){Add-Reused ($model+'-transport') 'transport' 'run.json + truth.lh5 hash'}
    else {
      if($Resume -and ((Test-Path (Join-Path $transportFull 'run.json')) -or (Test-Path (Join-Path $transportFull 'truth.lh5')) -or (Test-Path (Join-Path $transportFull 'run.log')))){throw "$model transport attempt is incomplete; preserved in place and not automatically rerun"}
      Invoke-Recorded ($model+'-transport') 'transport' @('python','-B','cs137.py','run','--directory',$transport)
      if(!(Validate-Transport $transportFull)){throw "$model transport did not produce a reusable receipt"}
    }
    $manifestFull=Join-Path $transportFull 'stream/manifest.json'
    if($Resume -and (Test-Path $manifestFull -PathType Leaf)){
      Add-Reused ($model+'-extract') 'transport' 'existing stream manifest; checked next'
    }else{
      if($Resume -and (Test-Path (Join-Path $transportFull 'stream'))){throw "$model stream directory is incomplete; preserved in place and not automatically regenerated"}
      Invoke-Recorded ($model+'-extract') 'transport' @('python','-B','cs137.py','extract','--directory',$transport,'--chunk-size','100')
    }
    Invoke-Recorded ($model+'-check-stream') 'transport' @('python','-B','cs137.py','check-stream','--manifest',($transport+'/stream/manifest.json'))
    $input=$Output+'/'+$model+'/transport/stream/manifest.json'
    $expectedResponseHash=''
    if($existingReport -and $existingReport.models.PSObject.Properties[$model]){$expectedResponseHash=[string]$existingReport.models.PSObject.Properties[$model].Value.response_report_sha256}
    $rr=if($Resume){Validate-Response $model $responseFull $expectedResponseHash}else{$null}
    if($null -ne $rr){Add-Reused ($model+'-native-response') 'julia' 'terminal response/run.json + artifact/input/source hashes'}
    else{
      if($Resume -and (Test-Path $responseFull)){throw "$model native response is incomplete; this v1 preserves it and does not claim group-level resume"}
      Invoke-Recorded ($model+'-native-response') 'julia' @('--startup-file=no','--threads=2','--project=simulation','simulation/native_response_guarded.jl','--input',$input,'--output',$response,'--trace-examples','4','--charge-csv','examples','--native-failure-policy','record')
      $rr=Validate-Response $model $responseFull; if($null -eq $rr){throw "$model native response missing terminal receipt"}
    }
    $rp=Join-Path $responseFull 'run.json'
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
  try{
    $report.finished_utc=(Get-Date).ToUniversalTime().ToString('o')
    $report.artifact_bytes=(Get-ChildItem $out -Recurse -File|Measure-Object Length -Sum).Sum
    Save-Report
  }finally{
    if($null -ne $runLock){$runLock.Dispose()}
  }
}
Write-Output "$($report.status): $Events initial Cs137 decays per selected detector ($($Models -join ',')); native_failed_groups=$($report.native_failed_groups); readout_rejected=$($report.readout_rejected); output=$Output"
