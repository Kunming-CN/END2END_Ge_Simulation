"""SAP18 admission/identity tests; no radiation, field or native drift calls."""
from pathlib import Path
import copy,json,unittest
from unittest.mock import patch
import sap18_workflow as S
import scenario_workflow as W
class Sap18(unittest.TestCase):
 def test_frozen_model_and_original_width_bias(self):
  c=S.model_contract();self.assertEqual(c['source_model_sha256'],S.MODEL_SHA)
  self.assertEqual(c['contact_potentials_V'],{'1':0,'2':-380});self.assertEqual(c['readout_contact_width_mm'],.8)
  self.assertEqual(c['stored_temperature_K'],78);self.assertEqual(c['runtime_temperature_K'],77)
 def test_model_contract_tamper(self):
  for key,value in [('effective_model_sha256','0'*64),('readout_contact_width_mm',2),('runtime_temperature_K',78),('contact_potentials_V',{'1':0,'2':-370})]:
   c=copy.deepcopy(S.model_contract());c[key]=value
   with self.assertRaises(W.ControlError):S.validate(c)
 def test_fixed_own_polarity(self):
  op=S.operating();self.assertEqual(op['signed_bias_V'],-380);self.assertEqual(op['wiring_factor'],-1)
  with self.assertRaises(W.ControlError):S.operating('KMRC01_candidate')
 def test_full_source_inventory_keeps_original_build(self):
  # Public source fingerprints are independent of milestone-private history.
  protected={
   'tools/ring_model_contract.py': '5a8a896e5755a73a6039dec04037bec9259f43b1934d2d167a018562f88ab8d2',
   'transport/ring_cs137.py': 'fa9725cff1e31c51f148b453c8239b8e7a8f62247e7a9e65847fa568d99ac34f',
   'transport/scenario_source_portable.py': 'b99bfc20ece50e0a87fc22bdb78effea049d27a90fb1b8a1311bcf0e29305f4d',
   'transport/cryostat_export.cc': 'af44c9893e4576151511b185989ff1bc88431b36261d2d3b2607640d335e767b',
   'transport/pixi.lock': 'c212a7f7e78bb7af4687bbbc7322659975961e62c3ea71a6f325e65e554b56be',
   'simulation/ring_stream.jl': 'a90d113473b34f4fdbde1d255313c1c0aa2366af78b5841e074a978468ce1baa',
   'simulation/ring_response.jl': '685088c21291dc4c62c70111626903ecf39f8071eb3d0645b87bc6a76f8cccf7',
   'simulation/ring_polarity.jl': 'df15377ccbb48b6fa7f810260f121a036a7e13a894dfc1db595460611159c13d',
  }
  # Exporter/runtime readiness belongs to installed-environment preflight.
  # Exercise additive source registration with a public-only base inventory.
  with patch.object(W,'source_pins',return_value=dict(protected)) as base_inventory:
   pins=S.source_pins()
  base_inventory.assert_called_once_with('KMRC01_candidate',W.ROOT,portable=True)
  self.assertEqual(pins[S.MODEL_REF],S.MODEL_SHA)
  for ref in S.SOURCES:self.assertIn(ref,pins)
  for ref,expected in protected.items():
   with self.subTest(source=ref):
    self.assertEqual(W.sha(W.ROOT/ref),expected)
    self.assertEqual(pins[ref],expected)
 def test_check_shared_numerics_not_alias(self):
  config={'name':'sap18-pure-check','cryostat':W.CRYOSTAT,'detector':S.MODEL,'source':W.CS,'pose':'nominal','primary_count':500,
          'seed':26092631,'threads':1,'electronics':W.catalog()['electronics_defaults']}
  v=W.settings_check(config['electronics'])
  plan=W.check(config,validate_settings=lambda c,r:v,pin_reader=lambda d,r:S.source_pins(r),
               runtime_reader=lambda t:{},portable_reader=lambda c,r:None)
  self.assertEqual(plan['resolved']['numerics']['bias_V'],380)
  self.assertEqual(plan['resolved']['operating_model'],S.operating())
 def test_gamma_refused_before_science(self):
  config={'name':'sap18-pure-check','cryostat':W.CRYOSTAT,'detector':S.MODEL,'source':W.GAMMA,'pose':'plus5mm','primary_count':20,
          'seed':26092631,'threads':1,'electronics':W.catalog()['electronics_defaults']}
  with self.assertRaises(W.ControlError):W.check(config,validate_settings=lambda *a: self.fail('Must refuse source before validators'))
 def test_own_serial_commands_and_identity(self):
  resolved={'selection':{'name':'sap18-pure-check','threads':1},'portable_source_plan':{}}
  commands=S.stage_commands(W.ROOT/'.local/runs/sap18-pure-check',resolved,environment={'JULIA_EXE':'existing-julia'})
  self.assertIn('./sap18_source.py',commands['radiation'])
  self.assertIn(str(W.ROOT/'simulation/workflow_sap18_response.jl'),commands['response'])
  self.assertTrue(commands['response'][2]=='--threads=1')
 def test_no_duplicated_solver_or_native_loop(self):
  src=(W.ROOT/'simulation/workflow_sap18_response.jl').read_text()
  self.assertIn('WR.run(o,a,request;process_response=process_sap18,source_names=SOURCES)',src)
  self.assertNotIn('function consume(',src);self.assertNotIn('calculate_electric_potential!',src)
if __name__=='__main__':unittest.main()
