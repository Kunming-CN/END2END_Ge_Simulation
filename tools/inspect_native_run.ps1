# Inspect a saved small LBNL campaign without starting calculations.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Directory,[switch]$Json)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $PSScriptRoot 'electronics_execution.ps1')
$blocks=New-Object 'System.Collections.Generic.List[object]'
$rows=New-Object 'System.Collections.Generic.List[object]'
$watched=New-Object 'System.Collections.Generic.List[object]'
$lease=$null
$result=[ordered]@{
  schema_version=1;kind='native_run_inspection_v1';status='blocked';recorded_status=$null
  detectors=@();events_per_detector=$null;radiation_seed=$null;expected_native_seed=2609261
  lock_observation='not_checked';stages=@();blockers=@();saved_artifacts_verified=$false
  terminal_compatible=$false;runtime_readiness_checked=$false;simulations_started=0;files_written=0
  scope='Saved-file inspection only; not runtime readiness, active-worker proof, permission to resume or experimental validation.'
}
function Add-InspectBlock([string]$Code,[string]$Where,[string]$Message){
  $blocks.Add([pscustomobject]@{code=$Code;location=$Where;message=$Message})
}
function Watch-InspectFile([string]$Path){
  $watched.Add([pscustomobject]@{path=$Path;hash=(Get-NRHash $root $Path)})
}
function Add-InspectStage([string]$Model,[string]$Name,[string]$Path,[string]$Receipt,[scriptblock]$Check){
  $state='not_started';$detail='No saved phase directory. No work was started.'
  try{
    [void](Resolve-NRPath $root $Path)
    if(Test-Path -LiteralPath $Path){
      $state='partial';$detail='No terminal phase receipt; phase completion is unverified. Preserve available files and inspect logs.'
      if(Test-Path -LiteralPath $Receipt -PathType Leaf){Watch-InspectFile $Receipt;[void](& $Check);$state='complete_verified';$detail='Saved receipt, bindings and supported settings checked.'}
    }
  }catch{
    $detail=$_.Exception.Message;$state='blocked'
    foreach($folder in @('simulation','transport','models')){
      if($detail.Contains('File binding mismatch: '+(Join-Path $root $folder))){$state='source_incompatible';$detail='Current source binding differs; artifact/settings checks are incomplete, not proof of corruption. '+$detail}
    }
  }
  $rows.Add([pscustomobject]@{detector=$Model;stage=$Name;saved_state=$state;detail=$detail})
  if($state -ne 'complete_verified'){Add-InspectBlock $state ($Model+'/'+$Name) $detail}
}
try{
  $candidate=if([IO.Path]::IsPathRooted($Directory)){$Directory}else{Join-Path $root $Directory}
  $dir=Resolve-NRPath $root ([IO.Path]::GetFullPath($candidate))
  $local=Join-Path $root '.local'
  Assert-NR ($dir.StartsWith($local+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) 'Inspection supports project .local runs only'
  Assert-NR (Test-Path -LiteralPath $dir -PathType Container) 'Saved run directory does not exist'
  $lock=Resolve-NRPath $root (Join-Path $dir 'run.lock')
  if(Test-Path -LiteralPath $lock){
    try{$lease=[IO.File]::Open($lock,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None);$result.lock_observation='existing_lock_unheld_at_probe'}
    catch{$result.lock_observation='held_or_inaccessible';throw 'Existing run lock is held or inaccessible; no recovery attempted.'}
  }else{$result.lock_observation='missing';Add-InspectBlock 'missing_lock' 'run.lock' 'No existing run lock; worker ownership is unknown.'}
  $file=Join-Path $dir 'run.json';Watch-InspectFile $file;$r=Read-NRJson $root $file
  Assert-NREqual $r.kind 'native_campaign_v1' 'campaign kind'
  Assert-NRInteger $r.events_per_model 'initial events' 1
  Assert-NR ($r.events_per_model -in @(20,500,10000)) 'Inspection supports small launcher presets, not the preserved million-event campaign'
  Assert-NRInteger $r.seed 'campaign radiation seed' 1
  $models=if($r.PSObject.Properties['detectors']){@($r.detectors)}else{@($r.models.PSObject.Properties.Name)}
  Assert-NR ($models.Count -gt 0 -and $models.Count -le 2 -and ($models|Select-Object -Unique).Count -eq $models.Count) 'Invalid detector set'
  foreach($model in $models){Assert-NR ($model -is [string] -and $model -cin @('AK02','SAP22')) 'Unsupported detector in saved run'}
  Assert-NR ($r.models -is [System.Management.Automation.PSCustomObject]) 'Missing campaign model records'
  foreach($id in $r.models.PSObject.Properties.Name){Assert-NR ($models -ccontains $id) 'Unexpected campaign model record'}
  if($r.status -cin @('completed_provisional_native_campaign','completed_with_native_failures')){Assert-NREqual @($r.models.PSObject.Properties.Name|Sort-Object) @($models|Sort-Object) 'terminal model records'}
  $result.recorded_status=$r.status;$result.detectors=@($models);$result.events_per_detector=$r.events_per_model;$result.radiation_seed=$r.seed
  $scenario='';if($null -ne $r.scenario){
    Assert-NREqual $r.scenario.file 'scenarios/lbnl-cs137.json' 'scenario file'
    Assert-NREqual $r.scenario.id 'lbnl-cs137' 'scenario identity';$scenario=$r.scenario.file
    try{Test-NRHash $root (Join-Path $root $scenario) $r.scenario.sha256}catch{Add-InspectBlock 'source_changed' $scenario $_.Exception.Message}
  }
  $exporter=Get-NRRecordedExporter $r
  $selectedProfile=Get-EERecordedProfile $root $dir $r
  $custom=$null -ne $r.PSObject.Properties['electronics']
  $result.electronics=[ordered]@{selection=$(if($custom){'saved_custom'}else{'canonical'});profile_path=$selectedProfile;profile=(Read-NRJson $root (Join-Path $root $selectedProfile));binding_verified=$true}
  if($custom){$result.electronics.input=$r.electronics.input;$result.electronics.physics_sha256=$r.electronics.physics_sha256}
  $required=Get-NRCampaignSources $exporter $scenario $custom
  if($r.source_sha256 -isnot [System.Management.Automation.PSCustomObject]){Add-InspectBlock 'source_inventory_missing' 'run.json' 'Campaign source inventory is missing.'}
  else{
    $actual=@($r.source_sha256.PSObject.Properties.Name|Sort-Object)
    if((ConvertTo-NRCanonical $actual) -cne (ConvertTo-NRCanonical @($required|Sort-Object))){Add-InspectBlock 'source_inventory_changed' 'run.json' 'Saved source inventory differs from this launcher revision. Do not edit old receipts.'}
    foreach($name in $required){
      try{Test-NRHash $root (Join-Path $root $name) $r.source_sha256.$name}
      catch{Add-InspectBlock 'source_changed' $name $_.Exception.Message}
    }
  }
  foreach($model in $models){
    $t=Join-Path $dir ($model+'/transport');$response=Join-Path $dir ($model+'/response')
    Add-InspectStage $model 'prepare' $t (Join-Path $t 'prepared.json') {Test-NRPrepared $root $t $model $r.events_per_model $r.seed $exporter}
    Add-InspectStage $model 'transport' $t (Join-Path $t 'run.json') {Test-NRTransport $root $t}
    Add-InspectStage $model 'stream' (Join-Path $t 'stream') (Join-Path $t 'stream/manifest.json') {Test-NRStream $root $t $model $r.events_per_model}
    Add-InspectStage $model 'response' $response (Join-Path $response 'run.json') {
      $parent=$r.models.PSObject.Properties[$model]
      Assert-NR ($null -ne $parent) 'Terminal child has no parent response binding; preserve for explicit recovery review.'
      $rr=Test-NRResponse -Root $root -Directory $response -Model $model -Events $r.events_per_model -Manifest (Join-Path $t 'stream/manifest.json') -ExpectedReportHash $parent.Value.response_report_sha256 -ExpectedProfilePath $selectedProfile
      Assert-NREqual $parent.Value.status $rr.status 'parent/child status';Assert-NREqual $parent.Value.counts $rr.counts 'parent/child census'
    }
  }
  if($r.status -cnotin @('completed_provisional_native_campaign','completed_with_native_failures')){
    Add-InspectBlock 'nonterminal_campaign' 'run.json' 'Recorded campaign is not terminal. A recorded running flag alone does not establish an active worker.'
  }
  if(@($rows|Where-Object {$_.saved_state -ne 'complete_verified'}).Count -eq 0){
    $fail=0;$reject=0
    foreach($model in $models){$fail+=$r.models.$model.counts.native_failed_groups;$reject+=$r.models.$model.counts.readout_rejected}
    Assert-NREqual $r.native_failed_groups $fail 'campaign native-failure total';Assert-NREqual $r.readout_rejected $reject 'campaign readout-rejection total'
    Assert-NREqual ($r.status -ceq 'completed_with_native_failures') ($fail -gt 0) 'campaign failure status'
  }
  $result.saved_artifacts_verified=(@($rows|Where-Object {$_.saved_state -ne 'complete_verified'}).Count -eq 0)
  if($custom){
    try{[void](Get-EERecordedProfile $root $dir $r)}
    catch{
      $result.saved_artifacts_verified=$false;$result.electronics.binding_verified=$false
      Add-InspectBlock 'changed_during_inspection' 'electronics' $_.Exception.Message
      if($_.Exception.Message -match 'Execution settings source compatibility|Frozen readout defaults|Frozen native profile'){
        Add-InspectBlock 'source_changed' 'electronics' $_.Exception.Message
      }
    }
  }
}catch{
  $result.saved_artifacts_verified=$false
  if($result.Contains('electronics')){$result.electronics.binding_verified=$false}
  $code=if($_.Exception.Message -match 'Execution settings source compatibility|Frozen readout defaults|Frozen native profile'){'source_changed'}else{'inspection_blocked'}
  Add-InspectBlock $code 'run' $_.Exception.Message
}
finally{
  try{
    foreach($entry in $watched){
      try{Test-NRHash $root $entry.path $entry.hash}catch{$result.saved_artifacts_verified=$false;if($result.Contains('electronics')){$result.electronics.binding_verified=$false};Add-InspectBlock 'changed_during_inspection' $entry.path $_.Exception.Message}
    }
  }finally{if($null -ne $lease){$lease.Dispose()}}
}
$result.snapshot_stable=(@($blocks|Where-Object {$_.code -eq 'changed_during_inspection'}).Count -eq 0)
$result.artifact_integrity=if($result.saved_artifacts_verified){'verified'}else{'not_fully_checked'}
$result.source_compatibility=if(@($blocks|Where-Object {$_.code -like 'source*'}).Count -gt 0 -or @($rows|Where-Object {$_.saved_state -eq 'source_incompatible'}).Count -gt 0){'incompatible'}else{'no_mismatch_detected'}
$result.stages=@($rows.ToArray());$result.blockers=@($blocks.ToArray())
$result.terminal_compatible=($blocks.Count -eq 0 -and $result.saved_artifacts_verified)
if($result.terminal_compatible){$result.status='terminal_verified'}
if($Json){$result|ConvertTo-Json -Depth 12}
else{
  Write-Output ('Inspection: '+$result.status+'; recorded campaign status: '+$result.recorded_status)
  Write-Output ('Detectors: '+($result.detectors -join ', ')+'; initial decays/model: '+$result.events_per_detector)
  Write-Output ('Radiation seed: '+$result.radiation_seed+'; expected native seed: '+$result.expected_native_seed)
  Write-Output ('Lock observation: '+$result.lock_observation)
  if($result.Contains('electronics')){Write-Output ('Electronics: '+$result.electronics.selection+'; '+$result.electronics.profile_path)}
  $rows|Format-Table detector,stage,saved_state,detail -Wrap -AutoSize
  foreach($block in $blocks){Write-Output ('BLOCKED ['+$block.code+'] '+$block.location+': '+$block.message)}
  Write-Output 'Inspection did not check runtime readiness or start/resume work. Preserve all originals; never edit receipts to bypass a mismatch.'
}
if($blocks.Count -gt 0){exit 2}else{exit 0}
