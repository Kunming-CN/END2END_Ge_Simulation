"""Replay completed GeGI signal stores into a new, resumable derivative.

This entry point cannot start Geant4, Julia, fields or injections. It reads
sealed originals through SQLite mode=ro. Source/group truth is retained only
in an identity envelope outside the reconstruction allowlist.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import zlib
import gegi_event_store as S
import gegi_signal_reconstruction as R
import gegi_calibration_admission as A

KIND = 'gegi_saved_reconstruction_v3'
ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('tools/gegi_saved_reconstruction.py', 'tools/gegi_signal_reconstruction.py',
           'tools/gegi_event_store.py', 'tools/gegi_imaging.py',
           'tools/gegi_calibration_admission.py', 'tools/scenario_workflow.py')
SOURCES += ('tools/gegi_signal_recovery.py',)


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(',', ':')).encode()+b'\n'


def write(path, value):
    temp = Path(str(path)+'.tmp')
    temp.write_bytes(encoded(value)); os.replace(temp, path)


def sources():
    return {ref: sha(ROOT/ref) for ref in SOURCES}


def calibration_inventory(bank):
    if bank is None:
        return {}
    refs={'depth-calibration.json','identity.json','depth-diagnostics.json'}
    for pixel in bank.table['pixels'].values():
        refs.update(row['record_ref'] for row in pixel.get('rows',[]))
    refs.update(row['record_ref'] for row in read(bank.root/'depth-diagnostics.json')['rows'])
    inventory={}
    for ref in sorted(refs):
        path=bank.root/ref
        if path.is_symlink() or not path.resolve().is_relative_to(bank.root):
            raise ValueError('Linked or escaped calibration input')
        inventory[ref]=sha(path)
    return inventory


def sealed_chunks(campaign):
    campaign = Path(campaign).resolve(); complete = read(campaign/'COMPLETE.json')
    if complete['status'] not in ('completed', 'completed_with_native_failures'):
        raise ValueError('Original campaign is incomplete')
    records = []
    for path in (campaign/'chunks').glob('*/b*/DONE.json'):
        if path.is_symlink() or not path.resolve().is_relative_to(campaign):
            raise ValueError('Linked or escaped original chunk')
        done = read(path); index = done['identity']['chunk_index']
        if complete['chunks'].get(str(index)) != sha(path):
            raise ValueError('Chunk seal differs from original COMPLETE')
        records.append((index, path, done))
    records.sort(key=lambda r:r[0])
    if len(records) != len(complete['chunks']) or len({r[0] for r in records}) != len(records):
        raise ValueError('Incomplete or duplicate chunk census')
    return complete, records


def native_arrays(db, event):
    if event['native_signals'] is None:
        if event['channels'] is not None or event['status'] != 'native_failed':
            raise ValueError('Unknown native failure/null contract')
        return None
    native, cache = {}, {}
    for cid, refs in event['native_signals'].items():
        native[int(cid)] = {}
        for name, ref in refs.items():
            digest = ref['sha256']
            if digest not in cache:
                row = db.execute('SELECT count,value FROM arrays WHERE digest=?',(digest,)).fetchone()
                if row is None or row[0] != ref['count']:
                    raise ValueError('Missing native array or changed count')
                cache[digest] = S.unpack_array(digest, *row)
            native[int(cid)][name] = cache[digest]
    if set(native) != set(range(1,35)):
        raise ValueError('Native channel census is not34')
    return native


def scalar_checks(event, recipe):
    """Fixed electronics identities; never change energies or acceptances."""
    if event['channels'] is None:
        return {'channels': 0, 'native_failed': 1}
    channels = event['channels']
    if {c['contact_id'] for c in channels} != set(range(1,35)) or len(channels) != 34:
        raise ValueError('Scalar channel census changed')
    cal = recipe['electronics_calibration']; checked = 0
    for c in channels:
        if c['wiring_factor'] not in (-1,1) or c['final_wired_induced_keV'] != c['wiring_factor']*c['final_induced_keV']:
            raise ValueError('Signed fixed wiring changed')
        if not c['current_balance']['passed']:
            raise ValueError('Original charge/current accounting failed')
        expected = (c['adc_code']+.5)*cal['adc_lsb_V']/cal['volts_per_keV']
        if c['accepted'] and abs(expected-c['reconstructed_energy_keV']) > 1e-8:
            raise ValueError('Fixed per-channel ADC gain changed')
        checked += 1
    return {'channels': checked, 'native_failed': 0}


def process(campaign, calibration, output, *, resume=False):
    started=time.perf_counter(); campaign=Path(campaign).resolve(); output=Path(output).resolve()
    if output == campaign or output.is_relative_to(campaign):
        raise ValueError('Derivative must be outside immutable campaign')
    complete,chunks=sealed_chunks(campaign); frozen=sources()
    admission=A.campaign(campaign,calibration) if calibration else None
    bank=R.TemplateBank(calibration) if calibration else None
    calibration_pins=calibration_inventory(bank)
    identity={'kind':KIND,'campaign_complete_sha256':sha(campaign/'COMPLETE.json'),
        'calibration_sha256':bank.sha256 if bank else None,'source_sha256':frozen,
        'calibration_admission':admission,
        'calibration_inventory_sha256':hashlib.sha256(encoded(calibration_pins)).hexdigest(),
        'algorithm_scope':'All original nonzero groups, source/truth-blind conditional signal hypotheses; no photopeak truth gate',
        'new_radiation_calls':0,'new_native_calls':0,'new_field_calls':0,'new_calibration_calls':0}
    if output.exists():
        if not resume or read(output/'identity.json') != identity:
            raise ValueError('Preserve existing derivative; only resume an identical unfinished recipe')
        if (output/'COMPLETE.json').exists():
            raise ValueError('Derivative already complete; do not repeat it')
    else:
        output.mkdir(parents=True);write(output/'identity.json',identity)
    stop = output/'stop.request'
    if resume and stop.exists():
        if stop.is_symlink():
            raise ValueError('Linked stop request is not owned')
        stop.unlink()
    (output/'chunks').mkdir(exist_ok=True)
    totals=Counter();reasons=Counter();transitions=Counter();manifest=[];bindings={}
    for index, seal, done in chunks:
        dbpath=seal.parent/'events.sqlite';destination=output/'chunks'/f'{index:03d}.jsonl.gz'
        receipt=output/'chunks'/f'{index:03d}.json'
        if stop.exists():
            paused={'kind':KIND,'status':'stopped_saved_reconstruction','chunks':len(manifest),
                    'counts':dict(totals),'elapsed_seconds_this_invocation':time.perf_counter()-started}
            write(output/'progress.json',paused)
            return paused
        if receipt.exists():
            record=read(receipt)
            if record['sha256'] != sha(destination) or record['source_sha256'] != frozen or record['input_store_sha256'] != done['artifacts']['events.sqlite']['sha256']:
                raise ValueError('Saved derivative chunk changed')
        else:
            if destination.exists() or Path(str(destination)+'.pending').exists():
                raise ValueError('Interrupted unsealed derivative retained; inspect before retry')
            before=dbpath.stat();digest=sha(dbpath)
            if digest != done['artifacts']['events.sqlite']['sha256']:
                raise ValueError('Immutable scalar/native store changed')
            count=Counter();reject=Counter();change=Counter();tick=time.perf_counter()
            pending=Path(str(destination)+'.pending')
            with closing(sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True)) as db, gzip.open(pending,'wb') as stream:
                db.execute('PRAGMA query_only=ON')
                for pid,gid,blob,metasha in db.execute('SELECT primary_id,group_id,metadata,metadata_sha256 FROM events ORDER BY primary_id,group_id'):
                    body=zlib.decompress(blob)
                    if hashlib.sha256(body).hexdigest()!=metasha:
                        raise ValueError('Original event metadata changed')
                    event=json.loads(body);check=scalar_checks(event,done['response']['readout_recipe'])
                    native=native_arrays(db,event)
                    # The only reconstruction input is the module's explicit observable allowlist.
                    observed=R.observables(event,native,done['response']['readout_recipe']['channels'])
                    result=R.reconstruct_observables(observed,bank)
                    result.pop('limitations',None);result.pop('independent_diagnostic_envelope',None)
                    original={'chunk_index':index,'raw_primary_id':pid,'pulse_group_id':gid,
                        'campaign_initial_id':event['campaign_initial_offset']+pid,
                        'source_group':event['source_group'],'metadata_sha256':metasha}
                    record={'original_identity':original,'native_status':event['status'],
                        'legacy_reason':event['reconstruction'].get('reason'),
                        'legacy_status':event['reconstruction']['status'],
                        'legacy_readout':event['readout_summary'],'reconstruction':result}
                    stream.write(encoded(record));count['pulse_groups']+=1;count['scalar_channels_checked']+=check['channels']
                    count['native_failed_groups']+=check['native_failed']
                    count['conditional_candidate_groups']+=bool(result['candidates'])
                    count['conditional_candidates']+=len(result['candidates'])
                    count['validated_recovered_groups']+=bool(result['imaging_accepted'])
                    count['spectroscopy_groups']+=bool(result['signal_use']['spectroscopy']['accepted'])
                    count['spectroscopy_only_groups']+=result['signal_use']['category']=='spectroscopy_only'
                    reject[result.get('reason') or result['status']]+=1
                    if result['candidates']:
                        change[event['reconstruction'].get('reason') or event['reconstruction']['status']]+=1
            after=dbpath.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or sources()!=frozen:
                raise ValueError('Original data or implementation changed while deriving')
            os.replace(pending,destination)
            record={'chunk_index':index,'input_store_sha256':digest,'source_sha256':frozen,'sha256':sha(destination),
                'counts':dict(count),'reasons':dict(reject),'legacy_candidate_transitions':dict(change),
                'template_bindings':dict(bank.bindings) if bank else {},
                'elapsed_seconds':time.perf_counter()-tick}
            write(receipt,record)
        totals.update(record['counts']);reasons.update(record['reasons']);transitions.update(record['legacy_candidate_transitions'])
        bindings.update(record['template_bindings'])
        manifest.append({'chunk_index':index,'receipt_sha256':sha(receipt),'data_sha256':record['sha256']})
        write(output/'progress.json',{'kind':KIND,'status':'running_saved_reconstruction','chunks':len(manifest),
            'counts':dict(totals),'elapsed_seconds_this_invocation':time.perf_counter()-started})
        print(json.dumps({'chunks':len(manifest),'groups':totals['pulse_groups'],'candidates':totals['conditional_candidate_groups']}),flush=True)
    expected=sum(g['pulse_groups'] for g in complete['groups'].values())
    if totals['pulse_groups']!=expected or sources()!=frozen or calibration_inventory(bank)!=calibration_pins:
        raise ValueError('Final group census or implementation changed')
    summary={**identity,'status':'completed_conditional_reconstruction','counts':dict(totals),'reasons':dict(reasons),
        'legacy_candidate_transitions':dict(transitions),'original_initial_denominators':complete['groups'],
        'limitations':R.LIMITATIONS,'independent_diagnostic_envelope':bank.calibrate_discrepancy() if bank else None,
        'template_bindings':bindings,'calibration_input_sha256':calibration_pins,
        'elapsed_seconds_this_invocation':time.perf_counter()-started}
    write(output/'summary.json',summary)
    write(output/'COMPLETE.json',{'kind':KIND,'status':summary['status'],'chunks':manifest,
        'summary_sha256':sha(output/'summary.json'),'identity_sha256':sha(output/'identity.json')})
    write(output/'progress.json',{'status':summary['status'],'chunks':len(chunks),'counts':dict(totals)})
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--campaign',required=True)
    p.add_argument('--calibration');p.add_argument('--output',required=True);p.add_argument('--resume',action='store_true')
    a=p.parse_args();process(a.campaign,a.calibration,a.output,resume=a.resume)
