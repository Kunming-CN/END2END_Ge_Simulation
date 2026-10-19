"""Shared v3 reconstruction for existing standalone GeGI native CSV signals.

The native response wrapper calls analyze() before sealing a NEW run. The CLI
reads a completed standalone run into a separate derivative, preserving every
original byte. Neither entry starts radiation, drift, fields or calibration.
"""
from __future__ import annotations
import argparse
from collections import Counter
import copy
from pathlib import Path

import scenario_workflow as W
import gegi_event_store as S
import gegi_signal_reconstruction as R
import gegi_calibration_admission as A

ROOT=Path(__file__).resolve().parents[1]
KIND='gegi_standalone_saved_reconstruction_v3'
SOURCES=('tools/gegi_standalone_reconstruction.py','tools/gegi_signal_reconstruction.py',
         'tools/gegi_event_store.py','tools/gegi_imaging.py','tools/gegi_calibration_admission.py')
LIMITATIONS=[
    'Conditional modeled signal reconstruction, not validated detector performance.',
    'Without a compatible independent saved waveform bank, depth and source imaging remain unsupported.',
    'Legacy constant-fraction timing and central-pixel depth calibration remain diagnostics; they do not produce v3 depths.',
    'Conditional candidates are not validated recovered events or calibrated posterior probabilities.',
    'No new radiation, native drift, field solve, calibration injection or event-by-event energy rescaling.',
]


def source_hashes():return {name:W.sha(ROOT/name) for name in SOURCES}


def write_new(path,value):
    # The containing derivative directory is exclusively reserved. An exclusive
    # file create also works on filesystems where hard-link publication fails.
    with Path(path).open('xb') as stream:stream.write(W.encoded(value)+b'\n')


def compatible_bank(calibration,request,receipt,channels):
    """Explicit independent-bank admission; no central-pixel/shape fallback."""
    if calibration is None:return None
    A.standalone(calibration,request,receipt,channels)
    return R.TemplateBank(calibration)


def reconstruct_event_csv(event,channels,response,artifacts,bank=None):
    """Check exact saved signals, then pass only the shared observable allowlist."""
    ids=[c['id'] for c in channels]
    W.require(ids==list(range(1,35)),'Standalone GeGI metadata must preserve all 34 electrode identities.')
    pid=event['event_id'];W.require(type(pid) is int and pid>=0,'Invalid original standalone primary ID.')
    if event.get('channels') is None:
        W.require(event.get('status')=='native_failed' and event.get('signals_ref') is None and
                  event.get('signals_sha256') is None,'Native failure must retain unknown signals as null.')
        return R.reconstruct_event(event,None,channels,bank)
    scalar=event['channels']
    W.require(len(scalar)==34 and {c['contact_id'] for c in scalar}==set(ids),
              'Standalone native signal channel census is not 34.')
    wiring={c['id']:c['wiring_factor'] for c in channels}
    W.require(all(c.get('wiring_factor')==wiring[c['contact_id']] for c in scalar),
              'Standalone fixed channel wiring changed.')
    ref=f'events/{pid}-signals.csv'
    W.require(event.get('signals_ref')==ref and event.get('signals_sha256')==artifacts.get(ref),
              'Standalone native CSV reference/hash is not bound to its original receipt.')
    path=W.safe_path(response,ref);expected=event['signals_sha256']
    W.require(type(expected) is str and len(expected)==64 and W.sha(path)==expected,'Saved standalone native CSV bytes changed.')
    native=S.native_csv(path,scalar)
    W.require(W.sha(path)==expected,'Saved standalone native CSV changed while reading.')
    W.require(all(native[c['contact_id']]['signed_induced_keV'][-1]==c['final_induced_keV'] for c in scalar),
              'Saved CSV terminal induced charge differs from fixed scalar readout.')
    return R.reconstruct_event(event,native,channels,bank)


def analyze(payload,response,receipt,*,request=None,calibration=None):
    """Update reconstruction fields of a new payload, preserving native records."""
    W.require(payload.get('kind')=='gegi_multichannel_results_v1' and
              payload.get('status') in W.TERMINAL and
              payload.get('configuration_sha256')==receipt.get('configuration_sha256'),
              'Use a completed native standalone GeGI response with matching configuration.')
    counts=payload['counts'];events=payload['events'];channels=payload['channels']
    W.require([c['id'] for c in channels]==list(range(1,35)),
              'Standalone GeGI metadata must preserve all 34 electrode identities.')
    W.require(counts==receipt['counts'] and counts['initial_primaries']==counts['zero_deposit_primaries']+counts['nonzero_primaries'] and
              len(events)==counts['nonzero_primaries'] and len({e['event_id'] for e in events})==len(events) and
              all(type(e['event_id']) is int and 0<=e['event_id']<counts['initial_primaries'] for e in events),
              'Standalone initial/zero/nonzero denominator or original-ID census changed.')
    W.require(calibration is None or request is not None,'Explicit independent calibration needs its original native request.')
    bank=compatible_bank(calibration,request,receipt,channels) if calibration else None
    bank_pins={name:W.sha(W.safe_path(bank.root,name)) for name in ('identity.json','depth-calibration.json')} if bank else {}
    frozen=source_hashes();reasons=Counter();candidate_groups=0;candidate_count=0
    for event in events:
        result=reconstruct_event_csv(event,channels,response,receipt['artifacts'],bank)
        # Never relabel conditional v3 hypotheses as accepted legacy cones.
        result.update(cones=[],paired_site_hypotheses=[],pairing_ambiguous=len(result['hypotheses'])>1,
                      ordering_ambiguous=bool(result['candidates']))
        if 'reconstruction' in event:event.setdefault('legacy_reconstruction',copy.deepcopy(event['reconstruction']))
        event['reconstruction']=result;reasons[result.get('reason') or result['status']]+=1
        candidate_groups+=bool(result['candidates']);candidate_count+=len(result['candidates'])
    if 'imaging' in payload:payload.setdefault('legacy_imaging',copy.deepcopy(payload['imaging']))
    payload['imaging']={'method':KIND,'status':'conditional_hypotheses_only' if bank else 'unsupported_independent_waveform_templates',
        'reason':'No unconditional source image is justified by the available response model.',
        'algorithm_kind':R.KIND,'source_sha256':frozen,'calibration_sha256':bank.sha256 if bank else None,
        'accepted_events':0,'rejected_events':len(events),'ambiguous_events':candidate_groups,
        'conditional_candidate_groups':candidate_groups,'conditional_candidates':candidate_count,
        'validated_recovered_groups':0,'rejection_counts':dict(reasons),'initial_primaries':counts['initial_primaries'],
        'cones':[],'azimuth_deg':[],'elevation_deg':[],'values':None,
        'truth_used':False,'source_label_used':False,'limitations':LIMITATIONS+R.LIMITATIONS}
    payload['reconstruction_algorithm']={'kind':KIND,'shared_kind':R.KIND,'source_sha256':frozen,
        'calibration_sha256':bank.sha256 if bank else None,
        'template_bindings':bank.bindings if bank else {},'new_radiation_calls':0,'new_native_calls':0,
        'new_field_calls':0,'new_calibration_calls':0}
    payload['limitations']=list(dict.fromkeys(payload.get('limitations',[])+LIMITATIONS))
    if bank:
        W.require(all(W.sha(W.safe_path(bank.root,ref))==digest for ref,digest in {**bank_pins,**bank.bindings}.items()),
                  'Independent waveform calibration changed during standalone processing.')
    W.require(source_hashes()==frozen,'Standalone reconstruction implementation changed during processing.')
    return payload


def postprocess(run,output,*,calibration=None):
    """Read a terminal standalone run; write only a new external derivative."""
    run=Path(run).absolute();output=Path(output).absolute()
    W.safe_path(run.parent,run.name);W.safe_path(output.parent,output.name)
    W.require(output!=run and not output.is_relative_to(run) and not output.exists(),
              'Preserve the sealed original run; use a new derivative outside it.')
    complete=W.read(W.safe_path(run,'COMPLETE.json'));response=W.safe_path(run,'response')
    receipt=W.read(W.safe_path(response,'run.json'));request_path=W.safe_path(run,'gegi-request.json')
    request=W.read(request_path);results=W.safe_path(response,'results.json')
    W.require(complete.get('kind')=='local_gegi_workflow_v1' and complete.get('status') in W.TERMINAL and
              receipt.get('kind')=='gegi_native_response_v1' and receipt.get('status') in W.TERMINAL and
              complete['configuration_sha256']==receipt['configuration_sha256']==request['configuration_sha256'],
              'Use a sealed completed standalone GeGI run with its original native request.')
    before={ref:W.sha(W.safe_path(run,ref)) for ref in ('COMPLETE.json','gegi-request.json','response/run.json','response/results.json')}
    W.require(receipt['request_sha256']==before['gegi-request.json'] and
              receipt['artifacts']['results.json']==before['response/results.json']==complete['artifacts']['response/results.json']['sha256'] and
              complete['artifacts']['response/run.json']['sha256']==before['response/run.json'],
              'Standalone result, request or native receipt differs from its completion seal.')
    payload=W.read(results)
    for event in payload['events']:
        ref=f'events/{event["event_id"]}.json';path=W.safe_path(response,ref)
        W.require(W.sha(path)==receipt['artifacts'].get(ref),'Original standalone native event metadata changed.')
        original=W.read(path)
        W.require(all(event.get(k)==v for k,v in original.items()),'Saved aggregate event differs from its original native checkpoint.')
    output.mkdir(parents=True)
    write_new(output/'identity.json',{'kind':KIND,'original_input_sha256':before,'source_sha256':source_hashes(),
        'scope':'Separate saved-data derivative; original readout and scientific files remain unchanged.'})
    analyze(payload,response,receipt,request=request,calibration=calibration)
    W.require(all(W.sha(W.safe_path(run,ref))==digest for ref,digest in before.items()),
              'Original standalone inputs changed while deriving.')
    write_new(output/'results.json',payload)
    write_new(output/'COMPLETE.json',{'kind':KIND,'status':'completed_conditional_reconstruction',
        'files':{name:W.sha(output/name) for name in ('identity.json','results.json')},
        'new_radiation_calls':0,'new_native_calls':0,'new_field_calls':0,'new_calibration_calls':0})
    return payload['imaging']


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True)
    p.add_argument('--output',required=True);p.add_argument('--calibration')
    args=p.parse_args();postprocess(args.run,args.output,calibration=args.calibration)
