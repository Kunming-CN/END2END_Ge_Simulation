# Shared saved-electronics execution binding. Dot sourcing performs no runtime work.
. (Join-Path $PSScriptRoot 'electronics_settings.ps1')
function Test-EEFeasibility($Configuration){
  $dt=2; $last=99998
  $n=[math]::Ceiling(20000*[double]$Configuration.shaping_tau_us/$dt)+1
  Assert-NR ((Test-NRFinite $n) -and $n -ge 3 -and $n -le 500000 -and $n -le $Configuration.max_samples_per_event -and ($n-1)*$dt -le $Configuration.max_window_ns) 'Injection calibration exceeds numerical sample/window bounds'
  Assert-NR ($Configuration.max_window_ns -ge 100000 -and $Configuration.max_samples_per_event -ge 50000) 'Isolated window exceeds numerical bounds'
  if($null -ne $Configuration.peak_gate_start_ns){
    $lo=[math]::Ceiling($Configuration.peak_gate_start_ns/$dt)
    $hi=[math]::Floor($Configuration.peak_gate_end_ns/$dt)
    Assert-NR ($lo -ge 0 -and $hi -gt $lo -and $hi*$dt -le $last) 'Peak gate must contain at least two numerical sample points within 0..99998 ns'
  }
  return [pscustomobject]@{time_step_ns=2;isolated_horizon_ns=100000;last_sample_ns=99998;calibration_samples=$n;scope='Arithmetic sample/window feasibility; numerical injection calibration remains part of native execution, not experimental validation'}
}
function Get-EESelection([string]$Root,[string]$Bundle){
  Assert-NR ($Bundle -cmatch '^\.local/electronics-profiles/[A-Za-z0-9_-]{1,64}\.json$') 'Select an existing saved bundle under .local/electronics-profiles/'
  $sources=Get-ESSources $Root
  $selected=Get-ESInput $Root $Bundle $sources
  Assert-NREqual $selected.input.kind 'electronics_settings_bundle_v1' 'Saved bundle required for execution'
  $feasibility=Test-EEFeasibility $selected.configuration
  Assert-NREqual (Get-ESSources $Root) $sources 'Stable execution selection sources'
  foreach($item in $selected.input_bindings){Test-NRHash $Root (Resolve-ESPath $Root $item.path) $item.sha256}
  return [pscustomobject]@{selected=$selected;sources=$sources;feasibility=$feasibility}
}
function Write-EEBytes([string]$Root,[string]$Relative,[byte[]]$Bytes){
  $dest=Resolve-ESPath $Root $Relative
  Assert-NR (!(Test-Path -LiteralPath $dest)) 'Execution snapshot replacement forbidden'
  [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($dest))
  $dest=Resolve-ESPath $Root $Relative
  $temp=$dest+'.pending-'+[Guid]::NewGuid().ToString('N')
  $stream=[IO.File]::Open($temp,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try{$stream.Write($Bytes,0,$Bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
  [IO.File]::Move($temp,$dest)
}
function New-EEBinding([string]$Root,[string]$Output,$Selection){
  # Copy exact original bytes at their original relative paths in a small mirror.
  # No receipt is rebased: Get-ESInput reads the original lineage inside this mirror.
  $mirror=$Output+'/electronics/inputs';$profilePath=$Output+'/electronics/profile.json'
  $copies=[ordered]@{}
  foreach($item in $Selection.selected.input_bindings){$copies[$item.path]=$item.sha256}
  foreach($item in $Selection.sources.PSObject.Properties){$copies[$item.Name]=$item.Value}
  foreach($item in $copies.GetEnumerator()){
    $source=Resolve-ESPath $Root $item.Key;Test-NRHash $Root $source $item.Value
    Write-EEBytes $Root ($mirror+'/'+$item.Key) ([IO.File]::ReadAllBytes($source))
    Test-NRHash $Root $source $item.Value
    Test-NRHash $Root (Resolve-ESPath $Root ($mirror+'/'+$item.Key)) $item.Value
  }
  Write-EEBytes $Root $profilePath ([Text.Encoding]::UTF8.GetBytes(($Selection.selected.profile|ConvertTo-Json -Depth 16)+"`n"))
  $binding=[pscustomobject]@{schema_version=1;kind='saved_electronics_execution_v1';input=$Selection.selected.input;inputs_root=$mirror
    copies_sha256=[pscustomobject]$copies;sources_sha256=$Selection.sources;profile_path=$profilePath
    profile_sha256=(Get-NRHash $Root (Resolve-ESPath $Root $profilePath));configuration=$Selection.selected.configuration
    physics_sha256=$Selection.selected.physics_sha256;feasibility=$Selection.feasibility}
  [void](Test-EEBinding $Root $Output $binding)
  return $binding
}
function Test-EEBinding([string]$Root,[string]$Output,$Binding){
  Assert-ESKeys $Binding @('schema_version','kind','input','inputs_root','copies_sha256','sources_sha256','profile_path','profile_sha256','configuration','physics_sha256','feasibility')
  Assert-NRInteger $Binding.schema_version 'execution binding schema' 1
  Assert-NREqual $Binding.schema_version 1 'execution binding schema'
  Assert-NREqual $Binding.kind 'saved_electronics_execution_v1' 'execution binding kind'
  Assert-NREqual $Binding.inputs_root ($Output+'/electronics/inputs') 'execution inputs location'
  Assert-NREqual $Binding.profile_path ($Output+'/electronics/profile.json') 'execution profile location'
  $mirror=Resolve-ESPath $Root $Binding.inputs_root
  $sources=Get-ESSources $Root
  Assert-NREqual $Binding.sources_sha256 $sources 'Execution settings source compatibility (never rebase old receipts)'
  Assert-NREqual (Get-ESSources $mirror) $sources 'Copied source inventory'
  $selected=Get-EESelection $mirror $Binding.input.path
  Assert-NREqual $Binding.input $selected.selected.input 'Original saved bundle lineage'
  $wanted=[ordered]@{}
  foreach($item in $selected.selected.input_bindings){$wanted[$item.path]=$item.sha256}
  foreach($item in $sources.PSObject.Properties){$wanted[$item.Name]=$item.Value}
  Assert-NREqual $Binding.copies_sha256 $wanted 'Exact execution copy inventory'
  foreach($item in $wanted.GetEnumerator()){Test-NRHash $Root (Resolve-ESPath $mirror $item.Key) $item.Value}
  Test-NRHash $Root (Resolve-ESPath $Root $Binding.profile_path) $Binding.profile_sha256
  Assert-NREqual (Read-ESFile $Root $Binding.profile_path).value $selected.selected.profile 'Standalone profile versus saved bundle'
  Assert-NREqual $Binding.configuration $selected.selected.configuration 'Parent independent effective configuration'
  Assert-NREqual $Binding.physics_sha256 $selected.selected.physics_sha256 'Parent effective configuration hash'
  Assert-NREqual $Binding.feasibility $selected.feasibility 'Parent numerical feasibility'
  return $Binding.profile_path
}
function Get-EERecordedProfile([string]$Root,[string]$Directory,$Receipt){
  $output=(Resolve-NRPath $Root $Directory).Substring($Root.TrimEnd('\','/').Length+1).Replace('\','/')
  if($Receipt.PSObject.Properties['electronics']){return Test-EEBinding $Root $output $Receipt.electronics}
  Assert-NR (!(Test-Path -LiteralPath (Join-Path $Directory 'electronics'))) 'Saved electronics directory lacks parent binding'
  Assert-NR (!$Receipt.source_sha256.PSObject.Properties['simulation/readout_demo.json']) 'Custom source inventory lacks parent electronics binding'
  return 'simulation/native_readout_profile.json'
}
