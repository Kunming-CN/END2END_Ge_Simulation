"""Replay the sealed 20-observation profile with verified outer escape segments."""

import argparse
from contextlib import closing
import math
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

import numpy as np

import gegi_ideal_forward_continuous as fit
import gegi_ideal_forward_curve_extensions as ext
import scenario_workflow as W


class ExtendedResponse(fit.Response):
    def __init__(self,*args,extensions,saved,**kwargs):
        super().__init__(*args,**kwargs)
        self.endpoint = saved | self.endpoint
        self.extensions = {k:ext.curves_for(v) for k,v in extensions.items()}

    def escape(self,key,curve,direct,energy):
        if not curve.nodes[0]<=energy<=curve.nodes[-1]:
            side = 'lower' if energy<curve.nodes[0] else 'upper'
            outer = self.extensions.get(key,{}).get(side)
            if outer is not None and outer.nodes[0]<=energy<=outer.nodes[-1]:
                self.state_count['verified_extension_lookups'] += 1
                return float(outer.log_density(energy))
        return super().escape(key,curve,direct,energy)


def old_points(response,norm,label,previous):
    """Compare identical coordinates under the same held-out Sobol draws."""
    candidates = [previous['selected'],previous['fixed_grid_comparison']]
    candidates.extend(item['selected'] for item in previous['radial_profile'] if item['selected'] is not None)
    peak = 0.
    for old in candidates:
        current = fit.objective(response,norm,label,norm.powers[-1],norm.validation,np.array(old['source_mm']))
        W.require(current is not None,'Extended response lost a previously evaluated source coordinate')
        peak = max(peak,abs(current['log_score']-old['independent_fine']['log_score']))
    return dict(matched_source_coordinates=len(candidates),max_abs_log_score_difference=peak)


def run(args):
    started = time.perf_counter()
    W.require(not args.output.exists() and args.endpoint_store.resolve()!=args.saved_endpoints.resolve(),
              'Choose fresh derivative outputs outside the original endpoint store')
    obs,plan,rates,crystal,points,cohorts,keys,branches,rows,old_refs,bind = ext.load_inputs(args)
    evidence,baseline,fixed,normal = [W.read(p) for p in (args.extensions,args.previous,args.fixed_blind,args.normalization)]
    W.require(evidence['kind']==ext.KIND and evidence['bindings']==bind and
        baseline['kind']==fit.FIT_KIND and W.digest(baseline['fit'])==baseline['blind_fit_sha256'] and
        baseline['observation_sha256']==bind['observation_sha256'] and
        baseline['endpoint_store_sha256']==bind['old_endpoint_store_sha256'] and
        baseline['fixed_blind_sha256']==W.sha(args.fixed_blind) and
        baseline['normalization_sha256']==W.sha(args.normalization)==fixed['normalization_sha256'] and
        fixed['curve_bank_sha256']==bind['curve_bank_sha256'] and
        fixed['curve_overlay_sha256']==bind['overlay_sha256'] and normal['basis']==bind['basis'],
        'The extended response must replay the original measured grid and continuous fit')
    baseline_fit = baseline['fit']
    cfg = SimpleNamespace(**baseline_fit['settings'])
    radii,nd = plan['trial_grid']['radii_mm'],len(plan['trial_grid']['unit_vectors'])
    normalizer = fit.Normalizers(crystal,rates,obs['incident_keV'],normal,cfg.independent_validation_seeds)
    meta = dict(kind='gegi_ideal_forward_extended_endpoint_store_v1',bindings=bind,
        extension_sha256=W.sha(args.extensions),source_sha256={Path(p).name:W.sha(p) for p in (__file__,fit.__file__,ext.__file__)})
    comparisons,out = {},{}
    with closing(sqlite3.connect(args.endpoint_store)) as db:
        fit.forward.bank.create_bank(db,meta)
        response = ExtendedResponse(crystal,rates,obs,branches,rows,db,bind['endpoint_settings'],
                                    extensions=evidence['curves'],saved=old_refs)
        for label,row in fixed['measured_analysis']['cohorts'].items():
            t = time.perf_counter()
            ids = [event['attempt_id'] for event in cohorts[label]['first_accepted']]
            W.require(ids==row['scored_attempt_ids'],'Extension cannot alter the fitted event set')
            original = baseline_fit['cohorts'][label]
            parity = old_points(response,normalizer,label,original)
            value = fit.profile_cohort(label,cfg,points,radii,nd,row['profile'],response,normalizer,False)
            value.update(scored_attempt_ids=ids,all_accepted_count=row['all_accepted_count'],
                         retained_for_expansion_count=row['retained_for_expansion_count'])
            by_radius = {v['radial_index']:v['selected'] for v in value['radial_profile']}
            orig_radius = {v['radial_index']:v['selected'] for v in original['radial_profile']}
            W.require(by_radius.keys()==orig_radius.keys(),'Extension changed the radial profile scope')
            shift = math.dist(value['selected']['source_mm'],original['selected']['source_mm'])
            comparisons[label] = dict(fixed_coordinate_parity=parity, fitted_position_shift_mm=shift,
                shell_max_independent_log_difference=max(abs(by_radius[r]['independent_fine']['log_score']-
                    orig_radius[r]['independent_fine']['log_score']) for r in by_radius),
                elapsed_seconds=time.perf_counter()-t)
            out[label] = value
            print(dict(cohort=label,**comparisons[label]),flush=True)
    W.require(W.sha(args.saved_endpoints)==bind['old_endpoint_store_sha256'],'Original endpoint samples changed')
    treatment = dict(baseline_fit,cohorts=out,objective_census=dict(curve_state_counts=dict(response.state_count),
        source_normalizer_components_computed=normalizer.computed,numerator_cached_points=len(response.cache)))
    elapsed = time.perf_counter()-started
    result = dict(baseline,fit=treatment,blind_fit_sha256=W.digest(treatment),elapsed_seconds=elapsed,
        extension_replay=dict(previous_sha256=W.sha(args.previous),extension_sha256=meta['extension_sha256'],
                              original_elapsed_seconds=baseline['elapsed_seconds'],comparisons=comparisons),
        endpoint_store_sha256=W.sha(args.endpoint_store),
        source_sha256=baseline['source_sha256']|meta['source_sha256'])
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    print(dict(output_sha256=W.sha(args.output),elapsed_seconds=elapsed,
               curve_state_counts=dict(response.state_count)),flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    ext.common(p)
    for name in ('extensions','previous','fixed-blind','normalization','endpoint-store','output'):
        p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())


if __name__=='__main__':
    main()
