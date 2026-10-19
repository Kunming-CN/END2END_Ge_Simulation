"""Interaction-ancestry checks for the read-only rejection diagnostic."""
import unittest
import gegi_rejection_diagnostic as D

def track(tid,parent,pdg,xyz=(0,0,0),proc=-1):
    return dict(trackid=tid,parent_trackid=parent,particle=pdg,procid=proc,
                xloc=xyz[0]/1000,yloc=xyz[1]/1000,zloc=xyz[2]/1000)

def event(tracks, steps):
    values=[dict(track_id=tid,particle_pdg=pdg,position_mm=list(xyz),energy_keV=energy,raw_row_index=i)
            for i,(tid,pdg,xyz,energy) in enumerate(steps)]
    return {'input_group':{'parent_event_metadata':{'tracks':tracks}},'input_steps':values,'steps':[]}

class DiagnosticTests(unittest.TestCase):
    def test_electron_substeps_and_delta_rays_are_one_interaction(self):
        e=event([track(1,0,22),track(2,1,11,proc=1),track(3,2,11,proc=2)],
                [(2,11,(0,0,0),20),(2,11,(.1,0,0),10),(3,11,(.2,0,0),7)])
        s,_,compton,*_=D.topology(e,{1:'compt',2:'eIoni'})
        self.assertEqual(len(s),1);self.assertEqual(s[0]['energy'],37);self.assertTrue(compton)

    def test_same_gamma_two_vertices_remain_two_interactions(self):
        e=event([track(1,0,22),track(2,1,11,proc=1),track(3,1,11,(10,0,0),2)],
                [(2,11,(0,0,0),100),(3,11,(10,0,0),562)])
        s,*_=D.topology(e,{1:'compt',2:'phot'});self.assertEqual(len(s),2)

    def test_fluorescent_photon_reabsorption_is_distinct(self):
        e=event([track(1,0,22),track(2,1,11,proc=2),track(3,2,22),track(4,3,11,(2,0,0),2)],
                [(2,11,(0,0,0),650),(4,11,(2,0,0),12)])
        s,_,compton,*_=D.topology(e,{2:'phot'})
        self.assertEqual(len(s),2);self.assertFalse(compton)

    def test_direct_beta_is_not_a_gamma_interaction(self):
        e=event([track(1,0,1000551370),track(2,1,11,proc=3)],[(2,11,(0,0,0),15)])
        s,_,_,_,_,direct,*_=D.topology(e,{3:'RadioactiveDecay'})
        self.assertEqual(s,[]);self.assertEqual(direct,15)

    def test_photon_binding_deposit_matches_secondary_vertex(self):
        e=event([track(1,0,22),track(2,1,11,(1,0,0),1)],[(1,22,(1,0,0),.02),(2,11,(1,0,0),20)])
        s,*_=D.topology(e,{1:'compt'});self.assertEqual(len(s),1);self.assertAlmostEqual(s[0]['energy'],20.02)

if __name__=='__main__':unittest.main()
