"""Additive nonzero source pose using shared native assembly and original event readers.

No original preparer, exporter, isotope record or numerical input is modified.
The batch parent owns radiation; this module prepares and verifies geometry only.
"""
from __future__ import annotations
import copy, math, re, subprocess, time
from pathlib import Path
import sys
import handoff as h
import cs137 as cs
import scenario_prepare as assembly
import scenario_source_portable as P
import catalog_geometry as G
import catalog_source as C
import decay_source as D
import angle_exporter_setup as X
import source_pose as Pose
sys.path.insert(0, str(h.ROOT/'tools'))
import scenario_workflow as W
import decay_workflow as DW
import workflow_batches as B

KIND = 'source_angle_checked_plan_v1'
PREPARED_KIND = 'source_angle_prepared_v1'
ADAPTER = 'shared_source_angle_precise_gps_v2'
GPS_PRECISION_CONTRACT = 'angular_gps_double_precision_mm_v2'
WINDOWS_ROOT = None
REFS = ('transport/source_angle.py', 'transport/source_pose.py',
        'transport/angle_exporter_setup.py', 'transport/angle_exporter/CMakeLists.txt',
        'transport/cryostat_angle_export.cc', 'transport/catalog_source.py',
        'transport/catalog_geometry.py', 'transport/decay_source.py',
        'transport/sap18_source.py', 'tools/decay_workflow.py', 'tools/ring_workflow.py',
        'tools/sap18_workflow.py', DW.ANCHORS, DW.REGISTRY, 'scenarios/detector-capabilities.json')


def model_geometry(model):
    if model in W.MODELS:
        points, probes, volume = D.geometry_contract(model)
        return {'canonical_gdml': h.gdml_text(points), 'probes': probes,
                'contour_rz_mm': [list(p) for p in points], 'analytic_volume_mm3': volume}
    model_doc = G.load_model(model)
    h.require(not model_doc['placement']['blocking_reasons'],
              ' '.join(model_doc['placement']['blocking_reasons']))
    return {'canonical_gdml': G.gdml_text(model_doc['geometry']),
            'probes': G.probes(model_doc['geometry']),
            'contour_rz_mm': {'catalog_geometry': model_doc['geometry']},
            'model_contract': model_doc}


def check(selection):
    required = {'name','cryostat','detector','source','pose','primary_count','seed','threads','electronics'}
    h.require(type(selection) is dict and set(selection) == required|{'angle_deg'},
              'Nonzero angular selection needs the versioned angle field.')
    h.require(Pose.angle(selection) != 0 and selection['cryostat'] == W.CRYOSTAT and
              selection['pose'] == 'nominal' and type(selection['primary_count']) is int and
              selection['primary_count'] in (20,500) and type(selection['seed']) is int and
              1 <= selection['seed'] <= B.SEED_MAX and type(selection['threads']) is int and
              selection['threads'] in (1,2), 'Unsupported source-angle geometry preparation.')
    W.run_path(selection['name'], h.ROOT)
    source = C.source_preset(selection['source'])
    pose = Pose.resolve(selection['angle_deg'], h.ROOT)
    screen = Pose.geometry_screen(pose, h.ROOT)
    geometry = model_geometry(selection['detector'])
    build = X.read(WINDOWS_ROOT)
    legacy = P.read_build_receipt(WINDOWS_ROOT)
    mode = 'cs137_legacy' if selection['source'] == W.CS else 'registered_decay'
    data = None if mode == 'cs137_legacy' else D.installed_data(source, build['runtime'])
    pins = {**P.canonical_sources(), **{ref: h.sha256(h.ROOT/ref) for ref in REFS},
            X.RECEIPT_REF: h.sha256(h.ROOT/X.RECEIPT_REF), X.EXPORTER_REF: build['exporter']['sha256'],
            P.BUILD_RECEIPT_REF: h.sha256(h.ROOT/P.BUILD_RECEIPT_REF)}
    pins.update({'.local/transport/LBNL/'+ref: digest for ref,digest in cs.upstream_hashes().items()})
    # Existing model helpers retain the original 77 K / Li50min contracts for
    # the original five, and canonical temperatures for added catalog models.
    operating = DW.operating(selection['detector'], h.ROOT) if selection['detector'] in W.MODELS else None
    return {'kind': KIND, 'schema_version': 1, 'selection': selection, 'source_pose': pose,
            'source_position_global_mm': pose['position_global_mm'], 'geometry_screen': screen,
            'source_contract': source, 'source_mode': mode, 'operating_model': operating,
            'gps_precision_contract': GPS_PRECISION_CONTRACT,
            'model_contract': geometry.get('model_contract'), 'runtime': build['runtime'],
            'decay_data': data, 'source_sha256': pins,
            'exporter_ref': X.EXPORTER_REF, 'exporter_sha256': build['exporter']['sha256'],
            'legacy_exporter_sha256': legacy['exporter']['sha256']}


def scenario(checked):
    mount = copy.deepcopy(cs.load(h.ROOT/'transport/cryostat_nominal.json'))
    pose = checked['source_pose']
    mount['source']['position_global_mm'] = pose['position_global_mm']
    source = checked['source_contract']
    if checked.get('source_mode', 'cs137_legacy' if source['id'] == W.CS else 'registered_decay') != 'cs137_legacy':
        mount['source'].update(Z=source['Z'], A=source['A'])
    mount['capsule']['axis_global'] = pose['capsule_axis_global']
    mount['source_pose'] = pose
    return mount


def parameter_text(mount):
    # New explicit exporter contract is the original eighteen parameters plus
    # degrees. The old serializer/exporter still accepts only its old contract.
    return P.parameter_text(mount, mount['source']['position_global_mm'], False).rstrip('\n')+' '+str(mount['source_pose']['angle_deg'])+'\n'


def validate_report(report, checked, geometry):
    assembly.native_helpers()
    h.require(type(report) is dict and set(report) == {'schema_version','geant4_version_number','overlap_seed',
        'overlap_samples','source_inside_fill','crystal_volume_mm3','volumes','probes','overlaps_passed'}, 'Changed native angular report fields')
    for key, value in (('schema_version',1),('geant4_version_number',1132),('overlap_seed',26092632),('overlap_samples',10000)):
        h.require(type(report[key]) is int and report[key] == value, 'Changed native geometry setting: '+key)
    h.require(report['overlaps_passed'] is True and report['source_inside_fill'] is True, 'Native source-angle overlap or containment failed')
    volumes = report['volumes']
    h.require(type(volumes) is list and len(volumes) == len(assembly.LEDGER), 'Changed native volume census')
    for found, expected in zip(volumes, assembly.LEDGER):
        h.require(set(found) == {'name','original_path','copy_number','material','density_g_cm3','elements',
            'translation_global_mm','rotation_local_to_global','overlap'} and type(found['copy_number']) is int and
            (found['name'],found['original_path'],found['copy_number'],found['material']) == expected and
            found['overlap'] is False, 'Changed native material/identity/overlap ledger')
        density, fractions = assembly.MATERIALS[found['material']]
        h.require(math.isclose(assembly.number(found['density_g_cm3']),density,rel_tol=1e-12), 'Changed native density')
        h.require(type(found['elements']) is list and len(found['elements']) == len(fractions) and
                  len({e['name'] for e in found['elements']}) == len(fractions), 'Changed native element census')
        for e in found['elements']:
            h.require(set(e) == {'name','mass_fraction'} and e['name'] in fractions and
                math.isclose(assembly.number(e['mass_fraction']),fractions[e['name']],rel_tol=1e-12), 'Changed native composition')
        h.validate_transform({'definition':h.TRANSFORM['definition'],'translation_global_mm':found['translation_global_mm'],
                              'rotation_local_to_global':found['rotation_local_to_global']})
    a = DW.anchors(h.ROOT)
    assembly.placement(volumes[0],[0,0,0],h.TRANSFORM['rotation_local_to_global'])
    assembly.placement(volumes[5],a['expected_vacuum_global_translation_mm'],h.TRANSFORM['rotation_local_to_global'])
    assembly.placement(volumes[16],a['coordinate_transform']['translation_global_mm'],assembly.ROTATION)
    spacer = [x+y for x,y in zip(a['expected_vacuum_global_translation_mm'],a['spacer']['vacuum_centre_mm'])]
    assembly.placement(volumes[17],spacer,assembly.ROTATION)
    pose = checked['source_pose']
    for volume in volumes[18:20]:
        assembly.placement(volume,pose['position_global_mm'],pose['capsule_rotation_local_to_global'])
    assembly.require_source_inside_fill_mm(pose['position_global_mm'],volumes[19])
    h.require(report['probes'] == [{'index':i,'classification':p['expected']} for i,p in enumerate(geometry['probes'])],
              'Native/YAML mass membership changed')
    if 'analytic_volume_mm3' in geometry:
        h.require(math.isclose(assembly.number(report['crystal_volume_mm3']),geometry['analytic_volume_mm3'],rel_tol=1e-10),
                  'Native analytic mass volume changed')
    else:
        C.validate_report(report,geometry['model_contract'],geometry['probes'])


def precise_gps_macro(text):
    """Set native unit-conversion formatting immediately before the GPS centre.

    Earlier physics commands keep their original behavior. Legacy zero/Gamma
    producers never call this additive angular helper.
    """
    marker = '/gps/pos/centre '
    lines = text.splitlines(keepends=True)
    indices = [i for i,line in enumerate(lines) if line.startswith(marker)]
    h.require(len(indices) == 1 and '/control/useDoublePrecision' not in text,
              'Angular macro needs one original GPS centre command.')
    lines.insert(indices[0], '/control/useDoublePrecision true\n')
    return ''.join(lines)


def macro(meta):
    report = meta['geometry_checks']
    text = cs.macro_text(report,meta['primary_count'],meta['source_position_global_mm']) if meta['source_mode'] == 'cs137_legacy' else D.macro_text(report,meta['primary_count'],meta['source_contract'],meta['source_position_global_mm'])
    return precise_gps_macro(text)


def model_contract(selection, output, prepare=False):
    model = selection['detector']
    if model not in W.MODELS:
        return G.load_model(model)
    if prepare:
        return DW.prepare_model(model,output/'effective-model')
    reference = (output/'effective-model/GeRC02.yaml').relative_to(h.ROOT).as_posix() if model == 'GeRC02' else None
    contract = DW.model_contract(model,reference,h.ROOT)
    h.require(cs.load(output/'effective-model/model-contract.json') == contract, 'Changed effective-model contract')
    if model == 'GeRC02':
        from ring_workflow import canonical_bytes
        h.require((output/'effective-model/GeRC02.yaml').read_bytes() == canonical_bytes(model)[0], 'Changed Li50min effective model bytes')
    return contract


def metadata(selection, checked, geometry, report, contract, elapsed, files):
    mode = checked['source_mode']
    m = {'kind':PREPARED_KIND,'schema_version':1,'producer_adapter':ADAPTER,'status':'complete','selection':selection,
         'model_id':selection['detector'],'model_contract':contract,
         'model_sha256':contract.get('source_model_sha256',contract.get('model_sha256')),
         'source_id':selection['source'],'source_contract':checked['source_contract'],'source_mode':mode,
         'source_pdg':cs.ION if mode == 'cs137_legacy' else checked['source_contract']['pdg'],
         'primary_count':selection['primary_count'],'seed':selection['seed'],'source_pose':checked['source_pose'],
         'gps_precision_contract':checked['gps_precision_contract'],
         'source_position_global_mm':checked['source_position_global_mm'], 'placement_contract':DW.anchors(h.ROOT),
         'clock_policy':'remage_initial_decay_secondaries_zero','daughter_lifetime_limit_ns':-1 if mode == 'cs137_legacy' else 100000,
         'coordinate_transform':DW.anchors(h.ROOT)['coordinate_transform'],'grouping_policy':dict(cs.POLICY),
         'geometry_checks':report,'probes':geometry['probes'],'contour_rz_mm':geometry['contour_rz_mm'],
         'source_sha256':checked['source_sha256'],'upstream_sha256':cs.upstream_hashes(),
         'decay_photon_line_window_keV':cs.LINE,'native_geometry_wall_s':elapsed,'files_sha256':files,
         'material_tables':{'stp/'+v['name']:v['material'] for v in report['volumes'] if v['name'] != 'ledger_0_PV'},
         'unscored_volumes':[{'name':'ledger_0_PV','material':'G4_AIR','reason':'unscored world; no full energy closure claim'}]}
    if mode != 'cs137_legacy': m['nuclear_policy'] = checked['source_contract']['nuclear_policy']
    return m


def prepare(selection, output, checked):
    h.require(check(selection) == checked, 'Checked source-angle inputs changed')
    out = h.local_path(output)
    h.require(not out.exists(), 'Preserve prior angular geometry attempt')
    out.mkdir(parents=True)
    receipt = {'kind':'source_angle_geometry_receipt_v1','status':'failed','source_pose':checked['source_pose']}
    try:
        geometry = model_geometry(selection['detector'])
        contract = model_contract(selection,out,prepare=True)
        h.publish_json(out/'checked-plan.json',checked)
        mount = scenario(checked)
        h.publish_json(out/'scenario.json',mount)
        P.runtime_data(out,checked['runtime'],P.CS137 if checked['source_mode'] == 'cs137_legacy' else P.GAMMA)
        if checked['decay_data'] is not None: h.publish_json(out/'runtime/decay-data.json',checked['decay_data'])
        h.write_new(out/'canonical.gdml',geometry['canonical_gdml'])
        h.write_new(out/'probe-points.txt',P.probe_text(geometry['probes']))
        h.write_new(out/'parameters.txt',parameter_text(mount))
        inputs = {f.relative_to(out).as_posix():h.sha256(f) for f in out.rglob('*') if f.is_file()}
        command = [str(h.ROOT/X.EXPORTER_REF),str(h.ROOT/'.local/transport/LBNL/stage.tg'),
                   *(str(out/ref) for ref in ('canonical.gdml','probe-points.txt','parameters.txt','geometry.gdml','geometry-report.json'))]
        start = time.perf_counter()
        with (out/'geometry.log').open('x',encoding='utf-8') as log:
            result = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=False)
        elapsed = time.perf_counter()-start
        receipt.update(command=command,returncode=result.returncode,native_geometry_wall_s=elapsed)
        h.require(result.returncode == 0 and not re.search(P.DIAGNOSTIC,(out/'geometry.log').read_text(errors='replace'),re.I),
                  'Native angular geometry failed; preserve report/log')
        report = cs.load(out/'geometry-report.json')
        validate_report(report,checked,geometry)
        h.require(check(selection) == checked and all(h.sha256(out/ref) == digest for ref,digest in inputs.items()),
                  'Source-angle inputs changed during native checks')
        files = {f.relative_to(out).as_posix():h.sha256(f) for f in out.rglob('*') if f.is_file()}
        m = metadata(selection,checked,geometry,report,contract,elapsed,files)
        h.write_new(out/'run.mac',macro(m)); files['run.mac'] = h.sha256(out/'run.mac')
        h.publish_json(out/'prepared.json',m)
        receipt['status'] = 'complete'
        return m
    except BaseException as error:
        receipt['error'] = str(error)
        raise
    finally:
        h.publish_json(out/'prepare-receipt.json',receipt)


def read_prepared(directory):
    out = h.local_path(directory)
    m = cs.load(out/'prepared.json')
    checked = check(m['selection'])
    h.require(B.typed_equal(cs.load(out/'checked-plan.json'),checked), 'Angular checked authority changed')
    files = m['files_sha256']
    inventory = {f.relative_to(out).as_posix() for f in out.rglob('*') if f.is_file() and
                 f.name not in ('prepared.json','prepare-receipt.json')}
    h.require(set(files) == inventory, 'Changed angular preparation file census')
    for ref,digest in files.items():
        h.require(h.sha256(P.safe_path(out,ref,True)) == digest, 'Angular preparation bytes changed')
    geometry = model_geometry(m['selection']['detector'])
    report = cs.load(out/'geometry-report.json')
    validate_report(report,checked,geometry)
    expected = metadata(m['selection'],checked,geometry,report,model_contract(m['selection'],out),m['native_geometry_wall_s'],files)
    h.require(B.typed_equal(m,expected), 'Rehashed source/pose/model/material/clock metadata changed')
    mount = scenario(checked)
    h.require(B.typed_equal(cs.load(out/'scenario.json'),mount) and
              (out/'parameters.txt').read_text() == parameter_text(mount) and
              (out/'canonical.gdml').read_text() == geometry['canonical_gdml'] and
              (out/'probe-points.txt').read_text() == P.probe_text(geometry['probes']) and
              (out/'run.mac').read_text() == macro(m), 'Rehashed angular source/geometry/macro inputs changed')
    runtime = cs.load(out/'runtime/runtime.json')
    h.require(runtime['identity'] == checked['runtime'], 'Changed prepared runtime')
    P.recheck_runtime_data(runtime,P.CS137 if checked['source_mode'] == 'cs137_legacy' else P.GAMMA)
    if checked['decay_data'] is not None:
        h.require(cs.load(out/'runtime/decay-data.json') == checked['decay_data'], 'Changed isotope data binding')
    return out,m,checked


def events(path, meta):
    # The original raw readers keep every vertex, zero primary, row, delay and
    # signed unit. Catalog dispatch changes only membership for catalog solids.
    yield from C.events(path,meta)
