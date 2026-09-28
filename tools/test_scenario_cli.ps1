$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Check([bool]$Value,[string]$Message){if(!$Value){throw $Message}}
foreach($name in @('tools/scenario_cli.ps1','tools/run_native_campaign.ps1','tools/verify_native_pilot.ps1')){
  [void][scriptblock]::Create((Get-Content (Join-Path $root $name) -Raw))
}
$scenarioPath=Join-Path $root 'scenarios/lbnl-cs137.json'
$s=Get-Content $scenarioPath -Raw|ConvertFrom-Json
Check ($s.schema_version -eq 1 -and $s.id -eq 'lbnl-cs137' -and $s.adapter -eq 'lbnl_cs137_v1') 'Scenario identity'
Check ((@($s.detectors) -join ',') -eq 'AK02,SAP22') 'Reviewed detector set'
Check ($s.presets.smoke.events_per_detector -eq 20) 'Smoke preset'
Check ($s.presets.demo.events_per_detector -eq 500) 'Demo preset'
Check ($s.presets.larger.events_per_detector -eq 10000) 'Larger preset'
Check ($s.geometry_ref -eq 'transport/cryostat_nominal.json') 'Canonical geometry reference'
Check ($s.upstream_manifest_ref -eq 'transport/cryostat-source.json') 'Canonical upstream manifest reference'
Check ($s.readout_profile_ref -eq 'simulation/native_readout_profile.json') 'Canonical readout profile reference'
$raw=Get-Content $scenarioPath -Raw
Check ($raw -notmatch '(?i)"(?:command|executable|shell)"\s*:') 'Scenario must not contain executable command fields'
foreach($ref in @($s.geometry_ref,$s.upstream_manifest_ref,$s.readout_profile_ref)){
  Check ($ref -match '^[A-Za-z0-9_.\/-]+$') 'Unsafe scenario reference'
  $full=[IO.Path]::GetFullPath((Join-Path $root $ref))
  Check ($full.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) 'Reference escapes project'
  Check (Test-Path $full -PathType Leaf) ('Missing scenario reference: '+$ref)
}
$cmd=Get-Content (Join-Path $root 'Run.cmd') -Raw
Check ($cmd -match 'scenario_cli\.ps1') 'Root Run.cmd does not select scenario CLI'
Check ($cmd -match 'exit /b %RC%') 'Root Run.cmd must propagate launcher exit code'
Check ($cmd -notmatch '(?i)curl|Invoke-WebRequest|winget|choco') 'Run.cmd must not install/fetch software'
$result=[ordered]@{
  status='passed'; scenario=$s.id; detectors=@($s.detectors)
  presets=[ordered]@{smoke=20;demo=500;larger=10000}
  scripts_parsed=3; command_fields_in_scenario=$false
}
$result|ConvertTo-Json -Depth 5
