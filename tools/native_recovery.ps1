# Metadata-only child launch/recovery contract. No runtime lookup or child launch.
. (Join-Path $PSScriptRoot 'electronics_execution.ps1')
function Write-RCImmutable([string]$Root,[string]$Path,[byte[]]$Bytes){
  $path=Resolve-NRPath $Root $Path
  if(Test-Path -LiteralPath $path){
    Assert-NR ([Convert]::ToBase64String([IO.File]::ReadAllBytes($path)) -ceq [Convert]::ToBase64String($Bytes)) ('Immutable recovery evidence differs: '+$path)
    return
  }
  $stream=[IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try{$stream.Write($Bytes,0,$Bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
}
function ConvertTo-RCBytes($Value){return ,([Text.Encoding]::UTF8.GetBytes(($Value|ConvertTo-Json -Depth 40)+"`n"))}
function Get-RCArguments([string]$Output,[string]$Model,[string]$Profile,[bool]$Custom){
  $args=@('--startup-file=no','--threads=2','--project=simulation','simulation/native_response_guarded.jl','--input',($Output+'/'+$Model+'/transport/stream/manifest.json'),'--output',($Output+'/'+$Model+'/response'),'--seed','2609261','--parcels','16','--trace-examples','4','--charge-csv','examples','--native-failure-policy','record')
  if($Custom){$args+=@('--profile',$Profile)}
  return $args
}
function Get-RCContext($Parent){
  $context=[ordered]@{}
  foreach($key in @('kind','events_per_model','seed','detectors','scenario','source_sha256','pilot','pilot_verification','started_utc','electronics','recovery_contract','native_executable')){$context[$key]=$Parent.$key}
  return $context
}
function Get-RCIntent([string]$Root,[string]$Output,[string]$Model,$Parent,[string]$Profile){
  $dir=Join-Path $Root ($Output+'/'+$Model+'/transport')
  $bindings=[ordered]@{}
  foreach($file in @('prepared.json','run.json','stream/manifest.json')){$bindings[$file]=Get-NRHash $Root (Join-Path $dir $file)}
  $profileDoc=Read-NRJson $Root (Join-Path $Root $Profile)
  $config=Resolve-ESConfiguration $Root $profileDoc;$config.expected_primary_count=$Parent.events_per_model
  $consumer=[ordered]@{}
  foreach($name in Get-NRConsumerSources){$consumer[$name]=Get-NRHash $Root (Join-Path $Root ('simulation/'+$name))}
  Assert-NR ($Parent.native_executable -is [string] -and [IO.Path]::IsPathRooted($Parent.native_executable)) 'Missing recorded native executable'
  return [ordered]@{schema_version=1;kind='guarded_native_launch_intent_v1';output=($Output+'/'+$Model+'/response');campaign=$Output;detector=$Model
    events=$Parent.events_per_model;radiation_seed=$Parent.seed;guard_required=$true
    executable=$Parent.native_executable;working_directory=$Root;arguments=@(Get-RCArguments $Output $Model $Profile ($null -ne $Parent.electronics))
    profile_path=$Profile;profile_sha256=(Get-NRHash $Root (Join-Path $Root $Profile));configuration=$config
    transport_sha256=$bindings;consumer_source_sha256=$consumer;model_sha256=(Get-NRHash $Root (Join-Path $Root ('models/'+$Model+'.yaml')));context=(Get-RCContext $Parent)}
}
function New-RCIntent([string]$Root,[string]$Output,[string]$Model,$Parent,[string]$Profile){
  $dir=Join-Path $Root ($Output+'/'+$Model)
  Assert-NR (!(Test-Path -LiteralPath (Join-Path $dir 'response'))) 'Cannot authorize an existing response retroactively'
  $intent=Get-RCIntent $Root $Output $Model $Parent $Profile
  $path=Join-Path $dir 'native-launch-intent.json'
  Assert-NR (!(Test-Path -LiteralPath $path)) 'Existing launch intent forbids another native attempt; inspect/recover'
  Write-RCImmutable $Root $path (ConvertTo-RCBytes $intent)
  return [ordered]@{path=($Output+'/'+$Model+'/native-launch-intent.json');sha256=(Get-NRHash $Root $path)}
}
function Get-RCModelBinding([string]$Root,[string]$Response,$Child){
  return [ordered]@{status=$Child.status;counts=$Child.counts;response_report_sha256=(Get-NRHash $Root (Join-Path $Response 'run.json'))
    native_seconds=$Child.native_drift_and_charge_seconds;electronics_seconds=$Child.electronics_seconds
    response_wall_seconds=$Child.solve_replay_readout_export_wall_seconds;process_peak_rss_bytes=$Child.process_peak_rss_bytes}
}
function Test-RCCampaign([string]$Root,[string]$Output,$Parent){
  $dir=Join-Path $Root $Output
  Assert-NREqual $Parent.kind 'native_campaign_v1' 'campaign kind'
  Assert-NRInteger $Parent.events_per_model 'campaign events' 1
  Assert-NR ($Parent.events_per_model -in @(20,500,10000)) 'Unsupported campaign census'
  Assert-NRInteger $Parent.seed 'radiation seed' 1
  $models=@($Parent.detectors)
  Assert-NR ($models.Count -ge 1 -and $models.Count -le 2 -and @($models|Select-Object -Unique).Count -eq $models.Count) 'Invalid campaign detectors'
  foreach($m in $models){Assert-NR ($m -cin @('AK02','SAP22')) 'Unsupported campaign detector'}
  Assert-NR ($Parent.models -is [pscustomobject]) 'Missing parent model map'
  foreach($m in $Parent.models.PSObject.Properties.Name){Assert-NR ($models -ccontains $m) 'Unexpected parent model'}
  $terminal=$Parent.status -cin @('completed_provisional_native_campaign','completed_with_native_failures')
  Assert-NR ($terminal -or $Parent.status -cin @('running','failed','nonterminal_recovered')) 'Unsupported parent status'
  $scenario='';if($null -ne $Parent.scenario){
    Assert-NREqual $Parent.scenario.file 'scenarios/lbnl-cs137.json' 'scenario file'
    Assert-NREqual $Parent.scenario.id 'lbnl-cs137' 'scenario id';$scenario=$Parent.scenario.file
    Test-NRHash $Root (Join-Path $Root $scenario) $Parent.scenario.sha256
  }
  $exporter=Get-NRRecordedExporter $Parent
  $profile=Get-EERecordedProfile $Root $dir $Parent
  $sources=Get-NRCampaignSources $exporter $scenario ($null -ne $Parent.electronics)
  Assert-NREqual @($Parent.source_sha256.PSObject.Properties.Name|Sort-Object) @($sources|Sort-Object) 'campaign source inventory'
  foreach($f in $sources){Test-NRHash $Root (Join-Path $Root $f) $Parent.source_sha256.$f}
  $pending=[ordered]@{};$verified=[ordered]@{};$unfinished=@()
  if($null -ne $Parent.child_launches){
    foreach($m in $Parent.child_launches.PSObject.Properties.Name){Assert-NR ($models -ccontains $m) 'Unexpected launch detector'}
  }
  foreach($m in $models){
    $response=Resolve-NRPath $Root (Join-Path $dir ($m+'/response'))
    $bound=$Parent.models.PSObject.Properties[$m]
    $launch=if($null -ne $Parent.child_launches){$Parent.child_launches.PSObject.Properties[$m]}else{$null}
    if($null -eq $bound -and $null -eq $launch -and !(Test-Path -LiteralPath $response)){
      Assert-NR (!(Test-Path -LiteralPath (Join-Path $dir ($m+'/native-launch-intent.json')))) 'Intent exists without durable parent binding'
      $unfinished+=,$m;continue
    }
    $t=Join-Path $dir ($m+'/transport')
    [void](Test-NRPrepared $Root $t $m $Parent.events_per_model $Parent.seed $exporter)
    [void](Test-NRTransport $Root $t);[void](Test-NRStream $Root $t $m $Parent.events_per_model)
    if($null -eq $bound){
      Assert-NREqual $Parent.recovery_contract 'guarded_child_intent_v1' 'prelaunch recovery contract'
      Assert-NR ($null -ne $launch) 'Missing prelaunch intent; legacy orphan cannot be adopted'
      $path=$Output+'/'+$m+'/native-launch-intent.json'
      Assert-NREqual $launch.Value.path $path 'intent path'
      Test-NRHash $Root (Join-Path $Root $path) $launch.Value.sha256
      Assert-NREqual (Read-NRJson $Root (Join-Path $Root $path)) (Get-RCIntent $Root $Output $m $Parent $profile) 'independent launch intent'
    }
    $expected=if($null -ne $bound){[string]$bound.Value.response_report_sha256}else{Get-NRHash $Root (Join-Path $response 'run.json')}
    $child=Test-NRResponse -Root $Root -Directory $response -Model $m -Events $Parent.events_per_model -Manifest (Join-Path $t 'stream/manifest.json') -ExpectedReportHash $expected -NewChild:($null -eq $bound) -ExpectedProfilePath $profile
    $binding=Get-RCModelBinding $Root $response $child
    Assert-NREqual $binding.response_report_sha256 $expected 'stable final child receipt'
    if($null -ne $bound){Assert-NREqual $bound.Value $binding 'strict parent child binding'}else{$pending[$m]=$binding}
    $verified[$m]=$binding.response_report_sha256
  }
  if($terminal){
    Assert-NR ($pending.Count -eq 0 -and $unfinished.Count -eq 0) 'Terminal parent lacks bound children'
    $failed=0;$rejected=0;foreach($m in $models){$failed+=$Parent.models.$m.counts.native_failed_groups;$rejected+=$Parent.models.$m.counts.readout_rejected}
    Assert-NREqual $Parent.native_failed_groups $failed 'parent failures';Assert-NREqual $Parent.readout_rejected $rejected 'parent rejections'
    Assert-NREqual ($Parent.status -ceq 'completed_with_native_failures') ($failed -gt 0) 'parent terminal status'
  }
  return [pscustomobject]@{pending=$pending;verified=$verified;unfinished=$unfinished;terminal=$terminal}
}
function Get-RCAfter($Before,$Check){
  $after=$Before|ConvertTo-Json -Depth 40|ConvertFrom-Json
  foreach($m in $Check.pending.Keys){$after.models|Add-Member -NotePropertyName $m -NotePropertyValue $Check.pending[$m]}
  # Stage and event histories, original error/timestamps and measured times remain exact.
  if($Check.unfinished.Count -gt 0){$after.status='nonterminal_recovered'}else{
    $failed=0;$rejected=0;foreach($m in $after.detectors){$failed+=$after.models.$m.counts.native_failed_groups;$rejected+=$after.models.$m.counts.readout_rejected}
    $after.status=if($failed -gt 0){'completed_with_native_failures'}else{'completed_provisional_native_campaign'}
    foreach($pair in @(@('native_failure_policy','record'),@('native_failed_groups',$failed),@('readout_rejected',$rejected))){$after|Add-Member -NotePropertyName $pair[0] -NotePropertyValue $pair[1] -Force}
  }
  return $after
}
function Invoke-NativeRecovery([string]$Root,[string]$Output,[switch]$DryRun){
  $dir=Resolve-NRPath $Root (Join-Path $Root $Output)
  Assert-NR ($Output -cmatch '^\.local/runs/[A-Za-z0-9_-]+$') 'Recovery requires a named saved run'
  $lock=Resolve-NRPath $Root (Join-Path $dir 'run.lock')
  Assert-NR (Test-Path -LiteralPath $lock -PathType Leaf) 'Existing run lock missing; no recovery writes'
  $lease=[IO.File]::Open($lock,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None)
  try{
    $file=Resolve-NRPath $Root (Join-Path $dir 'run.json');$currentHash=Get-NRHash $Root $file
    $currentBytes=[IO.File]::ReadAllBytes($file);$parent=Read-NRJson $Root $file
    $transactionRoot=Resolve-NRPath $Root (Join-Path $dir 'recovery-v1');$active=@()
    if(Test-Path -LiteralPath $transactionRoot){
      foreach($folder in Get-ChildItem -LiteralPath $transactionRoot -Force){
        [void](Resolve-NRPath $Root $folder.FullName)
        Assert-NR ($folder.PSIsContainer -and $folder.Name -cmatch '^[0-9a-f]{64}$') 'Unexpected transaction evidence'
        $commit=Join-Path $folder.FullName 'COMMITTED.json'
        if(!(Test-Path -LiteralPath $commit)){$active+=,$folder.FullName}else{
          $prior=Read-NRJson $Root (Join-Path $folder.FullName 'PREPARED.json')
          Assert-ESKeys $prior @('kind','schema_version','state','campaign','before_sha256','after_sha256','children_sha256')
          Assert-NREqual $prior.schema_version 1 'committed transaction version'
          Assert-NREqual $prior.kind 'native_parent_recovery_v1' 'committed transaction kind'
          Assert-NREqual $prior.state 'PREPARED' 'immutable prepared state'
          Assert-NREqual $prior.campaign $Output 'committed campaign'
          Assert-NREqual $folder.Name $prior.before_sha256 'committed directory'
          Test-NRHash $Root (Join-Path $folder.FullName 'parent-before.json') $prior.before_sha256
          Test-NRHash $Root (Join-Path $folder.FullName 'parent-after.json') $prior.after_sha256
          Test-NRHash $Root (Join-Path $folder.FullName 'parent-replaced-before.json') $prior.before_sha256
          Assert-NREqual (Read-NRJson $Root $commit) ([ordered]@{kind='native_parent_recovery_commit_v1';state='COMMITTED';prepared_sha256=(Get-NRHash $Root (Join-Path $folder.FullName 'PREPARED.json'));parent_sha256=$prior.after_sha256}) 'commit marker'
          Assert-NR ($currentHash -cne $prior.before_sha256) 'Committed marker contradicts before-parent'
        }
      }
    }
    Assert-NR ($active.Count -le 1) 'Multiple unfinished recovery transactions'
    $tx=if($active.Count){$active[0]}else{Join-Path $transactionRoot $currentHash}
    $preparedPath=Join-Path $tx 'PREPARED.json';$beforePath=Join-Path $tx 'parent-before.json';$afterPath=Join-Path $tx 'parent-after.json'
    $state='new';$receipt=$null
    if(Test-Path -LiteralPath $preparedPath){
      $receipt=Read-NRJson $Root $preparedPath
      Assert-ESKeys $receipt @('kind','schema_version','state','campaign','before_sha256','after_sha256','children_sha256')
      Assert-NREqual $receipt.schema_version 1 'transaction version'
      Assert-NREqual $receipt.kind 'native_parent_recovery_v1' 'transaction kind';Assert-NREqual $receipt.state 'PREPARED' 'transaction state'
      Assert-NREqual $receipt.campaign $Output 'transaction campaign'
      Assert-NREqual (Split-Path $tx -Leaf) $receipt.before_sha256 'transaction directory'
      Test-NRHash $Root $beforePath $receipt.before_sha256;Test-NRHash $Root $afterPath $receipt.after_sha256
      Assert-NR ($currentHash -ceq $receipt.before_sha256 -or $currentHash -ceq $receipt.after_sha256) 'Parent matches neither transaction boundary'
      $state=if($currentHash -ceq $receipt.after_sha256){'parent_after'}else{'parent_before'}
      $before=Read-NRJson $Root $beforePath
      $check=Test-RCCampaign $Root $Output $before
      Assert-NREqual $receipt.children_sha256 $check.verified 'verified transaction children'
      Assert-NREqual (Read-NRJson $Root $afterPath) (Get-RCAfter $before $check) 'staged parent semantics'
      if($state -eq 'parent_after'){
        Test-NRHash $Root (Join-Path $tx 'parent-replaced-before.json') $receipt.before_sha256
        [void](Test-RCCampaign $Root $Output $parent)
      }
    }else{
      if($active.Count){Assert-NREqual (Split-Path $tx -Leaf) $currentHash 'unfinished staging parent'}
      $check=Test-RCCampaign $Root $Output $parent
      if($check.terminal){Test-NRHash $Root $file $currentHash;return [ordered]@{status='terminal_noop';transaction_state='none';parent_status=$parent.status;simulations_started=0;runtime_readiness_checked=$false;files_written=0}}
      Assert-NR ($check.pending.Count -gt 0) 'No completed pending native child to recover'
      $afterBytes=ConvertTo-RCBytes (Get-RCAfter $parent $check)
      foreach($pair in @(@($beforePath,$currentBytes),@($afterPath,$afterBytes))){
        if(Test-Path -LiteralPath $pair[0]){Assert-NR ([Convert]::ToBase64String([IO.File]::ReadAllBytes($pair[0])) -ceq [Convert]::ToBase64String($pair[1])) 'Incomplete/different staging evidence; preserved without repair'}
      }
      if($active.Count){
        $state=if(Test-Path -LiteralPath $afterPath){'after_parent_staged'}elseif(Test-Path -LiteralPath $beforePath){'before_parent_preserved'}else{'empty_transaction'}
      }
    }
    Test-NRHash $Root $file $currentHash
    if($DryRun){return [ordered]@{status='recoverable';transaction_state=$state;pending_detectors=@($check.pending.Keys);unfinished_detectors=@($check.unfinished);simulations_started=0;runtime_readiness_checked=$false;files_written=0}}
    if($null -eq $receipt){
      [void][IO.Directory]::CreateDirectory($tx)
      Write-RCImmutable $Root $beforePath $currentBytes
      Write-RCImmutable $Root $afterPath $afterBytes
      $receipt=[ordered]@{kind='native_parent_recovery_v1';schema_version=1;state='PREPARED';campaign=$Output
        before_sha256=(Get-NRHash $Root $beforePath);after_sha256=(Get-NRHash $Root $afterPath);children_sha256=$check.verified}
      Write-RCImmutable $Root $preparedPath (ConvertTo-RCBytes $receipt)
    }
    if($state -ne 'parent_after'){
      # Revalidate immediately before mutation, including every existing binding.
      $recheck=Test-RCCampaign $Root $Output (Read-NRJson $Root $beforePath)
      Assert-NREqual $recheck.verified $receipt.children_sha256 'stable children before commit'
      Test-NRHash $Root $file $receipt.before_sha256
      Test-NRHash $Root $afterPath $receipt.after_sha256
      $replacement=Join-Path $tx 'parent-replacement.json'
      Write-RCImmutable $Root $replacement ([IO.File]::ReadAllBytes($afterPath))
      $backup=Join-Path $tx 'parent-replaced-before.json'
      Assert-NR (!(Test-Path -LiteralPath $backup)) 'Replacement backup already exists at before-parent boundary'
      [IO.File]::Replace($replacement,$file,$backup,$true)
    }
    Test-NRHash $Root $file $receipt.after_sha256
    $marker=[ordered]@{kind='native_parent_recovery_commit_v1';state='COMMITTED';prepared_sha256=(Get-NRHash $Root $preparedPath);parent_sha256=$receipt.after_sha256}
    Write-RCImmutable $Root (Join-Path $tx 'COMMITTED.json') (ConvertTo-RCBytes $marker)
    return [ordered]@{status='recovered';transaction_state='COMMITTED';parent_status=(Read-NRJson $Root $file).status;recovered_detectors=@($check.pending.Keys);unfinished_detectors=@($check.unfinished);simulations_started=0;runtime_readiness_checked=$false}
  }finally{$lease.Dispose()}
}
