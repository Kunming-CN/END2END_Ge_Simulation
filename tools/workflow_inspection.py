"""Narrow inspection of a proved-ended first-stage WSL service denial.

This never resumes a failed root, terminates a worker, or releases opaque failure.
OS inventories are filtered in memory; unrelated command lines are not retained.
"""
import os
from pathlib import Path
import re
import subprocess
import scenario_workflow as W

STATE='.local/local-control-v1'
KNOWN_RUN='39ac8d49a95bdae12a5e41d32a56e8abc4f230d63af9b84710d1c7b6af791cdb'
KNOWN_LOG='2c3dc855eb0f8875a7d8bfaf80a7f948ef85a7105336bdd4c66607b93c3f9cf7'
KNOWN_LAUNCH='5ff5f9279978a1aa4e2321f9d72749d245ba417d6d592a1d19db8f254ca2d4a8'
SCIENCE=re.compile(r'julia(?:\.exe)?|remage|pixi(?:\.exe)?|scenario_workflow\.py|scenario_source_portable\.py|scenario-source-portable-build-v1|cryostat_export|cmake(?:\.exe)?|ninja(?:\.exe)?|(?<![A-Za-z0-9_])(?:g\+\+|gcc|cc1plus|collect2|ld)(?:\s|\.exe|$)|scenario_prepare\.py|scenario_transport\.py|gamma_native_example\.(?:py|jl)|native_response|ring_run\.py|km_ring_run\.py|cs137\.py|decay_source\.py|workflow\.sh',re.I)


def recognized(directory):
    r=W.read(directory/'run.json');W.require(r['kind']==W.KIND and r['status']=='failed' and set(r['stages'])=={'geometry'},'Only a first-stage pre-science WSL denial can be released here.')
    stage=r['stages']['geometry'];W.require(stage['status']=='command_exited' and stage['exit_code']==4294967295 and Path(stage['arguments'][0]).name.casefold()=='wsl.exe','The failure is not the recognized WSL service denial.')
    expected=W.stage_commands(directory,r['resolved'],directory.parents[2],{'JULIA_EXE':'not-dispatched'})['geometry']
    W.require(stage['arguments']==expected,'Failed stage arguments differ from the selected geometry dispatch.')
    log=(directory/'geometry.log').read_bytes();text=log.decode('utf-16-le').replace('\ufeff','')
    W.require('Wsl/Service/E_ACCESSDENIED' in text and not (directory/'transport').exists() and
              set(W.inventory(directory))=={'run.json','resolved-config.json','electronics/profile.json','geometry.log'},
              'Scientific output or an unrecognized first-stage diagnostic is present.')
    return r


def capture(job,root):
    directory=W.run_path(job['name'],root)
    try:recognized(directory)
    except (W.ControlError,OSError,ValueError,KeyError,UnicodeError):return
    path=W.safe_path(root,STATE+'/failed-intents/'+job['id']+'.json')
    value={'kind':'workflow_failed_intent_v1','name':job['name'],'dispatch_id':job['id'],
           'driver':job['driver'],'configuration_sha256':job['plan']['configuration_sha256'],'artifacts':W.inventory(directory)}
    W.write(path,value,fresh=True);job['failure_authority_sha256']=W.sha(path)


def authority(job,root):
    directory=W.run_path(job['name'],root)
    if job.get('failure_authority_sha256'):
        path=W.safe_path(root,STATE+'/failed-intents/'+job['id']+'.json')
        W.require(W.sha(path)==job['failure_authority_sha256'],'Failed intent authority changed.')
        value=W.read(path)
        W.require(value['dispatch_id']==job['id'] and value['driver']==job['driver'] and
                  value['configuration_sha256']==job['plan']['configuration_sha256'],'Failed intent identity differs.')
    else:
        # One preserved pre-repair attempt has an independently frozen root receipt.
        path=W.safe_path(root,'.local/product-delivery-v1/implementation/M14a1-RESTRICTED-LAUNCH.json')
        W.require(W.sha(path)==KNOWN_LAUNCH and W.sha(directory/'run.json')==KNOWN_RUN and W.sha(directory/'geometry.log')==KNOWN_LOG,
                  'This old failed attempt has no recognized preserved authority.')
        launch=W.read(path);r=W.read(directory/'run.json')
        W.require(launch['browser_selected']['name']==job['name'] and launch['science_calls']==0 and
                  job['driver']==r['supervisor'] and launch['first_stage']['pid']==r['stages']['geometry']['pid'] and
                  launch['first_stage']['process_identity']==r['stages']['geometry']['process_identity'],'Old failed dispatch identity differs.')
        W.require((directory/'resolved-config.json').read_bytes()==W.encoded(job['plan'])+b'\n' and
                  (directory/'electronics/profile.json').read_bytes()==W.encoded(r['resolved']['profile'])+b'\n',
                  'Old failed configuration/profile bytes differ from the preserved dispatch.')
        value={'kind':'workflow_failed_intent_v1','name':job['name'],'dispatch_id':job['id'],'driver':job['driver'],
               'configuration_sha256':job['plan']['configuration_sha256'],'artifacts':W.inventory(directory),
               'recognized_launch_sha256':KNOWN_LAUNCH}
    W.require(value['name']==job['name'] and W.encoded(value['artifacts'])==W.encoded(W.inventory(directory)),'Failed bytes/inventory changed after the recorded intent.')
    return value


def inventories(root,runner=subprocess.run):
    command=['powershell.exe','-NoProfile','-Command',"$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); @(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CreationDate,Name,CommandLine) | ConvertTo-Json -Depth 3 -Compress"]
    win=runner(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,shell=False,
               creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    W.require(win.returncode==0,'Windows process inventory failed; the reservation remains blocked.')
    records=W.decode_json(win.stdout.decode('utf-8-sig'));records=records if type(records) is list else [records]
    W.require(bool(records) and all(type(r.get('ProcessId')) is int and 'CommandLine' in r for r in records),'Windows process inventory is incomplete.')
    relevant=[{'pid':r['ProcessId'],'parent_pid':r['ParentProcessId'],'creation':r['CreationDate'],'scope':'possible_scientific_worker'}
              for r in records if r['ProcessId']!=os.getpid() and SCIENCE.search(r.get('CommandLine') or r.get('Name') or '')]
    linux=runner(['wsl.exe','--distribution','Ubuntu-24.04','--','ps','-eo','pid,ppid,args'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,shell=False,
                 creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    W.require(linux.returncode==0,'WSL process inventory failed; the reservation remains blocked.')
    lines=linux.stdout.decode('utf-8-sig').splitlines();W.require(lines and 'PID' in lines[0] and 'PPID' in lines[0],'WSL process inventory is incomplete.')
    rows=[]
    for line in lines[1:]:
        fields=line.strip().split(None,2);W.require(len(fields)==3 and fields[0].isdigit() and fields[1].isdigit(),'WSL process row is ambiguous.')
        if SCIENCE.search(fields[2]):rows.append({'pid':int(fields[0]),'parent_pid':int(fields[1]),'scope':'possible_scientific_worker'})
    W.require(not relevant and not rows,'A possible scientific worker remains active; no reservation was released.')
    return {'windows_succeeded':True,'linux_succeeded':True,'windows_process_count':len(records),
            'linux_process_count':len(lines)-1,'relevant_windows_workers':relevant,'relevant_linux_workers':rows,'checked_utc':W.utc()}


def inspect_failure(job,root,probe=inventories):
    directory=W.run_path(job['name'],root);value=authority(job,root);r=recognized(directory)
    W.require(W.encoded(r['resolved'])==W.encoded(job['plan']['resolved']),'Failed plan changed.')
    stage=r['stages']['geometry'];driver={'pid':stage['pid'],'identity':stage['process_identity']}
    W.require(W.identity_ended(job['driver']) and W.identity_ended(driver),'Failed driver or stage identity is live or unknown.')
    quiescence=probe(root)
    W.require(quiescence['windows_succeeded'] and quiescence['linux_succeeded'] and not quiescence['relevant_windows_workers'] and not quiescence['relevant_linux_workers'],'Full quiescence checks did not pass.')
    W.require(W.encoded(value['artifacts'])==W.encoded(W.inventory(directory)),'Failed artifacts changed during inspection.')
    path=W.safe_path(root,STATE+'/inspected-failures/'+job['name']+'.json')
    record={'kind':'workflow_inspected_pre_science_failure_v1','name':job['name'],'dispatch_id':job['id'],
            'authority':value,'stage_driver':driver,'quiescence':quiescence,'science_calls':0,'retired_utc':W.utc(),
            'action':'A different unused output name may run. This failed root remains immutable and cannot resume.'}
    W.write(path,record,fresh=True);return W.sha(path)


def verified_retirement(directory,root):
    path=W.safe_path(root,STATE+'/inspected-failures/'+directory.name+'.json')
    if not path.exists():return False
    saved=W.read(W.safe_path(root,STATE+'/workflow-jobs.json'))
    job=next((j for j in saved['jobs'] if j['name']==directory.name),None)
    W.require(job and job['status']=='inspected_failure' and W.sha(path)==job.get('inspection_sha256'),'Inspected-failure authority is not bound to the owned reservation.')
    value=W.read(path);recognized(directory);authority(job,root)
    W.require(value['kind']=='workflow_inspected_pre_science_failure_v1' and value['dispatch_id']==job['id'] and
              W.encoded(value['authority']['artifacts'])==W.encoded(W.inventory(directory)) and
              W.identity_ended(job['driver']) and W.identity_ended(value['stage_driver']),'Failed retirement bytes or worker identities changed.')
    return True
