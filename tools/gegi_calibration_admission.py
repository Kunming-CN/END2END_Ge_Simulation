"""Read-only compatibility admission for independent saved GeGI waveforms.

No numerical solver or waveform fit is imported. Exact saved model, field,
electrode, time-grid and native-software identities determine admission.
"""
from __future__ import annotations
import math
from pathlib import Path

import scenario_workflow as W

ROOT=Path(__file__).resolve().parents[1]
KIND='gegi_saved_calibration_admission_v1'
SHARED_NATIVE=('gegi_response.jl','gegi_signal_helpers.jl','run.jl','replay.jl',
               'readout.jl','readout_profiles.jl','readout_demo.json')


def _identity(calibration):
    path=Path(calibration).absolute();W.safe_path(path.parent,path.name)
    original=W.safe_path(path,'identity.json');table=W.safe_path(path,'depth-calibration.json')
    identity=W.read(original);depth=W.read(table);digest=W.sha(original)
    W.require(identity.get('kind')=='gegi_pixel_calibration_identity_v1' and
              depth.get('identity_sha256')==digest,'Independent saved waveform calibration identity changed.')
    return identity,{'kind':KIND,'identity_sha256':digest,'table_sha256':W.sha(table)}


def _match(identity,request,channels,*,field_precision,native_sources,manifest_sha256,julia_version=None):
    W.require(identity.get('model_sha256')==request.get('model_sha256') and
              identity.get('channels')==channels and [c['id'] for c in channels]==list(range(1,35)),
              'Independent templates differ from the frozen model or exact 34-electrode metadata.')
    field=request.get('field_cache') or {};numerical=request.get('numerics') or {}
    W.require(field.get('sha256') and identity.get('field_cache',{}).get('sha256')==field['sha256'] and
              identity.get('field_precision_bits') in (32,64) and
              (field_precision is None or identity['field_precision_bits']==field_precision),
              'Independent templates require the same exact saved field state and precision.')
    dt=numerical.get('drift_dt_ns',1.);cap=numerical.get('drift_cap_ns',1000.);grid=identity.get('numerics') or {}
    W.require(type(dt) in (int,float) and math.isfinite(dt) and dt>0 and
              type(cap) in (int,float) and math.isfinite(cap) and cap>dt and
              numerical.get('diffusion',False) is False and numerical.get('self_repulsion',False) is False and
              grid.get('dt')==dt and grid.get('max_steps')==math.ceil(cap/dt)+1,
              'Independent templates differ from the native waveform time step or drift assumptions.')
    environment=identity.get('environment') or {};sources=identity.get('source_sha256') or {}
    W.require(manifest_sha256 and environment.get('manifest_sha256')==manifest_sha256 and
              (julia_version is None or environment.get('julia_version')==julia_version),
              'Independent templates differ from the pinned native environment.')
    W.require(all(native_sources.get(k) and native_sources[k]==sources.get(k) for k in SHARED_NATIVE),
              'Independent template/native carrier or readout implementation differs.')
    for name in ('Manifest.toml','Project.toml'):
        expected=native_sources.get(name) or request.get('source_sha256',{}).get('simulation/'+name)
        if expected:W.require(sources.get(name)==expected,'Independent template/native environment source differs: '+name)


def standalone(calibration,request,receipt,channels):
    if calibration is None:return None
    identity,report=_identity(calibration)
    W.require(receipt.get('model_sha256')==request.get('model_sha256') and receipt.get('channels')==channels,
              'Standalone native metadata differs from its original request.')
    actual=receipt.get('fields') or {};field=request.get('field_cache') or {}
    W.require(actual.get('cache_sha256')==field.get('sha256') and actual.get('precision_bits') in (32,64),
              'Standalone native field identity or precision is unavailable.')
    environment=receipt.get('environment') or {}
    _match(identity,request,channels,field_precision=actual['precision_bits'],
        native_sources=receipt.get('source_code_sha256') or {},
        manifest_sha256=environment.get('environment_manifest_sha256'),julia_version=environment.get('julia_version'))
    return {**report,'status':'compatible_saved_response_identity','model_sha256':identity['model_sha256'],
        'field_cache_sha256':field['sha256'],'field_precision_bits':actual['precision_bits'],
        'channel_count':len(channels),'drift_dt_ns':identity['numerics']['dt'],
        'max_steps':identity['numerics']['max_steps'],'scope':'Compatibility only; no experimental or complete-response validation.'}


def _native_requests(plan,root):
    """Recover only hash-bound request generations from retained revisions."""
    documents=[plan];seen=set();requests={}
    while documents:
        value=documents.pop()
        W.require(len(seen)<=32,'Saved campaign revision chain exceeds the bounded admission scope.')
        for key in ('native_request','new_native_request','recovery','transport_revision','quota_amendment','original_plan','predecessor_plan'):
            ref=value.get(key)
            if not isinstance(ref,dict) or set(ref)!={'ref','sha256'}:continue
            identity=(ref['ref'],ref['sha256'])
            if identity in seen:continue
            seen.add(identity);path=W.safe_path(root,ref['ref'])
            W.require(W.sha(path)==ref['sha256'],'Saved native-request/revision generation changed.')
            body=W.read(path)
            if key in ('native_request','new_native_request'):requests[ref['sha256']]=body
            else:documents.append(body)
    return requests


def campaign(campaign,calibration,*,root=ROOT):
    """Require every sealed chunk's original recipe to match the chosen bank."""
    if calibration is None:return None
    campaign=Path(campaign).absolute();root=Path(root).absolute();W.safe_path(campaign.parent,campaign.name)
    complete=W.read(W.safe_path(campaign,'COMPLETE.json'));plan_path=W.safe_path(campaign,'plan.json')
    plan=W.read(plan_path);plan_sha=W.sha(plan_path)
    W.require(complete.get('kind')=='gegi_campaign_plan_v1' and complete.get('status') in W.TERMINAL and
              complete.get('plan_sha256')==plan_sha,'Original campaign plan/completion binding changed.')
    requests=_native_requests(plan,root);request_sha=plan['native_request']['sha256']
    W.require(request_sha in requests,'Original campaign native request is missing.')
    identity,report=_identity(calibration);seen=set();used=set()
    for seal in (campaign/'chunks').glob('*/b*/DONE.json'):
        seal=W.safe_path(campaign,seal.relative_to(campaign).as_posix());done=W.read(seal)
        index=done['identity']['chunk_index']
        W.require(index not in seen and complete['chunks'].get(str(index))==W.sha(seal),
                  'Campaign chunk completion seal changed or is duplicated.')
        seen.add(index);native=done['identity'];response=done['response'];recipe=response['readout_recipe']
        native_sha=native.get('native_request_sha256')
        W.require(native_sha in requests and response.get('native_request_sha256')==native_sha,
                  'Campaign chunk names an unbound native-request generation.')
        request=requests[native_sha];used.add(native_sha)
        W.require(request.get('kind')=='gegi_campaign_response_request_v1' and
                  request.get('model_sha256')==plan.get('model_sha256') and
                  request.get('numerics',{}).get('field_policy')=='reuse-only',
                  'Saved campaign must retain its original reuse-only native model/request.')
        W.require(
                  native.get('model_sha256')==plan['model_sha256'] and response.get('new_field_solve') is False and
                  response.get('readout_recipe_sha256')==W.digest(recipe) and
                  recipe.get('drift_dt_ns')==request.get('numerics',{}).get('drift_dt_ns',1.),
                  'Campaign native model, drift recipe or request identity differs across chunks.')
        source=recipe.get('source_code_sha256') or {}
        W.require(source.get('Manifest.toml')==request['source_sha256'].get('simulation/Manifest.toml') and
                  source.get('Project.toml')==request['source_sha256'].get('simulation/Project.toml') and
                  all(source.get(k)==request['source_sha256'].get('simulation/'+k) for k in SHARED_NATIVE),
                  'Campaign native software/environment source pins differ from the original request.')
        _match(identity,request,recipe['channels'],field_precision=None,native_sources=source,
               manifest_sha256=source.get('Manifest.toml'))
    W.require(seen and {str(i) for i in seen}==set(complete['chunks']),'Campaign sealed chunk census is incomplete.')
    return {**report,'status':'compatible_saved_response_identity','campaign_complete_sha256':W.sha(campaign/'COMPLETE.json'),
        'native_request_sha256':request_sha,'original_native_request_variants_checked':sorted(used),
        'model_sha256':identity['model_sha256'],
        'field_cache_sha256':identity['field_cache']['sha256'],'field_precision_bits':identity['field_precision_bits'],
        'field_precision_basis':'Same serialized field-cache SHA256 and same native loader. Requested fresh-solve precision is a separate setting.',
        'channel_count':34,'drift_dt_ns':identity['numerics']['dt'],'max_steps':identity['numerics']['max_steps'],
        'sealed_chunks_checked':len(seen),'native_environment_basis':'Exact locked Manifest/Project and native source hashes; no new runtime or field inspection.',
        'scope':'Compatibility only; no experimental or complete-response validation.'}
