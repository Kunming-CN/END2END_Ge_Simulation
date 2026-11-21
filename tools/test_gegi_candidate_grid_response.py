import json
import math
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

import gegi_candidate_grid_response as grid
import gegi_candidate_trial_curve_bank as bank
import gegi_trial_curve_quadrature_repair as repair
from gegi_escape_response_curve import log_tail_envelope


class GridResponseTests(unittest.TestCase):
    def test_curve_resume_keeps_committed_direct_quadrature_and_reuses_completed_curve(self):
        model = bank.curve_identity([0.,0.,0.],[1.,0.,0.],50.,2.)
        item = dict(model=model, energies=np.linspace(185.,200.,25), domain_keV=[185.,200.])
        settings = dict(azimuth_samples=8,energy_order=64,base_knots=3,max_log_error_target=.01)
        seen = set()
        fail = True

        def direct(energies, *args, **kwargs):
            e, = energies
            if len(seen)==2 and fail:
                raise RuntimeError('interrupted')
            self.assertNotIn(e,seen)
            seen.add(e)
            z = float(log_tail_envelope(e,50.,2.))-.01*e
            yield dict(intermediate_keV=float(e),log_escape_density=z,raw_escape_density=math.exp(z),
                       density_status='positive_raw_density',log_quadrature_difference=0.)

        with tempfile.TemporaryDirectory() as folder, patch.object(bank.curve,'direct_logs',side_effect=direct):
            path = Path(folder)/'bank.sqlite'
            with closing(sqlite3.connect(path)) as db:
                bank.create_bank(db,{'recipe':1})
                with self.assertRaisesRegex(RuntimeError,'interrupted'):
                    bank.build_curve(db,'key',item,{},None,None,None,settings)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0],2)
                fail = False
                row = bank.build_curve(db,'key',item,{},None,None,None,settings)
                self.assertEqual(row['status'],'verified_heldout_curve')
                self.assertEqual(row,bank.build_curve(db,'key',item,{},None,None,None,settings))
                with self.assertRaisesRegex(bank.W.ControlError,'Resume requires identical'):
                    bank.create_bank(db,{'recipe':2})

    def test_escape_kernel_reports_coverage_without_clipping_or_flooring(self):
        model = bank.curve_identity([0.,0.,0.],[1.,0.,0.],500.,2.)
        nodes = [190.,200.,210.]
        raw = [float(log_tail_envelope(e,500.,2.))-2. for e in nodes]
        summary = dict(status='verified_heldout_curve',model=model,domain_keV=[190.,210.],comparison=dict(
            nodes=[dict(intermediate_keV=e,log_escape_density=z) for e,z in zip(nodes,raw,strict=True)]))
        points = np.array([190.,205.,220.,230.,np.nan])
        eligible = np.array([True,True,True,False,False])
        results, statuses = grid.escape_logs(summary,points,eligible)
        self.assertEqual([grid.STATUS[i] for i in statuses],['conditional_factor_computed','conditional_factor_computed',
                         'outside_validated_curve_domain','initialized_coefficients_unavailable','trial_source_at_first_vertex'])
        self.assertTrue(np.isnan(results[2:]).all())
        self.assertLess(results[0],math.log(np.nextafter(0.,1.)))
        self.assertAlmostEqual(results[1],float(log_tail_envelope(205.,500.,2.))-2.)
        missing, unknown = grid.escape_logs(None,points,eligible)
        self.assertTrue(np.isnan(missing).all())
        self.assertEqual(grid.STATUS[unknown[0]],'escape_curve_unverified')

    def test_imported_midpoints_receive_independent_within_interval_checks(self):
        self.assertEqual(bank.independent_energy(200.,220.,{}),210.)
        self.assertEqual(bank.independent_energy(200.,220.,{210.:None}),205.)

    def test_only_failed_direct_references_get_higher_order(self):
        passing = dict(log_quadrature_difference=.005)
        failed = dict(log_quadrature_difference=.02)
        call = Mock(side_effect=lambda e,n: passing if n==512 else failed)
        self.assertEqual(repair.direct_reference(250.,passing,.01,256,512,call),dict(passing,energy_order=256))
        call.assert_not_called()
        row = repair.direct_reference(250.,failed,.01,256,512,call)
        call.assert_called_once_with(250.,512)
        self.assertEqual(row,dict(passing,energy_order=512,lower_order_reference=failed))
        call.reset_mock()
        row = repair.direct_reference(255.,None,.01,256,512,call)
        self.assertEqual([args.args for args in call.call_args_list],[(255.,256),(255.,512)])
        self.assertEqual(row['lower_order_reference'],failed)

    def test_curve_quadrature_repair_keeps_the_passing_parent_samples(self):
        model = bank.curve_identity([0.,0.,0.],[1.,0.,0.],50.,2.)
        def reference(e, difference):
            z = float(log_tail_envelope(e,50.,2.))-.01*e
            return dict(intermediate_keV=e,log_escape_density=z,raw_escape_density=math.exp(z),
                        density_status='positive_raw_density',log_quadrature_difference=difference)

        nodes = [185.,192.,200.]
        saved = {e:reference(e,.001) for e in nodes+[188.5]}
        saved[192.] = reference(192.,.025)
        original = dict(comparison=dict(nodes=[saved[e] for e in nodes]))
        evaluate = Mock(side_effect=lambda e,n:reference(e,.001))
        item = dict(model=model,energies=np.linspace(185.,200.,25),domain_keV=[185.,200.])
        with closing(sqlite3.connect(':memory:')) as db:
            bank.create_bank(db,{'recipe':1})
            result = repair.repair_curve(db,'k',original,item,saved,evaluate,256,512,.01)
            self.assertEqual(repair.repair_curve(db,'k',original,item,saved,evaluate,256,512,.01),result)
        self.assertEqual([args.args for args in evaluate.call_args_list],[(192.,512),(196.,256)])
        self.assertEqual(result['status'],'verified_heldout_curve')
        self.assertEqual(result['retained_direct_points'],3)
        self.assertEqual(result['higher_order_points'],1)
        self.assertEqual(saved[192.]['log_quadrature_difference'],.025)

    def test_quadrature_extension_preserves_other_original_curves(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'extension.sqlite'
            old = dict(basis={},settings={'energy_order':256})
            rows = {'good':{'status':'verified_heldout_curve'}, 'bad':{'status':repair.UNRESOLVED}}
            receipt = repair.extension_recipe('original',old,repair.pending_curves(rows),512)
            with closing(sqlite3.connect(path)) as db:
                bank.create_bank(db,receipt)
                with db:
                    db.execute('INSERT INTO curves VALUES (?,?)',('bad',json.dumps({'status':'verified_heldout_curve'})))
            returned,overlay = repair.read_extension(path,'original',old,rows)
            self.assertEqual(returned,receipt)
            self.assertEqual(overlay.keys(),{'bad'})
            self.assertEqual(rows['bad']['status'],repair.UNRESOLVED)
            self.assertEqual((rows | overlay)['good'],rows['good'])


if __name__=='__main__':
    unittest.main()
