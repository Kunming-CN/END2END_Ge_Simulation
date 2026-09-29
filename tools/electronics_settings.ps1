# PowerShell-only editor/preflight. Dot sourcing defines functions; it does no IO.
# Profile constraints are shared with saved-run inspection (Test-NRProfile).
. (Join-Path $PSScriptRoot 'native_run_validation.ps1')
$script:ESDefault='simulation/native_readout_profile.json'
$script:ESBase='simulation/readout_demo.json'
$script:ESUnits=[ordered]@{
  shaping_tau_us='us';gain='V/V';threshold_V='V';adc_bits='bits';adc_full_scale_V='V'
  feedback_capacitance_pF='pF';feedback_tau_us='us';pole_zero_tau_us='us'
  peak_policy='enum';peak_gate_start_ns='ns since readout trace origin (or null)';peak_gate_end_ns='ns since readout trace origin (or null)'
}
function Resolve-ESPath([string]$Root,[string]$Relative){
  Assert-NR ($Relative -cmatch '^[A-Za-z0-9_.-]+([/\\][A-Za-z0-9_.-]+)*$') 'Use a project-relative path without spaces, links, streams or wildcards'
  foreach($part in ($Relative -split '[/\\]')){
    Assert-NR ($part -notin @('.','..') -and !$part.EndsWith('.') -and $part -notmatch '^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])($|\.)') 'Unsafe path component'
  }
  # Reject path redirection (including every ancestor). Ordinary NTFS hard links
  # do not redirect traversal: synced checkouts may use them for pending uploads.
  # Inputs are read/hash-checked only and output names are never replaced.
  return Resolve-NRPath $Root (Join-Path $Root $Relative)
}
function Assert-ESKeys($Value,[string[]]$Keys){
  Assert-NR ($Value -is [pscustomobject]) 'Expected JSON object'
  Assert-NREqual @($Value.PSObject.Properties.Name|Sort-Object -CaseSensitive) @($Keys|Sort-Object -CaseSensitive) 'Exact JSON keys'
}
# Windows PowerShell's JSON parser accepts duplicate members and some non-JSON
# syntax. This small data-only reader rejects them before ConvertFrom-Json sees
# string tokens. Arrays are intentionally not part of this profile/bundle schema.
function ConvertFrom-ESJson([string]$Text){
  $state=@{text=$Text;pos=0;depth=0}
  function Read-ESValue($st){
    $st.depth++; Assert-NR ($st.depth -le 16) 'JSON nesting limit'
    try{
      while($st.pos -lt $st.text.Length -and [char]::IsWhiteSpace($st.text[$st.pos])){$st.pos++}
      Assert-NR ($st.pos -lt $st.text.Length) 'Incomplete JSON'
      if($st.text[$st.pos] -eq '{'){
        $st.pos++;$map=[ordered]@{}
        while($true){
          while($st.pos -lt $st.text.Length -and [char]::IsWhiteSpace($st.text[$st.pos])){$st.pos++}
          Assert-NR ($st.pos -lt $st.text.Length) 'Incomplete object'
          if($st.text[$st.pos] -eq '}'){$st.pos++;return [pscustomobject]$map}
          Assert-NR ($st.text[$st.pos] -eq '"') 'Expected JSON member'
          $key=Read-ESValue $st
          Assert-NR (!$map.Contains($key)) 'Duplicate/case-aliased JSON member'
          while($st.pos -lt $st.text.Length -and [char]::IsWhiteSpace($st.text[$st.pos])){$st.pos++}
          Assert-NR ($st.pos -lt $st.text.Length -and $st.text[$st.pos] -eq ':') 'Expected colon';$st.pos++
          $map[$key]=Read-ESValue $st
          while($st.pos -lt $st.text.Length -and [char]::IsWhiteSpace($st.text[$st.pos])){$st.pos++}
          Assert-NR ($st.pos -lt $st.text.Length) 'Incomplete object'
          if($st.text[$st.pos] -eq '}'){$st.pos++;return [pscustomobject]$map}
          Assert-NR ($st.text[$st.pos] -eq ',') 'Expected comma';$st.pos++
          while($st.pos -lt $st.text.Length -and [char]::IsWhiteSpace($st.text[$st.pos])){$st.pos++}
          Assert-NR ($st.pos -lt $st.text.Length -and $st.text[$st.pos] -eq '"') 'Trailing comma/invalid member'
        }
      }
      # Match with a start offset (\G anchors to that offset).
      $rx=[regex]'\G(?:"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"|true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)'
      $match=$rx.Match($st.text,$st.pos)
      Assert-NR $match.Success 'Invalid JSON value (arrays/nonfinite tokens are not supported)'
      $token=$match.Value;$st.pos+=$token.Length
      if($token.StartsWith('"')){return ConvertFrom-Json -InputObject $token}
      if($token -ceq 'null'){return $null};if($token -ceq 'true'){return $true};if($token -ceq 'false'){return $false}
      if($token -notmatch '[.eE]'){return [long]::Parse($token,[Globalization.CultureInfo]::InvariantCulture)}
      $number=[double]::Parse($token,[Globalization.CultureInfo]::InvariantCulture)
      Assert-NR (Test-NRFinite $number) 'Nonfinite JSON number';return $number
    }finally{$st.depth--}
  }
  $result=Read-ESValue $state
  Assert-NR ($state.text.Substring($state.pos).Trim().Length -eq 0) 'Trailing JSON content'
  return $result
}
function Read-ESFile([string]$Root,[string]$Relative){
  $path=Resolve-ESPath $Root $Relative
  Assert-NR (Test-Path -LiteralPath $path -PathType Leaf) 'Settings input missing'
  Assert-NR ((Get-Item -LiteralPath $path).Length -le 131072) 'Settings input exceeds 128 KiB'
  $before=Get-NRHash $Root $path
  $value=ConvertFrom-ESJson ([IO.File]::ReadAllText($path))
  Test-NRHash $Root $path $before
  return [pscustomobject]@{value=$value;sha256=$before;path=$Relative.Replace('\','/')}
}
function Get-ESSources([string]$Root){
  $map=[ordered]@{}
  foreach($rel in @('tools/electronics_settings.ps1','tools/native_run_validation.ps1','tools/scenario_cli.ps1','simulation/readout_profiles.jl','simulation/readout.jl','simulation/Project.toml','simulation/Manifest.toml',$script:ESBase,$script:ESDefault)){
    $map[$rel]=Get-NRHash $Root (Resolve-ESPath $Root $rel)
  }
  Assert-NREqual $map[$script:ESBase] '33eb64724736c78852795ea001889759152ffefc22de9c4db6815fd1aaf8ee9e' 'Frozen readout defaults'
  Assert-NREqual $map[$script:ESDefault] '7556e6e77d6c21e76e1a4eabb69b2b26875517252c083c88b6eb6a80502ef6e6' 'Frozen native profile'
  return [pscustomobject]$map
}
function Resolve-ESConfiguration([string]$Root,$Electronics){
  Test-NRProfile $Electronics
  Assert-NR ($Electronics.kind -is [string] -and $Electronics.settings.peak_policy -is [string]) 'Profile kind/policy must be strings'
  # Preserve every inherited setting. Only schema2's declared removal/census
  # substitutions and all eleven profile overrides are made, just as in Julia.
  $base=(Read-ESFile $Root $script:ESBase).value
  $config=[ordered]@{}
  foreach($p in $base.PSObject.Properties){if($p.Name -cne 'max_total_samples'){$config[$p.Name]=$p.Value}}
  $config.schema_version=2;$config.expected_primary_count=$null
  foreach($p in $Electronics.settings.PSObject.Properties){$config[$p.Name]=$p.Value}
  return [pscustomobject]$config
}
function Get-ESPhysicsHash($Configuration){
  $sha=[Security.Cryptography.SHA256]::Create()
  try{return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes((ConvertTo-NRCanonical $Configuration))))).Replace('-','').ToLowerInvariant()}
  finally{$sha.Dispose()}
}
function Get-ESInput([string]$Root,[string]$Relative,$Sources,
  [System.Collections.Generic.HashSet[string]]$Visited=$null,[int]$Depth=0){
  Assert-NR ($Depth -ge 0 -and $Depth -lt 16) 'Provenance chain exceeds 16 input files'
  if($null -eq $Visited){$Visited=[System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)}
  $resolved=Resolve-ESPath $Root $Relative
  Assert-NR ($Visited.Add($resolved)) 'Cyclic settings provenance'
  $read=Read-ESFile $Root $Relative;$data=$read.value;$bindings=@($read)
  if($data.kind -ceq 'electronics_settings_bundle_v1'){
    Assert-ESKeys $data @('schema_version','kind','revision','profile','configuration','physics_sha256','provenance')
    Assert-NRInteger $data.schema_version 'bundle schema' 1;Assert-NREqual $data.schema_version 1 'bundle schema'
    Assert-NRInteger $data.revision 'revision' 1;Assert-NREqual $data.revision 1 'bundle revision'
    Assert-ESKeys $data.provenance @('input','defaults','sources_sha256')
    Assert-ESKeys $data.provenance.input @('path','sha256','schema_version','kind')
    Assert-ESKeys $data.provenance.defaults @('path','sha256','schema_version')
    foreach($entry in @($data.provenance.input,$data.provenance.defaults)){
      Assert-NR ($entry.path -is [string] -and $entry.sha256 -is [string] -and $entry.sha256 -cmatch '^[0-9a-f]{64}$') 'Invalid provenance path/hash type'
      Assert-NRInteger $entry.schema_version 'provenance schema' 1
    }
    Assert-NREqual $data.provenance.sources_sha256 $Sources 'Source bindings (changed source requires inspection; never rebase old saves)'
    Assert-NREqual $data.provenance.defaults ([pscustomobject]@{path=$script:ESBase;sha256=$Sources.($script:ESBase);schema_version=1}) 'Default provenance'
    $prior=Get-ESInput -Root $Root -Relative $data.provenance.input.path -Sources $Sources -Visited $Visited -Depth ($Depth+1)
    Assert-NREqual $prior.input.sha256 $data.provenance.input.sha256 'Input profile binding'
    Assert-NREqual $prior.input.schema_version $data.provenance.input.schema_version 'Input schema'
    Assert-NREqual $prior.input.kind $data.provenance.input.kind 'Input kind'
    $bindings+=@($prior.input_bindings)
    $effective=Resolve-ESConfiguration $Root $data.profile
    foreach($key in @('schema_version','adc_bits','max_samples_per_event','trace_max_points')){
      Assert-NRInteger $data.configuration.$key ('resolved '+$key) 1
    }
    Assert-NR ($data.configuration.require_all_events -is [bool]) 'Resolved selection policy must be Boolean'
    Assert-NREqual $data.configuration $effective 'Independent resolved configuration'
    Assert-NREqual $data.physics_sha256 (Get-ESPhysicsHash $effective) 'Physics hash'
    $electronics=$data.profile
  }else{
    $electronics=$data;$effective=Resolve-ESConfiguration $Root $electronics
  }
  return [pscustomobject]@{input_bindings=$bindings;profile=$electronics;configuration=$effective;physics_sha256=(Get-ESPhysicsHash $effective);input=[pscustomobject]@{path=$read.path;sha256=$read.sha256;schema_version=$data.schema_version;kind=$data.kind}}
}
function Get-ESReuse {
  return [pscustomobject]@{
    dependency_based_theoretical_reuse='Electronics changes alone do not require new radiation, fields or charge. Requires compatible full charge waveforms, complete identities, timing, units and producer settings.'
    artifact_verified_supported_reuse='NOT_CHECKED: settings comparison verifies no run artifacts. Run.cmd inspect checks terminal saved-run compatibility for unchanged canonical settings; it does not authorize electronics replay.'
    electronics_only_replay='NOT_IMPLEMENTED: the coupled response driver does not automatically reuse charge for changed electronics. No comparison calculation is started.'
    custom_profile_execution='NOT_IMPLEMENTED: new runs and resume retain canonical electronics. A canonical pilot cannot authorize changed electronics; no custom-profile pilot matching is implemented.'
  }
}
function Invoke-ElectronicsSettings {
  param([string]$Root,[string]$Mode='interactive',[string]$View='simple',[string]$SettingsFile='',
    [string]$CompareTo='',[string]$SetJson='',[string]$SaveName='', [switch]$AsJson)
  Assert-NR ($Mode -cin @('interactive','show','check','save','compare')) 'Unknown settings mode'
  Assert-NR ($View -cin @('simple','advanced')) 'Unknown settings view'
  Assert-NR (!$AsJson -or $Mode -cne 'interactive') 'Interactive settings cannot emit JSON'
  Assert-NR (!$SetJson -or $Mode -cin @('save','check')) '-SetJson is accepted only by save/check'
  Assert-NR (!$SaveName -or $Mode -cin @('save','interactive')) '-SaveName is accepted only by save/interactive'
  Assert-NR (($Mode -ceq 'compare') -eq [bool]$CompareTo) 'compare requires -CompareTo; other modes forbid it'
  if(!$SettingsFile){$SettingsFile=$script:ESDefault}
  $sources=Get-ESSources $Root;$source=Get-ESInput $Root $SettingsFile $sources
  $edited=ConvertFrom-ESJson (ConvertTo-Json -InputObject $source.profile -Depth 12)
  if($SetJson){
    $patch=ConvertFrom-ESJson $SetJson;Assert-NR ($patch -is [pscustomobject]) 'Edits must be a JSON object'
    foreach($p in $patch.PSObject.Properties){
      Assert-NR ($p.Name -cin @($script:ESUnits.Keys)) ('Unknown setting: '+$p.Name)
      $edited.settings.($p.Name)=$p.Value
    }
  }
  if($Mode -ceq 'interactive'){
    Write-Host 'Electronics settings: saves a configuration only; custom run selection/replay is not implemented.'
    $chosen=Read-Host "View simple/advanced [$View]";if($chosen){$View=$chosen}
    Assert-NR ($View -cin @('simple','advanced')) 'Expected simple or advanced'
    $keys=if($View -ceq 'simple'){@('shaping_tau_us','gain','threshold_V','adc_bits','adc_full_scale_V')}else{@($script:ESUnits.Keys)}
    foreach($key in $keys){
      $display=ConvertTo-NRCanonical $edited.settings.$key
      $answer=Read-Host "$key [$($script:ESUnits[$key])] = $display; Enter keeps, otherwise JSON value"
      if($answer){$edited.settings.$key=ConvertFrom-ESJson $answer}
    }
    if(!$SaveName){$SaveName=Read-Host 'New saved settings name (letters/digits/underscore/hyphen; blank cancels)'}
    if(!$SaveName){Write-Host 'Cancelled; nothing saved.';return}
    $Mode='save'
  }
  $config=Resolve-ESConfiguration $Root $edited;$physicsHash=Get-ESPhysicsHash $config
  $result=[ordered]@{status='valid_configuration_only';profile=$edited;configuration=$config;physics_sha256=$physicsHash;units=[pscustomobject]$script:ESUnits;reuse=(Get-ESReuse)
    preflight='Schema/configuration only; runtime calibration and pulse processing NOT_RUN. Gates use ns since readout trace origin (each Cs137 pulse-group origin), maximum 99998 ns for the current 100000 ns isolated window/2 ns analog grid. No waveform ADC sampling-frequency setting.'}
  if($Mode -ceq 'compare'){
    $other=Get-ESInput $Root $CompareTo $sources
    $changes=[ordered]@{}
    foreach($key in $script:ESUnits.Keys){if((ConvertTo-NRCanonical $edited.settings.$key) -cne (ConvertTo-NRCanonical $other.profile.settings.$key)){
      $changes[$key]=[pscustomobject]@{from=$edited.settings.$key;to=$other.profile.settings.$key;unit=$script:ESUnits[$key]}
    }}
    $result.comparison=[pscustomobject]@{same_physics=($physicsHash -ceq $other.physics_sha256);other_physics_sha256=$other.physics_sha256;changes=[pscustomobject]$changes}
  }
  # Detect inputs/source changes during this operation before any save is made.
  Assert-NREqual (Get-ESSources $Root) $sources 'Stable settings sources'
  foreach($binding in $source.input_bindings){Test-NRHash $Root (Resolve-ESPath $Root $binding.path) $binding.sha256}
  if($Mode -ceq 'compare'){foreach($binding in $other.input_bindings){Test-NRHash $Root (Resolve-ESPath $Root $binding.path) $binding.sha256}}
  if($Mode -ceq 'save'){
    Assert-NR (@($source.input_bindings).Count -lt 16) 'Saving would exceed 16 provenance input files; no file created'
    Assert-NR ($SaveName -cmatch '^[A-Za-z0-9_-]{1,64}$') 'Supply -SaveName (1..64 letters/digits/underscore/hyphen)'
    $edited.name=$SaveName
    $destination=Resolve-ESPath $Root ('.local/electronics-profiles/'+$SaveName+'.json')
    Assert-NR (!(Test-Path -LiteralPath $destination)) 'Saved settings already exist; overwrite is forbidden'
    $bundle=[ordered]@{schema_version=1;kind='electronics_settings_bundle_v1';revision=1;profile=$edited;configuration=$config;physics_sha256=$physicsHash
      provenance=[ordered]@{input=$source.input;defaults=[ordered]@{path=$script:ESBase;sha256=$sources.($script:ESBase);schema_version=1};sources_sha256=$sources}}
    $bytes=[Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $bundle -Depth 16)+"`n")
    $parent=[IO.Path]::GetDirectoryName($destination)
    [void][IO.Directory]::CreateDirectory($parent)
    # Recheck links immediately before writing; Move is atomic and refuses an
    # existing destination. Failed staging files are retained, never overwritten.
    $null=Resolve-ESPath $Root ('.local/electronics-profiles/'+$SaveName+'.json')
    $staged=$destination+'.pending-'+[Guid]::NewGuid().ToString('N')
    $stream=[IO.File]::Open($staged,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try{$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
    [IO.File]::Move($staged,$destination)
    $result.status='saved_configuration_only';$result.saved_path='.local/electronics-profiles/'+$SaveName+'.json'
  }
  if($AsJson){[pscustomobject]$result|ConvertTo-Json -Depth 16;return}
  Write-Host $result.status
  $keys=if($View -ceq 'simple'){@('shaping_tau_us','gain','threshold_V','adc_bits','adc_full_scale_V')}else{@($script:ESUnits.Keys)}
  foreach($key in $keys){Write-Host ("{0} = {1} [{2}]" -f $key,(ConvertTo-NRCanonical $edited.settings.$key),$script:ESUnits[$key])}
  if($View -ceq 'advanced'){Write-Host 'Full resolved configuration (inherited limits and injection calibration included):';Write-Host ($config|ConvertTo-Json -Depth 8)}
  Write-Host ('Physics SHA256: '+$physicsHash)
  if($result.Contains('saved_path')){Write-Host ('Saved: '+$result.saved_path)}
  if($result.Contains('comparison')){Write-Host ($result.comparison|ConvertTo-Json -Depth 8)}
  foreach($p in $result.reuse.PSObject.Properties){Write-Host ($p.Name+': '+$p.Value)}
  Write-Host 'Schema/preflight only; no runtime calibration or pulse simulation. Gates are optional ns since readout trace origin (each Cs137 pulse-group origin), limited to 99998 ns by the current 100000 ns isolated window/2 ns analog grid. This grid is not waveform ADC sampling.'
}
