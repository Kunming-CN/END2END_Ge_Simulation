# Low-code Windows entry for reviewed local scenarios. No installs or physics hidden here.
param(
  [ValidateSet('menu','check','setup','run','resume','open','status','detectors','inspect')][string]$Action='menu',
  [ValidateSet('lbnl-cs137')][string]$Scenario='lbnl-cs137',
  [ValidateSet('smoke','demo','larger')][string]$Preset='demo',
  [ValidateSet('AK02','SAP22','both')][string]$Detector='both',
  [ValidatePattern('^[A-Za-z0-9_-]*$')][string]$Name='',
  [ValidateRange(1,2147483647)][int]$Seed=26092631,
  [string]$Pilot='',
  [switch]$BuildExporter,
  [switch]$Open,
  [switch]$Json,
  [switch]$DryRun
)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')); Set-Location $root
. (Join-Path $PSScriptRoot 'native_run_validation.ps1')
$scenarioFile=Join-Path $root ('scenarios/'+$Scenario+'.json')
if(!(Test-Path $scenarioFile -PathType Leaf)){throw 'Scenario definition missing'}
$scenarioConfig=Get-Content $scenarioFile -Raw|ConvertFrom-Json
if($scenarioConfig.schema_version -ne 1 -or $scenarioConfig.id -ne $Scenario -or $scenarioConfig.adapter -ne 'lbnl_cs137_v1'){throw 'Unsupported scenario schema/adapter'}
$canonicalRefs=[ordered]@{geometry_ref='transport/cryostat_nominal.json';upstream_manifest_ref='transport/cryostat-source.json';readout_profile_ref='simulation/native_readout_profile.json'}
foreach($p in $canonicalRefs.GetEnumerator()){if([string]$scenarioConfig.($p.Key) -ne $p.Value){throw "Scenario reference is not supported by adapter v1: $($p.Key)"}}
$scenarioSha256=(Get-FileHash $scenarioFile -Algorithm SHA256).Hash.ToLowerInvariant()
function Resolve-ProjectFile([string]$Relative){
  if($Relative -notmatch '^[A-Za-z0-9_.\/-]+$'){throw 'Unsafe scenario reference'}
  $full=[IO.Path]::GetFullPath((Join-Path $root $Relative))
  if(!$full.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Scenario reference escapes project'}
  if(!(Test-Path $full -PathType Leaf)){throw "Scenario dependency missing: $Relative"}
  return $full
}
$geometry=Resolve-ProjectFile $scenarioConfig.geometry_ref
$upstreamManifest=Resolve-ProjectFile $scenarioConfig.upstream_manifest_ref
$profile=Resolve-ProjectFile $scenarioConfig.readout_profile_ref
$exporterRel='.local/m2a/cs137-build-v1/cryostat_export'
$exporter=Join-Path $root $exporterRel
$runsRoot=Join-Path $root '.local/runs'
function Model-List([string]$Choice){
  if($Choice -eq 'both'){return @('AK02','SAP22')}
  if($scenarioConfig.detectors -notcontains $Choice){throw 'Detector is not reviewed for this scenario'}
  return @($Choice)
}
function Events-For([string]$Which){
  $p=$scenarioConfig.presets.PSObject.Properties[$Which]
  if(!$p){throw 'Unknown preset'}
  return [int]$p.Value.events_per_detector
}
function Hash-Lower([string]$Path){(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function Check-Upstream {
  $m=Get-Content $upstreamManifest -Raw|ConvertFrom-Json; $missing=@();$changed=@()
  foreach($f in $m.files){
    $path=Join-Path $root ('.local/transport/LBNL/'+$f.name)
    if(!(Test-Path $path -PathType Leaf)){$missing+=,$f.name}
    elseif((Get-Item $path).Length -ne $f.bytes -or (Hash-Lower $path) -ne $f.sha256){$changed+=,$f.name}
  }
  [pscustomobject]@{ok=($missing.Count -eq 0 -and $changed.Count -eq 0);missing=$missing;changed=$changed;expected_path='.local/transport/LBNL';source=$m.repository;commit=$m.commit}
}
function Check-Setup {
  $up=Check-Upstream; $j=Get-Command julia -ErrorAction SilentlyContinue; $wsl=Get-Command wsl.exe -ErrorAction SilentlyContinue
  $savedEap=$ErrorActionPreference; $ErrorActionPreference='SilentlyContinue'
  $juliaEnv=''; $juliaReady=$false
  if($null -ne $j){
    $juliaEnv=(& $j.Source --startup-file=no --project=simulation -e 'using SolidStateDetectors, JSON, Unitful; print(string(VERSION,"|",pkgversion(SolidStateDetectors),"|",pkgversion(JSON),"|",pkgversion(Unitful)))' 2>$null | Out-String).Trim()
    $juliaReady=($LASTEXITCODE -eq 0 -and $juliaEnv -eq '1.13.0|0.11.8|1.9.0|1.29.0')
  }
  $ubuntu=$false; if($null -ne $wsl){& $wsl.Source -d Ubuntu-24.04 -- true *> $null; $ubuntu=($LASTEXITCODE -eq 0)}
  $transport=$false; if($ubuntu){& (Join-Path $root 'transport/Run.cmd') versions *> $null; $transport=($LASTEXITCODE -eq 0)}
  $ErrorActionPreference=$savedEap
  [pscustomobject]@{
    scenario=$scenarioConfig.id; scenario_sha256=$scenarioSha256; check_mode='read_only_no_install'
    julia_executable=($null -ne $j); julia_environment=$juliaEnv; julia_ready=$juliaReady
    wsl_ubuntu_24=$ubuntu; locked_transport=$transport; upstream=$up.ok; exporter=(Test-Path $exporter -PathType Leaf)
    free_GB=[math]::Round((Get-PSDrive -Name ([IO.Path]::GetPathRoot($root).TrimEnd('\').TrimEnd(':'))).Free/1GB,1)
    geometry_sha256=Hash-Lower $geometry; readout_profile_sha256=Hash-Lower $profile
    ready=($juliaReady -and $ubuntu -and $transport -and $up.ok -and (Test-Path $exporter -PathType Leaf))
  }
}
function Show-SetupStatus {
  $s=Check-Setup
  $s|Format-List
  if(!$s.ready){
    Write-Host 'Setup is incomplete. No packages or source files were installed by this check.' -ForegroundColor Yellow
    if(!$s.julia_ready){Write-Host 'Julia: follow simulation/README.md to install the pinned Julia environment.'}
    if(!$s.wsl_ubuntu_24 -or !$s.locked_transport){Write-Host 'Transport: follow transport/README.md for Ubuntu-24.04 and explicit pixi install --locked.'}
    if(!$s.upstream){Write-Host 'LBNL inputs: use the pinned repository, commit and file hashes in transport/cryostat-source.json; place exact files in .local/transport/LBNL.'}
    if(!$s.exporter){Write-Host 'After dependencies and LBNL inputs are ready, run: .\Run.cmd setup -BuildExporter'}
    exit 2
  }
}
function Build-Exporter {
  $up=Check-Upstream
  if(!$up.ok){throw "Pinned LBNL source files are missing/changed. Place exact originals in $($up.expected_path); see transport/cryostat-source.json before building."}
  & (Join-Path $root 'transport/Run.cmd') cmake -S . -B ../.local/m2a/cs137-build-v1 -G Ninja
  if($LASTEXITCODE -ne 0){throw 'CMake configure failed'}
  & (Join-Path $root 'transport/Run.cmd') cmake --build ../.local/m2a/cs137-build-v1 --target cryostat_export --parallel 2
  if($LASTEXITCODE -ne 0 -or !(Test-Path $exporter -PathType Leaf)){throw 'cryostat_export build failed'}
}
function Require-Ready {
  $s=Check-Setup
  if(!$s.ready){
    $s|Format-List
    $up=Check-Upstream
    if(!$up.ok){Write-Host "LBNL originals are not redistributed. See transport/cryostat-source.json and the pinned upstream commit." -ForegroundColor Yellow}
    throw 'Setup is incomplete. Run: .\Run.cmd setup'
  }
  return $s
}
function Run-Path([string]$RunName){
  if($RunName -cnotmatch '^[A-Za-z0-9_-]+$'){throw 'A valid run name is required (letters, digits, underscore or hyphen).'}
  $p=[IO.Path]::GetFullPath((Join-Path $runsRoot $RunName))
  if(!$p.StartsWith($runsRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Run path escapes .local/runs'}
  $scan=$p
  while($scan -and $scan.Length -ge $root.Length){
    if((Test-Path -LiteralPath $scan) -and ((Get-Item -LiteralPath $scan -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw "Linked run path refused: $scan"}
    if($scan -eq $root){break}; $scan=[IO.Path]::GetDirectoryName($scan)
  }
  return $p
}
function Write-RunIndex([string]$Directory){
  $run=Resolve-NRPath $root (Join-Path $Directory 'run.json'); if(!(Test-Path -LiteralPath $run -PathType Leaf)){return}
  $r=Get-Content $run -Raw|ConvertFrom-Json
  $links=@()
  foreach($m in @($r.models.PSObject.Properties.Name)){
    Assert-NR ($m -cin @('AK02','SAP22')) 'Unsupported saved result detector'
    $summary=Resolve-NRPath $root (Join-Path $Directory ($m+'/response/summary.html'))
    if(Test-Path $summary -PathType Leaf){$links+=('<li><a href="'+$m+'/response/summary.html">'+$m+' response summary</a></li>')}
  }
  $status=[System.Net.WebUtility]::HtmlEncode([string]$r.status)
  $body='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>END2END local run</title><style>body{font:16px/1.5 system-ui;max-width:850px;margin:auto;padding:22px}code{background:#eee;padding:2px 5px}</style><h1>'+[System.Net.WebUtility]::HtmlEncode($scenarioConfig.title)+'</h1><p>Status: <strong>'+$status+'</strong></p><p>Saved local results; synthetic electronics and nominal geometry.</p><ul>'+($links -join '')+'</ul><p><code>run.json</code> preserves configuration, stages, hashes and failures.</p>'
  [IO.File]::WriteAllText((Resolve-NRPath $root (Join-Path $Directory 'index.html')),$body)
}
function Show-DetectorChoices {
  $file=Join-Path $root 'scenarios/detector-capabilities.json'
  $caps=Get-Content -LiteralPath $file -Raw|ConvertFrom-Json
  $catalog=Get-Content -LiteralPath (Join-Path $root 'models/catalog.json') -Raw|ConvertFrom-Json
  if($caps.schema_version -ne 1 -or $caps.scenario_id -ne $Scenario){throw 'Unsupported capability registry'}
  $names=@($caps.detectors|ForEach-Object {$_.model_id})
  if($names.Count -ne $catalog.detectors.Count -or ($names|Select-Object -Unique).Count -ne $names.Count){throw 'Capability catalog coverage mismatch'}
  foreach($entry in $caps.detectors){
    $model=@($catalog.detectors|Where-Object {$_.id -ceq $entry.model_id})
    if($model.Count -ne 1 -or $model[0].model_sha256 -ne $entry.model_sha256 -or $model[0].contacts.Count -ne $entry.contact_count){throw 'Capability model identity mismatch'}
    if($entry.lbnl_execution_implemented -isnot [bool]){throw 'Capability execution flag must be a Boolean'}
    if([bool]$entry.lbnl_execution_implemented -ne ($scenarioConfig.detectors -contains $entry.model_id)){throw 'Capability/scenario execution mismatch'}
    if($entry.lbnl_execution_implemented){
      if($entry.geometry_adapter -ne $scenarioConfig.adapter -or @($entry.readout_contacts).Count -ne 1 -or $entry.readout_contacts[0] -ne $model[0].readout_contact_id){throw 'Capability adapter/readout mismatch'}
    }elseif($null -ne $entry.geometry_adapter -or @($entry.readout_contacts).Count -ne 0){throw 'Unsupported model has execution metadata'}
  }
  $caps.detectors|ForEach-Object {[pscustomobject]@{
    Detector=$_.model_id;Contacts=$_.contact_count
    ViewerPage=(Test-Path -LiteralPath (Join-Path $root ('docs/detectors/'+$_.model_id+'/geometry.html')))
    LBNL=if($_.lbnl_execution_implemented){'implemented'}else{'not integrated'}
  }}|Format-Table -AutoSize
  Write-Host '.\Run.cmd run -Detector AK02 -Preset demo  (or SAP22; both runs separate cases)'
  Write-Host 'Viewing a model does not establish cryostat fit or full-chain support.'
  Write-Host 'Positive uninstrumented launcher and clean-machine reproduction remain unvalidated.'
}

function Show-Status {
  if(!(Test-Path $runsRoot)){Write-Host 'No .local/runs yet.';return}
  $rows=@()
  foreach($f in Get-ChildItem $runsRoot -Directory -ErrorAction SilentlyContinue){
    $run=Join-Path $f.FullName 'run.json'; if(!(Test-Path $run)){continue}
    try{$r=Read-NRJson $root $run;$rows+=[pscustomobject]@{Name=$f.Name;Status=$r.status;Events=$r.events_per_model;Detectors=(@($r.models.PSObject.Properties.Name)-join ',')}}catch{$rows+=[pscustomobject]@{Name=$f.Name;Status='unreadable_or_blocked';Events=$null;Detectors='inspect saved files'}}
  }
  $rows|Sort-Object Name -Descending|Select-Object -First 20|Format-Table -AutoSize
}
function Open-Run([string]$RunName){
  $dir=Run-Path $RunName; Write-RunIndex $dir; $page=Resolve-NRPath $root (Join-Path $dir 'index.html')
  if(!(Test-Path $page)){throw 'Run has no viewable receipt yet'}
  Start-Process $page
}
function New-Name {
  $stamp=Get-Date -Format 'yyyyMMdd-HHmmss'; return "$Scenario-$Preset-$Detector-$stamp"
}
function Inspect-Run([string]$RunName){
  $dir=Run-Path $RunName
  & (Join-Path $PSScriptRoot 'inspect_native_run.ps1') -Directory $dir -Json:$Json
}
function Invoke-Run([bool]$ResumeMode){
  if($ResumeMode -and $DryRun){Inspect-Run $Name;return}
  $ready=Require-Ready
  if(!$Name){if($ResumeMode){throw 'Resume requires -Name'}else{$script:Name=New-Name}}
  $dir=Run-Path $Name; $rel='.local/runs/'+$Name
  if($ResumeMode){
    $runFile=Join-Path $dir 'run.json'; if(!(Test-Path $runFile -PathType Leaf)){throw 'Resume requires a saved run.json'}
    $saved=Get-Content $runFile -Raw|ConvertFrom-Json
    if($saved.kind -ne 'native_campaign_v1'){throw 'Saved run kind is not supported'}
    $events=[int]$saved.events_per_model; if($events -notin @(20,500,10000)){throw 'Saved event preset is not supported by this launcher'}
    $runSeed=[int]$saved.seed
    $models=if($saved.PSObject.Properties['detectors']){@($saved.detectors)}else{@($saved.models.PSObject.Properties.Name)}
    if($models.Count -lt 1 -or @($models|Where-Object {$scenarioConfig.detectors -notcontains $_}).Count -gt 0){throw 'Saved detector set is not reviewed for this scenario'}
    $pilotArg=if($saved.PSObject.Properties['pilot']){[string]$saved.pilot}else{''}
  }else{
    $models=Model-List $Detector; $events=Events-For $Preset; $runSeed=$Seed; $pilotArg=$Pilot
    if($Preset -eq 'larger' -and !$pilotArg){throw 'The larger preset requires -Pilot pointing to a verified 500/model run'}
  }
  $args=@{Output=$rel;Events=$events;Seed=$runSeed;Models=$models;Exporter=$exporterRel;ScenarioFile='scenarios/lbnl-cs137.json'}
  if($pilotArg){$args.Pilot=$pilotArg}; if($ResumeMode){$args.Resume=$true}
  Write-Host "Scenario: $($scenarioConfig.title)"; Write-Host "Detectors: $($models -join ', ')"; Write-Host "Initial decays per detector: $events"; Write-Host "Output: $rel"
  if($ResumeMode){Write-Host 'Resume uses the saved run configuration; command-line preset/detector/seed overrides are ignored.'}
  if($DryRun){Write-Host 'DRY RUN: setup/config resolved; no simulation started.';return}
  & (Join-Path $root 'tools/run_native_campaign.ps1') @args
  if($LASTEXITCODE -and $LASTEXITCODE -ne 0){throw 'Campaign driver failed'}
  Write-RunIndex $dir
  if($Open){Open-Run $Name}
}
function Menu {
  Write-Host '';Write-Host 'END2END Ge Simulation';Write-Host '1) Check setup';Write-Host '2) Setup / build local exporter';Write-Host '3) New LBNL Cs137 run';Write-Host '4) Resume a saved run (inspect first)';Write-Host '5) Open saved results';Write-Host '6) List run status';Write-Host '7) Detector capabilities';Write-Host '8) Inspect saved run - no calculation';Write-Host 'Q) Quit'
  $choice=(Read-Host 'Select').Trim().ToUpperInvariant()
  switch($choice){
    '1'{$script:Action='check'}
    '2'{$script:Action='setup'}
    '3'{$script:Action='run';$p=(Read-Host 'Preset smoke/demo/larger [demo]').Trim();if($p){$script:Preset=$p};$d=(Read-Host 'Detector AK02/SAP22/both [both]').Trim();if($d){$script:Detector=$d};$n=(Read-Host 'Run name [auto]').Trim();if($n){$script:Name=$n}}
    '4'{$script:Action='resume';$script:Name=(Read-Host 'Saved run name').Trim()}
    '5'{$script:Action='open';$script:Name=(Read-Host 'Saved run name').Trim()}
    '6'{$script:Action='status'}
    '7'{$script:Action='detectors'}
    '8'{$script:Action='inspect';$script:Name=(Read-Host 'Saved run name').Trim()}
    'Q'{return $false}
    default{throw 'Invalid menu choice'}
  }; return $true
}
if($Action -eq 'menu'){if(!(Menu)){return}}
if($Action -cnotin @('check','setup','run','resume','open','status','detectors','inspect')){throw 'Unsupported action'}
if($Preset -cnotin @('smoke','demo','larger') -or $Detector -cnotin @('AK02','SAP22','both') -or $Name -cnotmatch '^[A-Za-z0-9_-]*$'){throw 'Invalid menu parameter'}
if($Json -and $Action -ne 'inspect'){throw '-Json is supported only for inspect'}
if($Action -eq 'inspect' -and ($BuildExporter -or $Open -or $DryRun -or $Pilot -or $PSBoundParameters.ContainsKey('Preset') -or $PSBoundParameters.ContainsKey('Detector') -or $PSBoundParameters.ContainsKey('Seed'))){throw 'inspect does not accept setup/run/open options'}
switch($Action){
  'check'{Show-SetupStatus}
  'setup'{if($BuildExporter -or !(Test-Path $exporter)){Build-Exporter};Show-SetupStatus}
  'run'{Invoke-Run $false}
  'resume'{Invoke-Run $true; if($DryRun){exit $LASTEXITCODE}}
  'open'{Open-Run $Name}
  'status'{Show-Status}
  'detectors'{Show-DetectorChoices}
  'inspect'{Inspect-Run $Name;exit $LASTEXITCODE}
}
