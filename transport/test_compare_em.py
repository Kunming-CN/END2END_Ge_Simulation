"""Small deterministic tests; no Monte Carlo simulation is launched."""
import copy
import math
from pathlib import Path
import tempfile
import unittest
import h5py
import numpy as np
import compare_em as c
import handoff as h

class EMTests(unittest.TestCase):
    def test_intervals(self):
        self.assertGreater(c.wilson(0,100)[1],0)
        self.assertLess(c.wilson(100,100)[0],1)
        self.assertAlmostEqual(c.wilson(25,100)[0],1-c.wilson(75,100)[1])
        same=c.difference_interval(20,100,20,100)
        self.assertLess(same[0],0);self.assertGreater(same[1],0)
        forward=c.difference_interval(30,100,20,100)
        reverse=c.difference_interval(20,100,30,100)
        self.assertAlmostEqual(forward[0],-reverse[1])
        self.assertAlmostEqual(forward[1],-reverse[0])
        for k,n in ((-1,10),(11,10),(0,0),(True,10)):
            with self.assertRaises(ValueError):c.wilson(k,n)
    def test_zero_inclusive_spectrum(self):
        m,edges,counts=c.summarize([0,0,1,4,10,10],10)
        self.assertEqual(m['zero_deposit'],2)
        self.assertEqual(m['fully_contained_events'],2)
        self.assertEqual(m['primaries'],6)
        self.assertEqual(int(counts.sum()),4)
        self.assertEqual(m['fully_contained_fraction'],1/3)
        self.assertTrue(np.allclose(np.diff(edges),.5))
        self.assertEqual(m['mean_deposited_keV_per_primary'],25/6)
        for v in ([0,-1],[0,float('nan')],[0,11],[0,float('inf')],[1]):
            with self.assertRaises(ValueError):c.summarize(v,10)
    def test_constructor_macro(self):
        _,points=h.load_model('AK02')
        default=h.macro_text(points,100,662)
        self.assertEqual(default,h.macro_text(points,100,662,'Livermore',False))
        self.assertNotIn('printParameters',default)
        for em in h.EM_OPTIONS:
            macro=h.macro_text(points,100,662,em,True)
            self.assertIn('/RMG/Processes/LowEnergyEMPhysics '+em+'\n',macro)
            self.assertIn('/process/em/printParameters',macro)
            self.assertLess(macro.index('/RMG/Processes/LowEnergyEMPhysics'),macro.index('/run/initialize'))
        with self.assertRaises(ValueError):h.macro_text(points,100,662,'unknown')
    def test_atomic_flag_and_holm_guards(self):
        text = "Fluorescence enabled 1\nAuger electron cascade enabled 1\nPIXE atomic de-excitation enabled 0\nDe-excitation module ignores cuts 1\n"
        self.assertEqual(c.atomic_flags(text), {'fluorescence':True,'auger':True,'pixe':False,'ignore_cuts':True})
        with self.assertRaises(ValueError):c.atomic_flags('Atomic Deexcitation Parameters')
        with self.assertRaises(ValueError):c.atomic_flags(text+'Fluorescence enabled 0\n')
        self.assertEqual(c.holm_adjust([.01,.04,.03]), [.03,.06,.06])
        with self.assertRaises(ValueError):c.holm_adjust([-.1])
        self.assertAlmostEqual(float(c.fisher_exact([[10,10],[10,10]]).pvalue),1.)
        self.assertLess(float(c.fisher_exact([[0,20],[20,0]]).pvalue),1e-8)
    def test_raw_source_direction_and_position(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'fixture.h5'
            with h5py.File(file,'w') as f:
                g=f.create_group('vtx');p=f.create_group('particles')
                for key,value in [('xloc',[.02265,.02265]),('yloc',[0.,0.]),('zloc',[.0047,.0047]),('time',[0.,0.])]:g[key]=value
                for key,value in [('px',[-.662,-.662]),('py',[0.,0.]),('pz',[0.,0.])]:p[key]=value
                meta={'contour_rz_mm':[[0,0],[12.65,9.4]],'energy_keV':662}
                c.validate_source(f,meta)
                g['xloc'][0]=.023
                with self.assertRaises(ValueError):c.validate_source(f,meta)
                g['xloc'][0]=.02265;p['px'][0]=.662
                with self.assertRaises(ValueError):c.validate_source(f,meta)
                p['px'][0]=-.662;g['time'][0]=1.
                with self.assertRaises(ValueError):c.validate_source(f,meta)

if __name__=='__main__':unittest.main(verbosity=2)
