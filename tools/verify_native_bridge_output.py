"""Read-only verification of a finished selected pilot, including every artifact."""
import json
from pathlib import Path
import native_bridge_report as R

def verify(pilot):
    pilot=Path(pilot).resolve()
    terminal=R.read(pilot/'run.json')
    R.require(terminal['status'].startswith('completed'),'Pilot is not complete')
    inputs=R.read(pilot/'input-export.json')
    for model in ('AK02','SAP22'):
        base=pilot/model; report=R.read(base/'run.json')
        expected={'input-contract.json','profile-input.json'}
        for ns in R.NS:
            expected.add(ns+'-readout-config.json')
            for name in ('scalars.jsonl','endpoints.jsonl','traces.jsonl','signals.csv','native-failures.jsonl'):
                expected.add(ns+'/'+name)
        declared={Path(name).as_posix() for name in report['artifacts']}
        actual={p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file() and p!=base/'run.json'}
        R.require(declared==expected==actual,'Required artifact inventory mismatch')
        for name,digest in report['artifacts'].items():
            R.require(R.sha(base/name)==digest,'Changed pilot artifact')
        R.require(R.sha(base/'input-contract.json')==inputs['contracts'][model]['sha256'],'Input export binding mismatch')
        contract=R.read(base/'input-contract.json')
        R.require(contract['source_sha256']==inputs['source_sha256'] and contract['input_sha256']==inputs['input_sha256'],'Contract provenance mismatch')
        originals={(e['namespace'],e['event_id']):e for e in contract['events']}
        for ns in R.NS:
            pulses=[r for r in R.records(base/ns/'scalars.jsonl') if r['record_kind']=='pulse']
            failed={R.key(r):r for r in pulses if r['status']=='native_transport_failed'}
            ledger=list(R.records(base/ns/'native-failures.jsonl'))
            R.require(len(ledger)==len(failed) and {R.key(d['pulse']) for d in ledger}==set(failed),'Failure ledger census mismatch')
            for d in ledger:
                pulse=d['pulse']; e=originals[(ns,pulse['event_id'])]; g=pulse['group']
                rows={s['raw_row_index']:s for s in e['steps']}
                R.require(pulse==failed[R.key(pulse)] and d['original_event']==e and d['original_group']==g,'Failure identity/truth mismatch')
                R.require(d['original_steps']==[rows[i] for i in g['row_indices']],'Failure original rows mismatch')
                err=pulse['native_error']
                R.require(err['type']=='ArgumentError' and err['message'] in ('Noncontact endpoint outside crystal','Invalid waveform support'),'Unexpected failure type')
                R.require(err['exact_error']=='ArgumentError: '+err['message'],'Failure error text mismatch')
                for k in ('readout','final_induced_keV','transport_flags','endpoints'):
                    R.require(pulse[k] is None,'Invented failed-native quantity')
            for endpoint in R.records(base/ns/'endpoints.jsonl'):
                R.require(R.key(endpoint) not in failed,'Failed native endpoint must not exist')
    return {'status':'passed','scope':'Artifact inventory, hashes, contract bindings and failure truth'}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('pilot',type=Path)
    print(json.dumps(verify(p.parse_args().pilot)))
