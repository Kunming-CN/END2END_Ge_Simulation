# Read-only pilot verification. Does not modify historical receipts or run physics.
param([Parameter(Mandatory=$true)][string]$Pilot,[Parameter(Mandatory=$true)][string]$Exporter)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pilotDir=[IO.Path]::GetFullPath((Join-Path $root $Pilot)); $localRoot=Join-Path $root '.local'
if(!$pilotDir.StartsWith($localRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Pilot must be inside project .local'}
function Read-Json([string]$Path){Get-Content -LiteralPath $Path -Raw|ConvertFrom-Json}
function Verify-Hash([string]$Path,[string]$Expected){
  $full=[IO.Path]::GetFullPath($Path)
  if(!$full.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Dependency escapes project'}
  if(!(Test-Path -LiteralPath $full -PathType Leaf)){throw "Pilot dependency missing: $full"}
  $checkPath=$full
  while($checkPath.Length -gt $root.Length){
    if((Test-Path -LiteralPath $checkPath) -and ((Get-Item -LiteralPath $checkPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Linked dependency refused'}
    $checkPath=[IO.Path]::GetDirectoryName($checkPath)
  }
  if($Expected -notmatch '^[0-9a-f]{64}$' -or (Get-FileHash -LiteralPath $full -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -ne $Expected){throw "Pilot dependency mismatch: $full"}
}
function Verify-Map([string]$Folder,$Map){
  foreach($entry in $Map.PSObject.Properties){
    if([IO.Path]::GetFileName($entry.Name) -ne $entry.Name){throw 'Unsafe dependency filename'}
    Verify-Hash (Join-Path $Folder $entry.Name) $entry.Value
  }
}
$p=Read-Json (Join-Path $pilotDir 'run.json')
if($p.kind -ne 'native_campaign_v1' -or $p.status -ne 'completed_provisional_native_campaign' -or $p.events_per_model -ne 500){throw 'Require completed 500/model pilot'}
$checks=[ordered]@{}
foreach($model in @('AK02','SAP22')){
  $response=Join-Path $pilotDir ($model+'/response'); $transport=Join-Path $pilotDir ($model+'/transport')
  $pr=Read-Json (Join-Path $response 'run.json'); $meta=Read-Json (Join-Path $transport 'prepared.json')
  $manifestPath=Join-Path $transport 'stream/manifest.json'; $m=Read-Json $manifestPath
  if($pr.status -ne 'completed_provisional_native_response' -or $pr.model_id -ne $model -or $meta.model_id -ne $model -or $m.model_id -ne $model){throw 'Pilot model/status mismatch'}
  if(($pr.counts.PSObject.Properties['native_failed_groups'] -and $pr.counts.native_failed_groups -ne 0) -or ($pr.counts.PSObject.Properties['readout_rejected'] -and $pr.counts.readout_rejected -ne $pr.counts.rejected)){throw 'Pilot must be clean: native failures are not accepted'}
  if($pr.counts.initial_decays -ne 500 -or $pr.counts.initial_primaries -ne 500 -or $pr.counts.groups -lt 1 -or $pr.counts.accepted+$pr.counts.rejected -ne $pr.counts.groups -or $meta.primary_count -ne 500 -or $m.primary_count -ne 500){throw 'Pilot positive/census check failed'}
  Verify-Hash (Join-Path $response 'run.json') $p.models.PSObject.Properties[$model].Value.response_report_sha256
  foreach($needed in @('readout.jl','readout_demo.json','readout_profiles.jl','native_response.jl','native_stream.jl','native_li_example.jl','replay.jl','run.jl','Project.toml','Manifest.toml')){if(!$pr.source_sha256.PSObject.Properties[$needed]){throw 'Missing recorded consumer dependency'}}
  foreach($needed in @('cs137.py','handoff.py','cryostat_export.cc','cryostat_nominal.json','cryostat-source.json','CMakeLists.txt','pixi.toml','pixi.lock')){if(!$meta.source_sha256.PSObject.Properties[$needed]){throw 'Missing recorded producer dependency'}}
  foreach($needed in @('scalars.jsonl','endpoints.jsonl','truth.jsonl','traces.jsonl','histograms.json','readout-config.json','profile-input.json')){if(!$pr.artifacts.PSObject.Properties[$needed]){throw 'Missing response artifact binding'}}
  Verify-Map $response $pr.artifacts
  Verify-Map (Join-Path $root 'simulation') $pr.source_sha256
  Verify-Map (Join-Path $root 'transport') $meta.source_sha256
  Verify-Map (Join-Path $root 'transport') $m.source_sha256
  Verify-Map $transport $meta.files_sha256
  Verify-Map (Join-Path $root '.local/transport/LBNL') $meta.upstream_sha256
  Verify-Hash (Join-Path $root $Exporter) $meta.exporter_sha256
  Verify-Hash (Join-Path $root 'simulation/native_readout_profile.json') $pr.profile_sha256
  Verify-Hash $manifestPath $pr.input_sha256
  Verify-Hash (Join-Path $transport 'prepared.json') $m.prepared_sha256
  Verify-Hash (Join-Path $transport 'run.json') $m.run_sha256
  Verify-Hash (Join-Path $transport 'truth.lh5') $m.source_lh5_sha256
  Verify-Hash (Join-Path $transport 'geometry.gdml') $m.geometry_sha256
  Verify-Hash (Join-Path $transport 'run.mac') $m.macro_sha256
  foreach($doc in @($pr,$meta,$m)){Verify-Hash (Join-Path $root ('models/'+$model+'.yaml')) $doc.model_sha256}
  foreach($chunk in $m.chunks){if([IO.Path]::GetFileName($chunk.file) -ne $chunk.file){throw 'Unsafe chunk filename'}; Verify-Hash (Join-Path (Join-Path $transport 'stream') $chunk.file) $chunk.sha256}
  $checks[$model]=[ordered]@{initial_decays=500;groups=$pr.counts.groups;accepted=$pr.counts.accepted;artifacts_verified=@($pr.artifacts.PSObject.Properties).Count;consumer_dependencies_verified=@($pr.source_sha256.PSObject.Properties).Count;producer_dependencies_verified=@($meta.source_sha256.PSObject.Properties).Count}
}
[ordered]@{kind='native_pilot_verification_v1';status='passed';pilot_campaign_sha256=(Get-FileHash (Join-Path $pilotDir 'run.json') -Algorithm SHA256).Hash.ToLowerInvariant();previous_launcher_sha256=$p.source_sha256.PSObject.Properties['tools/run_native_campaign.ps1'].Value;verifier_sha256=(Get-FileHash $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant();models=$checks;scope='Recorded project sources, profiles, original models, raw transport, chunks, binary and response artifacts; no new physics/calibration claim'}|ConvertTo-Json -Depth 8
