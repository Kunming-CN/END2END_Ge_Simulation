"""Run native GeGI signals once, then derive signal-only Compton reconstruction."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import scenario_workflow as W
import gegi_standalone_reconstruction as reconstruction


def preserve_native_results(output,expected):
    """Keep exact pre-reconstruction bytes without overwriting prior evidence."""
    source=W.safe_path(output,'results.json');target=W.safe_path(output,'native-results.json')
    if target.exists():
        W.require(W.sha(target)==expected,'Existing native-results.json differs; preserve and inspect it.')
    else:
        with source.open('rb') as original,target.open('xb') as saved:
            shutil.copyfileobj(original,saved,length=1024*1024);saved.flush();os.fsync(saved.fileno())
    W.require(W.sha(source)==W.sha(target)==expected,'Native result changed while preserving original bytes.')
    return {'file':'native-results.json','sha256':expected,
            'scope':'Exact native worker result bytes before derived reconstruction fields were added.'}


def run(request_path, output, *, resume_native=False):
    request_path, output = Path(request_path), Path(output)
    request = W.read(request_path)
    W.require(request['kind'] == 'gegi_native_request_v1', 'Unsupported GeGI native request.')
    W.verify_pins({'source_sha256': request['source_sha256']})
    W.require(resume_native or not output.exists(), 'GeGI response output already exists; preserve it.')
    if resume_native:
        W.require(output.is_dir() and (output/'identity.json').is_file()
                  and not (output/'results.json').exists(),
                  'Resume requires an unfinished native checkpoint; preserve completed results.')
        identity = W.read(output/'identity.json')
        W.require(identity['request_sha256'] == W.sha(request_path), 'Native checkpoint request changed.')
        for ref, digest in identity['source_code_sha256'].items():
            W.require(W.sha(W.safe_path(W.ROOT/'simulation', ref)) == digest, 'Native checkpoint source changed.')
    environment = W.child_env(request['selection']['threads'])
    started = time.perf_counter()
    call = subprocess.run([environment['JULIA_EXE'], '--startup-file=no',
                           '--threads='+str(request['selection']['threads']), '--project='+str(W.ROOT/'simulation'),
                           str(W.ROOT/'simulation/gegi_response.jl'), '--request', str(request_path), '--output', str(output)],
                          cwd=W.ROOT, env=environment, shell=False,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    W.require(call.returncode == 0, 'GeGI native signal worker failed; original output is retained.')
    W.verify_pins({'source_sha256': request['source_sha256']})
    receipt, payload = W.read(output/'run.json'), W.read(output/'results.json')
    W.require(receipt['configuration_sha256'] == payload['configuration_sha256'] == request['configuration_sha256'],
              'GeGI native response changed configuration identity.')
    native_hash = W.sha(output/'results.json')
    W.require(receipt['artifacts']['results.json']==native_hash, 'Native standalone result bytes differ from their worker receipt.')
    receipt['native_results']=preserve_native_results(output,native_hash)
    receipt['artifacts']['native-results.json']=native_hash
    reconstruction.analyze(payload, output, receipt, request=request)
    W.write(output/'results.json', payload)
    receipt['imaging'] = {'method': payload['imaging']['method'],
                          'source_sha256': W.sha(W.ROOT/'tools/gegi_standalone_reconstruction.py'),
                          'source_files_sha256': reconstruction.source_hashes(),
                          'input_native_results_sha256': native_hash,
                          'accepted_events': payload['imaging']['accepted_events'],
                          'status':payload['imaging']['status'],
                          'scope': 'Shared saved-waveform conditional reconstruction. No compatible independent waveform bank is supplied by this standalone worker; depth and source imaging remain unsupported. Fixed readout energies and diagnostic timings are preserved.'}
    receipt['artifacts']['results.json'] = W.sha(output/'results.json')
    receipt['response_and_imaging_elapsed_seconds'] = time.perf_counter()-started
    W.write(output/'run.json', receipt)
    print(W.encoded({'status': receipt['status'], 'counts': payload['counts'], 'imaging_events': payload['imaging']['accepted_events']}).decode('utf-8'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--resume-native', action='store_true',
                        help='Continue an exact unfinished native checkpoint; never rerun radiation.')
    args = parser.parse_args()
    run(args.request, args.output, resume_native=args.resume_native)
