# Shared read-only validation for the fixed LBNL native-response contract.
# No runtime imports, process launch, writes, source rebasing or cache deserialization.
function Assert-NR([bool]$Ok,[string]$Message){if(!$Ok){throw $Message}}
function Resolve-NRPath([string]$Root,[string]$Path){
  $rootPath=[IO.Path]::GetFullPath($Root).TrimEnd('\','/')
  $full=[IO.Path]::GetFullPath($Path)
  Assert-NR ($full.StartsWith($rootPath+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) 'Validation path escapes project'
  $relative=$full.Substring($rootPath.Length+1)
  Assert-NR ($relative -notmatch '[:*?]') 'Unsafe validation path'
  $scan=$full
  while($scan.Length -ge $rootPath.Length){
    $item=Get-Item -LiteralPath $scan -Force -ErrorAction SilentlyContinue
    if($null -ne $item){Assert-NR (!(($item.Attributes) -band [IO.FileAttributes]::ReparsePoint)) ('Linked validation path refused: '+$relative)}
    if($scan -eq $rootPath){break};$scan=[IO.Path]::GetDirectoryName($scan)
  }
  return $full
}
function Get-NRHash([string]$Root,[string]$Path){
  $full=Resolve-NRPath $Root $Path
  Assert-NR (Test-Path -LiteralPath $full -PathType Leaf) ('Missing validation file: '+$Path)
  return (Get-FileHash -LiteralPath $full -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
}
function Test-NRHash([string]$Root,[string]$Path,$Expected){
  Assert-NR ($Expected -is [string] -and $Expected -cmatch '^[0-9a-f]{64}$') 'Missing or malformed SHA256 binding'
  Assert-NR ((Get-NRHash $Root $Path) -ceq $Expected) ('File binding mismatch: '+$Path)
}
function Read-NRJson([string]$Root,[string]$Path){
  $full=Resolve-NRPath $Root $Path
  Assert-NR (Test-Path -LiteralPath $full -PathType Leaf) ('Missing JSON receipt: '+$Path)
  return (Get-Content -LiteralPath $full -Raw -ErrorAction Stop|ConvertFrom-Json -ErrorAction Stop)
}
function Assert-NRInteger($Value,[string]$Label,[long]$Minimum=0){
  Assert-NR (($Value -is [int] -or $Value -is [long]) -and $Value -ge $Minimum) ('Invalid integer: '+$Label)
}
function ConvertTo-NRCanonical($Value){
  if($null -eq $Value){return 'null'}
  if($Value -is [System.Management.Automation.PSCustomObject] -or $Value -is [System.Collections.IDictionary]){
    $names=if($Value -is [System.Collections.IDictionary]){@($Value.Keys)}else{@($Value.PSObject.Properties.Name)}
    $pairs=@(foreach($name in ($names|Sort-Object -CaseSensitive)){
      $v=if($Value -is [System.Collections.IDictionary]){$Value[$name]}else{$Value.$name}
      (ConvertTo-Json -InputObject ([string]$name) -Compress)+':'+(ConvertTo-NRCanonical $v)
    });return '{'+($pairs -join ',')+'}'
  }
  if($Value -is [array]){return '['+((@($Value|ForEach-Object {ConvertTo-NRCanonical $_})) -join ',')+']'}
  if($Value -is [double] -or $Value -is [decimal]){return ([double]$Value).ToString('R',[Globalization.CultureInfo]::InvariantCulture)}
  return (ConvertTo-Json -InputObject $Value -Compress)
}
function Assert-NREqual($Actual,$Expected,[string]$Label){
  Assert-NR ((ConvertTo-NRCanonical $Actual) -ceq (ConvertTo-NRCanonical $Expected)) ('Configuration differs: '+$Label)
}
function Assert-NRMap([string]$Root,[string]$Folder,$Map,[string[]]$Required){
  Assert-NR ($Map -is [System.Management.Automation.PSCustomObject]) 'Missing file inventory'
  $actualNames=@($Map.PSObject.Properties.Name|Sort-Object -CaseSensitive)
  Assert-NREqual $actualNames @($Required|Sort-Object -CaseSensitive) 'Required file list'
  foreach($entry in $Map.PSObject.Properties){
    Assert-NR ($entry.Name -cmatch '^[A-Za-z0-9_][A-Za-z0-9_.-]*$') 'Invalid inventory filename'
    Test-NRHash $Root (Join-Path $Folder $entry.Name) $entry.Value
  }
}
function Get-NRProducerSources {
  return @('CMakeLists.txt','cryostat-source.json','cryostat_export.cc','cryostat_nominal.json','cs137.py','handoff.py','pixi.lock','pixi.toml')
}
function Get-NRPreparedFiles {
  return @('canonical.gdml','geometry-report.json','geometry.gdml','geometry.log','parameters.txt','probe-points.txt','run.mac','scenario.json')
}
function Test-NRPrepared([string]$Root,[string]$Directory,[string]$Model,[int]$Events,[int]$RadiationSeed,[string]$Exporter){
  $m=Read-NRJson $Root (Join-Path $Directory 'prepared.json')
  Assert-NREqual $m.kind 'cs137_prepared_v1' 'prepared kind'
  Assert-NREqual $m.source_pdg 1000551370 'prepared Cs137 source'
  Assert-NREqual $m.model_id $Model 'prepared detector'
  Assert-NRInteger $m.primary_count 'prepared count';Assert-NREqual $m.primary_count $Events 'prepared count'
  Assert-NRInteger $m.seed 'radiation seed' 1;Assert-NREqual $m.seed $RadiationSeed 'radiation seed'
  Assert-NRMap $Root $Directory $m.files_sha256 (Get-NRPreparedFiles)
  Assert-NRMap $Root (Join-Path $Root 'transport') $m.source_sha256 (Get-NRProducerSources)
  $up=Read-NRJson $Root (Join-Path $Root 'transport/cryostat-source.json')
  Assert-NRMap $Root (Join-Path $Root '.local/transport/LBNL') $m.upstream_sha256 @($up.files|ForEach-Object {$_.name})
  foreach($f in $up.files){Assert-NREqual $m.upstream_sha256.($f.name) $f.sha256 'pinned upstream'}
  Test-NRHash $Root (Join-Path $Root ('models/'+$Model+'.yaml')) $m.model_sha256
  Test-NRHash $Root (Join-Path $Root $Exporter) $m.exporter_sha256
  return $m
}
function Test-NRTransport([string]$Root,[string]$Directory){
  $r=Read-NRJson $Root (Join-Path $Directory 'run.json')
  Assert-NREqual $r.status 'complete' 'transport status';Assert-NREqual $r.returncode 0 'transport exit'
  Test-NRHash $Root (Join-Path $Directory 'prepared.json') $r.prepared_sha256
  Test-NRHash $Root (Join-Path $Directory 'truth.lh5') $r.source_lh5_sha256
  return $r
}
function Test-NRStream([string]$Root,[string]$Directory,[string]$Model,[int]$Events){
  $m=Read-NRJson $Root (Join-Path $Directory 'stream/manifest.json')
  Assert-NREqual $m.kind 'cs137_decay_stream_v1' 'stream kind';Assert-NREqual $m.status 'complete' 'stream status'
  Assert-NREqual $m.model_id $Model 'stream detector';Assert-NRInteger $m.primary_count 'stream count';Assert-NREqual $m.primary_count $Events 'stream count'
  $bindings=[ordered]@{'prepared.json'=$m.prepared_sha256;'run.json'=$m.run_sha256;'truth.lh5'=$m.source_lh5_sha256;'geometry.gdml'=$m.geometry_sha256;'run.mac'=$m.macro_sha256;'scenario.json'=$m.config_sha256}
  foreach($b in $bindings.GetEnumerator()){Test-NRHash $Root (Join-Path $Directory $b.Key) $b.Value}
  Assert-NRMap $Root (Join-Path $Root 'transport') $m.source_sha256 (Get-NRProducerSources)
  Test-NRHash $Root (Join-Path $Root ('models/'+$Model+'.yaml')) $m.model_sha256
  Assert-NREqual $m.units ([ordered]@{energy='keV';length='mm';time='ns'}) 'stream units'
  Assert-NREqual $m.source_lh5 '../truth.lh5' 'stream raw location'
  Assert-NREqual $m.raw_position_unit 'm' 'raw position units';Assert-NREqual $m.raw_track_energy_unit 'MeV' 'raw track energy units'
  $prep=Read-NRJson $Root (Join-Path $Directory 'prepared.json')
  foreach($key in @('coordinate_transform','grouping_policy','clock_policy','decay_photon_line_window_keV')){Assert-NREqual $m.$key $prep.$key ('prepared/stream '+$key)}
  $next=0;$names=@()
  Assert-NR ($m.chunks -is [array] -and $m.chunks.Count -gt 0) 'Missing stream chunks'
  foreach($c in $m.chunks){
    Assert-NR ($c.file -cmatch '^decays-[0-9]{8}\.jsonl$' -and $names -cnotcontains $c.file) 'Invalid or duplicate stream chunk'
    Assert-NRInteger $c.count 'chunk count' 1;Assert-NRInteger $c.first_global_decay_id 'chunk start'
    Assert-NREqual $c.first_global_decay_id $next 'contiguous chunk census'
    Test-NRHash $Root (Join-Path (Join-Path $Directory 'stream') $c.file) $c.sha256
    $next+=$c.count;$names+=,$c.file
  }
  Assert-NREqual $next $Events 'total chunk census';Assert-NREqual $m.global_decay_id_range @(0,($Events-1)) 'global event range'
  return $m
}
function Get-NRConsumerSources([string]$Contract='guarded'){
  $names=@('Manifest.toml','Project.toml','native_li_example.jl','native_response.jl','native_stream.jl','readout.jl','readout_demo.json','readout_profiles.jl','replay.jl','run.jl','test_native_response.jl','test_native_stream.jl','test_readout_profiles.jl')
  if($Contract -eq 'guarded'){$names+=@('native_response_guarded.jl','native_boundary_guard.jl')}
  return $names
}
function Test-NRResponse {
  param([string]$Root,[string]$Directory,[string]$Model,[int]$Events,[string]$Manifest,
    [string]$ExpectedReportHash='',[switch]$NewChild,
    [ValidateSet('guarded','legacy_unguarded')][string]$Contract='guarded')
  $file=Join-Path $Directory 'run.json'
  if(!$NewChild){Test-NRHash $Root $file $ExpectedReportHash}
  elseif($ExpectedReportHash){Test-NRHash $Root $file $ExpectedReportHash}
  $r=Read-NRJson $Root $file
  Assert-NREqual $r.kind 'native_response_v1' 'response kind'
  Assert-NREqual $r.input_kind 'cs137_decay_stream_v1' 'response input kind'
  Assert-NREqual $r.model_id $Model 'response detector'
  Assert-NR ($r.status -cin @('completed_provisional_native_response','completed_with_native_failures')) 'Response is not terminal'
  $countNames=@('accepted','analog_samples','decay_photons','groups','initial_decays','initial_primaries','line_photons','native_charge_samples','native_failed_groups','readout_rejected','rejected','saturated','zero_deposit_primaries')
  foreach($key in $countNames){Assert-NRInteger $r.counts.$key ('counts.'+$key)}
  Assert-NREqual $r.counts.initial_decays $Events 'response census';Assert-NREqual $r.counts.initial_primaries $Events 'primary census'
  Assert-NREqual ($r.counts.accepted+$r.counts.rejected) $r.counts.groups 'accepted/rejected partition'
  Assert-NREqual ($r.counts.native_failed_groups+$r.counts.readout_rejected) $r.counts.rejected 'failure/rejection partition'
  Assert-NR ($r.counts.zero_deposit_primaries -le $Events -and $r.counts.line_photons -le $r.counts.decay_photons) 'Response count bounds'
  Assert-NREqual ($r.status -ceq 'completed_with_native_failures') ($r.counts.native_failed_groups -gt 0) 'failure status'
  $artifacts=@('endpoints.csv','endpoints.jsonl','histograms.csv','histograms.json','input-contract.json','input-prepared.json','profile-input.json','profile.json','readout-config.json','scalars.csv','scalars.jsonl','signals.csv','summary.html','traces.jsonl','truth.csv','truth.jsonl')
  if($r.counts.native_failed_groups -gt 0){$artifacts+=,'native-failures.jsonl'}
  Assert-NRMap $Root $Directory $r.artifacts $artifacts
  Assert-NRMap $Root (Join-Path $Root 'simulation') $r.source_sha256 (Get-NRConsumerSources $Contract)
  Assert-NREqual @($r.artifact_bytes.PSObject.Properties.Name|Sort-Object) @($artifacts|Sort-Object) 'artifact byte inventory'
  foreach($name in $artifacts){
    Assert-NRInteger $r.artifact_bytes.$name ('artifact bytes '+$name)
    Assert-NREqual $r.artifact_bytes.$name ((Get-Item -LiteralPath (Join-Path $Directory $name)).Length) ('artifact size '+$name)
  }
  $hist=Read-NRJson $Root (Join-Path $Directory 'histograms.json')
  Assert-NREqual $hist.normalization_denominators $r.counts 'histogram count denominator'
  Assert-NREqual $hist.width_keV 5 'histogram width'
  Test-NRHash $Root $Manifest $r.input_sha256
  $m=Read-NRJson $Root $Manifest;$transport=Split-Path (Split-Path $Manifest -Parent) -Parent
  Assert-NREqual $m.model_id $Model 'response stream model';Assert-NREqual $m.primary_count $Events 'response stream count'
  Assert-NREqual $r.source_lh5_sha256 $m.source_lh5_sha256 'response raw source'
  $tr=Read-NRJson $Root (Join-Path $transport 'run.json');Assert-NREqual $r.source_lh5_sha256 $tr.source_lh5_sha256 'response transport source'
  Assert-NREqual (Read-NRJson $Root (Join-Path $Directory 'input-contract.json')) $m 'copied input contract'
  $prepared=Read-NRJson $Root (Join-Path $transport 'prepared.json')
  Assert-NREqual (Read-NRJson $Root (Join-Path $Directory 'input-prepared.json')) $prepared 'copied input preparation'
  Test-NRHash $Root (Join-Path $Root ('models/'+$Model+'.yaml')) $r.model_sha256
  $settings=[ordered]@{parcels=16;seed_family=2609261;diffusion=$true;end_drift_when_no_field=$false;self_repulsion=$false;drift_dt_ns=2;nominal_drift_cap_ns=10000;readout_contact_id=1;temperature_K=77;stored_temperature_K=78;native_failure_policy='record';charge_csv_policy='examples';trace_selection='first 4 pulse groups in original census order'}
  foreach($p in $settings.GetEnumerator()){Assert-NREqual $r.($p.Key) $p.Value $p.Key}
  Assert-NREqual $r.bias_V $(if($Model -ceq 'AK02'){500}else{700}) 'canonical bias'
  Assert-NREqual $r.native_failure_allowlist @('Noncontact endpoint outside crystal','Invalid waveform support') 'native_failure_allowlist'
  Assert-NREqual $r.seed_rule 'SHA256(seed/global_event_id/raw_row_index/parcel_index), first8 bytes big-endian UInt64; no chunk/group index' 'seed_rule'
  Assert-NREqual $r.field_settings ([ordered]@{precision_bits=64;min_spacing_mm=0.05;max_spacing_mm=2;sor=1;potential_rechecks=4}) 'field settings'
  Assert-NREqual $r.units ([ordered]@{charge='fC';current='nA';voltage='V';energy='keV';time='ns'}) 'response units'
  Assert-NREqual $r.grouping_policy $m.grouping_policy 'grouping policy'
  Assert-NREqual $m.grouping_policy ([ordered]@{activity_live_time_pileup_claim=$false;horizon_ns=100000;interval='[origin, origin+horizon)';name='nominal_isolated_windows_v1';state_at_group_start='reset';tail='truncate at horizon; recovery not established'}) 'reviewed grouping'
  $profile=Read-NRJson $Root (Join-Path $Root 'simulation/native_readout_profile.json')
  Test-NRProfile $profile
  Test-NRHash $Root (Join-Path $Root 'simulation/native_readout_profile.json') $r.profile_sha256
  Test-NRHash $Root (Join-Path $Directory 'profile-input.json') $r.profile_sha256
  Assert-NREqual $r.profile $profile 'recorded profile'
  Assert-NREqual (Read-NRJson $Root (Join-Path $Directory 'profile.json')) $profile 'copied profile'
  $expected=Read-NRJson $Root (Join-Path $Root 'simulation/readout_demo.json')
  $expected.schema_version=2;$expected.expected_primary_count=$Events
  $expected.PSObject.Properties.Remove('max_total_samples')
  foreach($p in $profile.settings.PSObject.Properties){$expected|Add-Member -NotePropertyName $p.Name -NotePropertyValue $p.Value -Force}
  $resolved=Join-Path $Directory 'readout-config.json'
  Test-NRHash $Root $resolved $r.config_sha256
  Assert-NREqual (Read-NRJson $Root $resolved) $expected 'resolved electronics settings'
  $manifestHash=Get-NRHash $Root (Join-Path $Root 'simulation/Manifest.toml')
  Assert-NREqual $r.environment ([ordered]@{environment_manifest_sha256=$manifestHash;julia_version='1.13.0';ssd_version='0.11.8';project='simulation/Project.toml';manifest='simulation/Manifest.toml'}) 'recorded environment'
  foreach($key in @('julia_version','pinned_julia_version')){Assert-NREqual $r.readout_environment.$key '1.13.0' ('readout '+$key)}
  Assert-NREqual $r.readout_environment.json_version '1.9.0' 'readout JSON version'
  Assert-NREqual $r.readout_environment.manifest_sha256 $manifestHash 'readout manifest'
  Assert-NREqual $r.readout_environment.project_sha256 (Get-NRHash $Root (Join-Path $Root 'simulation/Project.toml')) 'readout project'
  if($Contract -eq 'guarded'){
    Assert-NREqual $r.boundary_guard.kind 'ssd_0_11_8_boundary_guard_v1' 'guard kind'
    Assert-NREqual $r.boundary_guard.installed $true 'guard installed'
    Assert-NREqual $r.boundary_guard.package_files_modified $false 'package changes'
    Assert-NREqual $r.boundary_guard.native_source_sha256 '0358c255e37c38f62eee6f1e476c0ed48560708dfcd3d367d2688eaa022232ad' 'guard upstream'
    Assert-NREqual $r.guard_source_sha256 $r.source_sha256.'native_boundary_guard.jl' 'guard source binding'
    Assert-NREqual $r.guard_wrapper_sha256 $r.source_sha256.'native_response_guarded.jl' 'guard wrapper binding'
  }else{Assert-NR ($null -eq $r.boundary_guard) 'Legacy response unexpectedly declares a guard'}
  return $r
}
function Get-NRCampaignSources([string]$Exporter,[string]$ScenarioFile=''){
  $files=@('tools/run_native_campaign.ps1','tools/native_run_validation.ps1','transport/cs137.py','transport/cryostat_export.cc','transport/cryostat_nominal.json','transport/handoff.py','transport/pixi.lock','simulation/native_response_guarded.jl','simulation/native_boundary_guard.jl','simulation/native_response.jl','simulation/native_stream.jl','simulation/readout_profiles.jl','simulation/native_readout_profile.json','simulation/native_li_example.jl','simulation/readout.jl','simulation/replay.jl','simulation/run.jl','simulation/Manifest.toml','tools/verify_native_pilot.ps1')
  $files+=,$Exporter
  if($ScenarioFile){$files+=,$ScenarioFile}
  return $files
}
function Test-NRFinite($Value){
  return (($Value -is [int] -or $Value -is [long] -or $Value -is [double] -or $Value -is [decimal]) -and ![double]::IsNaN([double]$Value) -and ![double]::IsInfinity([double]$Value))
}
function Test-NRProfile($Profile){
  Assert-NR ($Profile -is [System.Management.Automation.PSCustomObject]) 'Missing profile object'
  Assert-NREqual @($Profile.PSObject.Properties.Name|Sort-Object) @('kind','name','schema_version','settings') 'profile field inventory'
  Assert-NRInteger $Profile.schema_version 'profile version';Assert-NREqual $Profile.schema_version 2 'profile schema'
  Assert-NREqual $Profile.kind 'native_readout_profile_v1' 'profile kind'
  Assert-NR ($Profile.name -is [string] -and $Profile.name -cmatch '^[A-Za-z0-9_.-]{1,80}$') 'Invalid profile name'
  $s=$Profile.settings
  Assert-NR ($s -is [System.Management.Automation.PSCustomObject]) 'Missing profile settings'
  $names=@('feedback_capacitance_pF','feedback_tau_us','pole_zero_tau_us','shaping_tau_us','gain','adc_bits','adc_full_scale_V','threshold_V','peak_policy','peak_gate_start_ns','peak_gate_end_ns')
  Assert-NREqual @($s.PSObject.Properties.Name|Sort-Object) @($names|Sort-Object) 'profile settings inventory'
  foreach($k in @('feedback_capacitance_pF','feedback_tau_us','pole_zero_tau_us','shaping_tau_us','gain','adc_full_scale_V')){
    Assert-NR ((Test-NRFinite $s.$k) -and $s.$k -gt 0) ('Invalid positive profile setting: '+$k)
  }
  Assert-NRInteger $s.adc_bits 'ADC bits' 2;Assert-NR ($s.adc_bits -le 24) 'ADC bits exceed profile contract'
  Assert-NR ((Test-NRFinite $s.threshold_V) -and $s.threshold_V -gt 0 -and $s.threshold_V -lt $s.adc_full_scale_V) 'Invalid profile threshold'
  Assert-NR ($s.peak_policy -cin @('legacy_reject_negative_input','signed_input_positive_peak')) 'Invalid peak policy'
  $start=$s.peak_gate_start_ns;$end=$s.peak_gate_end_ns
  Assert-NREqual ($null -eq $start) ($null -eq $end) 'Both peak gate bounds are required'
  if($null -ne $start){
    Assert-NR ((Test-NRFinite $start) -and (Test-NRFinite $end) -and $start -ge 0 -and $start -lt $end -and $end -le 99998) 'Peak gate outside supported isolated window'
  }
}
