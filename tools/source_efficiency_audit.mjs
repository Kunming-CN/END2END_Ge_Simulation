// Postprocess the saved 10k run only. No radiation, SSD, or electronics rerun.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const [input,output]=process.argv.slice(2);
if(!input||!output||process.argv.length!==4)throw Error('Usage: node tools/source_efficiency_audit.mjs .local/CAMPAIGN .local/NEW.json');
const check=(ok,msg)=>{if(!ok)throw Error(msg);};
const local=fs.realpathSync(path.join(root,'.local')), dir=fs.realpathSync(path.resolve(input)), dest=path.resolve(output);
check(dir.startsWith(local+path.sep)&&fs.realpathSync(path.dirname(dest)).startsWith(local+path.sep),'Paths must be below project .local');
check(!fs.existsSync(dest),'No overwrite');
const json=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const run=json(path.join(dir,'run.json'));
check(run.events_per_model===10000&&run.status==='completed_with_native_failures','Use the completed 10k source');
// Log-log interpolation of NIST total attenuation coefficients, NOT energy absorption.
const interpolate=(v0,v1)=>Math.exp(Math.log(v0)+Math.log(.661657/.6)/Math.log(.8/.6)*Math.log(v1/v0));
const muGe=interpolate(.07452,.06426)*5.323, muAl=interpolate(.07802,.06841)*2.699;
const result={kind:'saved_source_geometry_sanity_check_v1',campaign_sha256:sha(path.join(dir,'run.json')),models:[],
 nist:{energy_keV:661.657,interpolation:'log-log between 0.6 and 0.8 MeV; total attenuation, includes coherent scattering',
 Ge_mu_cm_inverse:muGe,Al_mu_cm_inverse:muAl,
 sources:['https://physics.nist.gov/PhysRefData/XrayMassCoef/ElemTab/z32.html','https://physics.nist.gov/PhysRefData/XrayMassCoef/ElemTab/z13.html']},
 limitations:['Order-of-magnitude disk/mean-thickness estimate, not a second transport simulation or a validation of experimental efficiency.',
 'Ignores exact groove/bore-dependent path lengths, oblique incidence, capsule angular attenuation, scattered-in photons and non-line radiation.',
 'Counts of decays with Ge deposition are distinct from energy-deposition fraction, accepted ADC events and full-energy peaks.',
 'Geometry is nominal: global +y faces curved cylindrical wall, not the flat axial end of the cryostat.']};
for(const model of ['AK02','SAP22']){
 const folder=path.join(dir,model), scenario=json(path.join(folder,'transport/scenario.json'));
 const geometry=json(path.join(folder,'transport/geometry-report.json')), response=json(path.join(folder,'response/run.json'));
 check(sha(path.join(folder,'response/run.json'))===run.models[model].response_report_sha256,'Response receipt changed');
 const scalar=path.join(folder,'response/scalars.jsonl'); check(sha(scalar)===response.artifacts['scalars.jsonl'],'Scalar bytes changed');
 const decays=fs.readFileSync(scalar,'utf8').trim().split('\n').map(JSON.parse).filter(e=>e.record_kind==='decay');
 check(decays.length===10000&&decays.every((e,i)=>e.event_id===i&&e.global_decay_id===i),'Incomplete decay census');
 const gdml=fs.readFileSync(path.join(folder,'transport/canonical.gdml'),'utf8');
 const rz=[...gdml.matchAll(/<rzpoint\s+r="([^"]+)"\s+z="([^"]+)"/g)].map(m=>[Number(m[1]),Number(m[2])]);
 check(rz.length>0&&rz.flat().every(Number.isFinite),'Invalid Ge contour');
 const radius=Math.max(...rz.map(v=>v[0])), height=Math.max(...rz.map(v=>v[1]))-Math.min(...rz.map(v=>v[1]));
 const source=scenario.source.position_global_mm, transform=scenario.coordinate_transform;
 check(JSON.stringify(transform.rotation_local_to_global)==='[[1,0,0],[0,0,1],[0,-1,0]]','Unexpected pose');
 check(source[0]===transform.translation_global_mm[0]&&Math.abs(source[2]-transform.translation_global_mm[2])<1e-12,'Source not centered');
 const top=transform.translation_global_mm[1]+Math.max(...rz.map(v=>v[1])), gap=source[1]-top;
 const omega=(1-gap/Math.sqrt(gap*gap+radius*radius))/2;
 const meanThickness=geometry.crystal_volume_mm3/(Math.PI*radius*radius);
 const lineCount=decays.reduce((n,e)=>n+e.line_photon_count,0), positive=decays.filter(e=>e.deposited_energy_keV>0);
 const totalGe=decays.reduce((n,e)=>n+e.deposited_energy_keV,0);
 const GeP=1-Math.exp(-muGe*meanThickness/10);
 // Nominal central ray: capsule Al + curved outer wall + shield roof, millimetres.
 const aluminumMm=.1+1.25+1.27, AlT=Math.exp(-muAl*aluminumMm/10);
 const approx=lineCount/decays.length*omega*AlT*GeP;
 result.models.push({model,source_global_mm:source,crystal_translation_global_mm:transform.translation_global_mm,
  radius_mm:radius,height_mm:height,volume_mm3:geometry.crystal_volume_mm3,top_global_y_mm:top,source_to_top_mm:gap,
  upper_envelope_disk_solid_angle_fraction:omega,volume_over_projected_area_mm:meanThickness,
  nominal_central_Al_path_mm:aluminumMm,nominal_central_Al_unscattered_transmission:AlT,mean_thickness_total_interaction_probability:GeP,
  line_photons:lineCount,initial_decays:decays.length,Ge_positive_decays:positive.length,Ge_positive_fraction:positive.length/decays.length,
  deposited_total_keV:totalGe,mean_Ge_energy_per_initial_decay_keV:totalGe/decays.length,mean_energy_given_Ge_deposit_keV:totalGe/positive.length,
  Ge_deposit_650_to_670_keV_decays:positive.filter(e=>e.deposited_energy_keV>=650&&e.deposited_energy_keV<670).length,
  approximate_line_only_interacting_fraction:approx,source_hashes:{scenario:sha(path.join(folder,'transport/scenario.json')),geometry_report:sha(path.join(folder,'transport/geometry-report.json')),scalars:sha(scalar)}});
}
fs.writeFileSync(dest,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify(result.models.map(m=>({model:m.model,gap_mm:m.source_to_top_mm,solid_angle:m.upper_envelope_disk_solid_angle_fraction,observed:m.Ge_positive_fraction,estimate:m.approximate_line_only_interacting_fraction,mean_deposit_keV:m.mean_energy_given_Ge_deposit_keV,band650_670:m.Ge_deposit_650_to_670_keV_decays}))));
