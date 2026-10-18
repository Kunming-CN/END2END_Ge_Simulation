"""Bounded GeGI gamma or registered-ion transport in the locked remage runtime.

Preparation performs native geometry overlap checks without radiation. Radiation
is serial so the established bounded LH5 readers preserve every original row.
The requested 1/2 thread setting is retained for downstream SSD computation.
"""
from __future__ import annotations
import argparse
import itertools
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

import handoff as h
import cs137 as cs
import decay_source as decay
import catalog_geometry as C
import gegi_geometry as G
import scenario_source_portable as P
import scenario_transport as T

SOURCE = 'gegi_mono_gamma_v1'
CS137 = 'cs137_point_decay_v1'
CO60 = 'co60_point_decay_v1'
DECAY_SOURCES = (CS137, CO60)
REGISTRY = 'scenarios/source-presets.json'
ADAPTER = 'gegi_source_v1'
KIND = 'gegi_event_stream_v1'
FIELDS = {'name', 'cryostat', 'detector', 'source', 'pose', 'primary_count', 'seed',
          'threads', 'electronics', 'gamma_energy_keV', 'source_position_mm'}
LOCK_SHA = 'c212a7f7e78bb7af4687bbbc7322659975961e62c3ea71a6f325e65e554b56be'
PACKAGES = ('python', 'numpy', 'h5py', 'pyyaml', 'remage', 'geant4',
            'geant4-data-emlow', 'geant4-data-ensdfstate', 'geant4-data-photonevaporation',
            'geant4-data-radioactivedecay')
DIAGNOSTIC = (r'COMMAND NOT FOUND|illegal application state|command refused|parameter out of range|'
              r'macro.*(?:failed|error)|\*\*\*\s*(?:Error|Fatal)|Overlap is detected|'
              r'GeomVol1002|GeomNav0003|cannot open|failed to read|\[Error|\[Fatal')


def decode(text):
    return json.loads(text, object_pairs_hook=P.json_pairs, parse_constant=P.bad_constant,
                      parse_float=P.finite_float)


def load(path):
    return decode(Path(path).read_text(encoding='utf-8-sig'))


def source_pins():
    refs = ('transport/gegi_source.py', 'transport/gegi_geometry.py', G.ASSET,
            'transport/catalog_geometry.py', 'transport/handoff.py', 'transport/cs137.py',
            'transport/scenario_transport.py', 'transport/scenario_prepare.py',
            'transport/scenario_source_portable.py', 'models/GeGI_3D.yaml', 'models/catalog.json',
            'transport/pixi.toml', 'transport/pixi.lock', 'transport/workflow.sh',
            'transport/decay_source.py', 'tools/decay_workflow.py', REGISTRY)
    return {ref: h.sha256(h.ROOT/ref) for ref in refs}


def runtime_snapshot():
    """Reuse installed package checks without the unrelated LBNL build closure."""
    import yaml
    h.require(platform.system() == 'Linux', 'Run GeGI transport in the existing locked WSL environment')
    prefix = Path(sys.prefix).resolve()
    h.require(Path(os.environ.get('CONDA_PREFIX', '/missing')).resolve() == prefix,
              'Active locked prefix mismatch')
    h.require(Path(os.environ.get('PIXI_PROJECT_MANIFEST', '/missing')).resolve() == h.ROOT/'transport/pixi.toml',
              'GeGI transport requires the existing project Pixi runtime')
    lockfile = h.ROOT/'transport/pixi.lock'
    h.require(h.sha256(lockfile) == LOCK_SHA, 'Pinned transport lock changed')
    lock = yaml.safe_load(lockfile.read_bytes())
    urls = {p['conda'] for p in lock['environments']['default']['packages']['linux-64']}
    packages = {}
    for name in PACKAGES:
        pattern = re.compile(re.escape(name)+r'-([^-]+)-([^-]+)\.(?:conda|tar\.bz2)')
        matches = [p for p in lock['packages'] if p.get('conda') in urls and pattern.fullmatch(Path(p['conda']).name)]
        h.require(len(matches) == 1, 'Missing/ambiguous locked package '+name)
        p = matches[0]; match = pattern.fullmatch(Path(p['conda']).name)
        wanted = {'name': name, 'version': match[1], 'build': match[2],
                  'url': p['conda'], 'archive_sha256': p['sha256']}
        packages[name] = P.package_record(prefix, wanted)
    h.require(platform.python_version() == packages['python']['version'], 'Wrong locked Python')
    executables = {name: P.executable(prefix, name, version)
                   for name, version in (('remage', '1.1.0'), ('geant4-config', '11.3.2'))}
    return {'kind': 'gegi_locked_runtime_v1', 'prefix': str(prefix), 'lock_sha256': LOCK_SHA,
            'packages': packages, 'executables': executables,
            'python_sha256': h.sha256(sys.executable), 'python_version': platform.python_version()}


def registered_preset(source_id):
    """Keep the registered nuclear physics; GeGI owns only its point placement."""
    h.require(source_id in DECAY_SOURCES, 'Unsupported GeGI isotope source')
    rows=[p for p in decay.D.presets(h.ROOT) if p['id']==source_id]
    h.require(len(rows)==1, 'Missing or duplicate registered GeGI isotope')
    preset=rows[0]
    if source_id==CS137:
        h.require(preset['adapter']=='legacy_cs137_v1' and preset['isotope']=='Cs137'
                  and preset['count_unit']=='initial Cs137 decays', 'Registered Cs137 identity changed')
    else:
        decay.D.validate_source(preset)
        h.require(preset['isotope']=='Co60' and preset['pdg']==1000270600
                  and preset['count_unit']=='initial Co60 decays', 'Registered Co60 identity changed')
    return preset


def source_contract(selection, cryostat):
    screen=G.source_screen(selection['source_position_mm'], cryostat)
    if selection['source']==SOURCE:
        return {'id': SOURCE, 'particle': 'gamma', 'pdg': 22, 'distribution': 'point',
                'angular_policy': 'isotropic_4pi', 'energy_keV': selection['gamma_energy_keV'],
                'position_global_mm': selection['source_position_mm'], 'time_ns': 0,
                'particles_per_primary': 1, 'normalization': 'per emitted monoenergetic gamma; no activity or decay claim',
                'count_unit': 'emitted gamma', 'source_geometry_screen': screen}
    preset=registered_preset(selection['source'])
    legacy=selection['source']==CS137
    return {'id':preset['id'], 'mode':'cs137_legacy' if legacy else 'registered_decay',
            'registered_preset':preset, 'registry_ref':REGISTRY,
            'particle':'ion', 'pdg':cs.ION if legacy else preset['pdg'],
            'Z':55 if legacy else preset['Z'], 'A':137 if legacy else preset['A'],
            'ground_daughter_pdg':1000561370 if legacy else preset['ground_daughter_pdg'],
            'kinetic_energy_keV':0, 'primary_excitation_keV':0,
            'distribution':'point', 'position_global_mm':selection['source_position_mm'], 'time_ns':0,
            'angular_policy':'unpolarized radioactive decay; Geant4 cascade, no directed beam',
            'initial_nuclei_per_primary':1, 'count_unit':preset['count_unit'],
            'normalization':'per initial '+preset['isotope']+' nucleus, including every zero-deposit primary; gamma count is not decay count; no activity/live-time claim',
            'clock_policy':'remage_initial_decay_secondaries_zero',
            'daughter_lifetime_limit_ns':-1 if legacy else preset['nuclear_policy']['ground_secondary_lifetime_cap_ns'],
            'grouping_policy':dict(cs.POLICY),
            'diagnostic_lines':[{'name':'Ba137_661.7','window_keV':list(cs.LINE)}] if legacy else preset['diagnostic_lines'],
            'photon_diagnostic_policy':('radioactive-decay-created photons only' if legacy else
                                        'all source-descendant secondary photons, matching the shared registered-decay reader'),
            'diagnostic_line_policy':'diagnostics only; no event/photon filtering or branching-intensity claim',
            'source_geometry_screen':screen}


def isotope_data(source, runtime):
    """Reuse the existing dataset checks and bind them to this locked prefix."""
    if source['id']==SOURCE:
        return None
    if source['id']!=CS137:
        return decay.installed_data(source['registered_preset'], runtime)
    result={'source_id':CS137, 'required_files':cs.installed_data(), 'datasets':{}}
    prefix=Path(runtime['prefix']).resolve()
    packages={'G4RADIOACTIVEDATA':'geant4-data-radioactivedecay',
              'G4LEVELGAMMADATA':'geant4-data-photonevaporation', 'G4ENSDFSTATEDATA':'geant4-data-ensdfstate'}
    for variable, package in packages.items():
        directory=Path(os.environ[variable]).resolve()
        h.require(directory.is_dir() and directory.is_relative_to(prefix), 'Decay dataset outside locked prefix')
        result['datasets'][variable]={'directory':str(directory), 'package':runtime['packages'][package]}
    return result


def check(selection):
    h.require(type(selection) is dict and (set(selection)==FIELDS or
              selection.get('source') in DECAY_SOURCES and set(selection)==FIELDS-{'gamma_energy_keV'}),
              'Unsupported GeGI selection fields')
    h.require(type(selection['name']) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,48}', selection['name'])
              and not re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', selection['name']),
              'Invalid GeGI run name')
    h.require(selection['cryostat'] == 'gegi_cryostat_v1' and selection['detector'] == G.MODEL
              and selection['source'] in (SOURCE, *DECAY_SOURCES) and selection['pose'] == 'custom',
              'GeGI requires its own cryostat, canonical detector and supported point source')
    h.require(type(selection['primary_count']) is int and 1 <= selection['primary_count'] <= 10000
              and type(selection['seed']) is int and 0 < selection['seed'] < 2147483647
              and type(selection['threads']) is int and selection['threads'] in (1, 2),
              'Unsupported GeGI count, seed or thread count')
    energy = selection.get('gamma_energy_keV')
    if selection['source']==SOURCE:
        h.require(type(energy) in (int, float) and math.isfinite(energy) and 1 <= energy <= 10000,
                  'Gamma energy must be a finite 1–10000 keV value')
    else:
        h.require(energy is None, 'Isotope decay energies come from Geant4 nuclear data, not a mono-gamma energy')
    h.require(type(selection['electronics']) is dict, 'Electronics settings must be retained as an object')
    model, cryostat = G.load_model(), G.load_cryostat()
    source = source_contract(selection, cryostat)
    result = {'kind': 'gegi_source_checked_v1', 'schema_version': 1, 'selection': selection,
            'model_contract': model, 'cryostat_contract': cryostat, 'source_contract': source,
            'coordinate_transform': G.TRANSFORM, 'runtime': runtime_snapshot(), 'source_sha256': source_pins()}
    if selection['source'] in DECAY_SOURCES:
        result['decay_data']=isotope_data(source,result['runtime'])
    return result


def material_tables(cryostat):
    return {'stp/germanium': 'G4_Ge', **{'stp/'+p['name']: p['material'] for p in G.layout(cryostat)['parts']}}


def macro(checked, geometry_only=False):
    selection = checked['selection']
    report = {'volumes': [{'name': 'germanium', 'copy_number': 0},
                          *G.layout(checked['cryostat_contract'])['parts']]}
    if selection['source'] in DECAY_SOURCES and not geometry_only:
        source=checked['source_contract']
        text=(cs.macro_text(report, selection['primary_count'], selection['source_position_mm'])
              if selection['source']==CS137 else
              decay.macro_text(report, selection['primary_count'], source['registered_preset'], selection['source_position_mm']))
        # Geant4's unit messenger must retain the requested arbitrary point.
        text=text.replace('/gps/pos/centre ', '/control/useDoublePrecision true\n/gps/pos/centre ', 1)
        return ('# GeGI registered at-rest decay; canonical semiconductor and cryostat.\n'
                '/RMG/Manager/Randomization/RandomEngine JamesRandom\n'
                '/RMG/Manager/Randomization/Seed '+str(selection['seed'])+'\n'+text)
    # Keep the existing remage output precision/identity settings and explicitly
    # replace only the ion generator and decay-only clock commands.
    lines = cs.macro_text(report, selection['primary_count'], selection['source_position_mm']).splitlines()
    lines = [line for line in lines if not line.startswith(('#', '/gps/', '/run/beamOn',
             '/process/had/rdm/', '/RMG/Processes/Stepping/ResetInitialDecayTime',
             '/RMG/Processes/Stepping/DaughterNucleusMaxLifetime'))]
    lines[:0] = ['# GeGI nominal cryostat, unchanged canonical semiconductor.',
                 '/RMG/Manager/Randomization/RandomEngine JamesRandom',
                 '/RMG/Manager/Randomization/Seed '+str(selection['seed'])]
    if geometry_only:
        lines += ['/geometry/test/recursion_depth -1', '/geometry/test/resolution 10000',
                  '/geometry/test/tolerance 0 mm', '/geometry/test/verbosity true', '/geometry/test/run']
    else:
        lines += ['/gps/particle gamma', '/gps/pos/type Point',
                  '/gps/pos/centre '+' '.join(format(v, '.17g') for v in selection['source_position_mm'])+' mm',
                  '/gps/ang/type iso', '/gps/ene/type Mono',
                  '/gps/ene/mono '+format(selection['gamma_energy_keV'], '.17g')+' keV',
                  '/gps/time 0 ns', '/gps/number 1', '/run/beamOn '+str(selection['primary_count'])]
    return '\n'.join(lines)+'\n'


def command(checked, geometry_only=False):
    return ['remage', '--flat-output', '-t', '1', '--rand-seed', str(checked['selection']['seed']),
            '-o', 'geometry-check.lh5' if geometry_only else 'truth.lh5', '-g', 'geometry.gdml',
            '--', 'geometry.mac' if geometry_only else 'run.mac']


def geometry_log_check(directory, checked):
    text = (directory/'geometry.log').read_text(errors='replace')
    h.require(not re.search(DIAGNOSTIC, text, re.I), 'Native GeGI geometry failed; preserve geometry.log')
    # Positive proof that the requested kernel check visited every physical solid.
    names = ['cryostat_vacuum', 'germanium', *[p['name'] for p in G.layout(checked['cryostat_contract'])['parts']]]
    for name in names:
        h.require(re.search(r'Checking overlaps for volume\s+'+re.escape(name)+r'(?=[:\s])', text),
                  'Missing native overlap evidence for '+name)
    h.require(len(re.findall(r'OK!', text)) >= len(names), 'Incomplete native overlap completion evidence')


def prepare(selection, output, checked):
    h.require(check(selection) == checked, 'Checked GeGI inputs changed before preparation')
    d = h.local_path(output)
    h.require(not d.exists(), 'Existing GeGI output is retained; use a new output root')
    d.mkdir(parents=True)
    receipt = {'kind': 'gegi_prepare_receipt_v1', 'status': 'failed'}
    try:
        h.publish_json(d/'checked-plan.json', checked)
        h.write_new(d/'geometry.gdml', G.gdml_text(checked['model_contract'], checked['cryostat_contract']))
        h.write_new(d/'geometry.mac', macro(checked, True))
        h.write_new(d/'run.mac', macro(checked))
        h.publish_json(d/'model-contract.json', checked['model_contract'])
        h.publish_json(d/'cryostat.json', checked['cryostat_contract'])
        if 'decay_data' in checked:
            h.publish_json(d/'decay-data.json',checked['decay_data'])
        runtime = checked['runtime']; prefix = Path(runtime['prefix'])
        emlow = Path(os.environ.get('G4LEDATA', '/missing')).resolve()
        h.require(emlow.is_relative_to(prefix), 'EMLOW dataset is outside the locked environment')
        dataset = T.emlow_manifest(emlow, prefix/runtime['packages']['geant4-data-emlow']['metadata_ref'])
        h.publish_json(d/'emlow-data.json', dataset)
        cmd = command(checked, True)
        started = time.perf_counter()
        with (d/'geometry.log').open('x', encoding='utf-8') as log:
            result = subprocess.run(cmd, cwd=d, stdout=log, stderr=subprocess.STDOUT, check=False)
        receipt.update(command=cmd, returncode=result.returncode, native_geometry_wall_s=time.perf_counter()-started)
        h.require(result.returncode == 0, 'Native GeGI preparation failed; preserve evidence')
        geometry_log_check(d, checked)
        report = {'kind': 'gegi_geometry_report_v1', 'overlaps_passed': True,
                  'overlap_samples_per_volume': 10000, 'overlap_tolerance_mm': 0,
                  'coordinate_transform': G.TRANSFORM, 'source_geometry_screen': checked['source_contract']['source_geometry_screen'],
                  'analytic_crystal_volume_mm3': checked['model_contract']['analytic_crystal_volume_mm3'],
                  'geometry': G.layout(checked['cryostat_contract']),
                  'scope': 'Native sampled assembly overlap check; source/world containment is exact analytic geometry; no physical accuracy qualification.'}
        h.publish_json(d/'geometry-report.json', report)
        meta = {'kind': 'gegi_source_prepared_v1', 'schema_version': 1, 'status': 'complete',
                'producer_adapter': ADAPTER, 'selection': selection, 'model_id': G.MODEL,
                'model_sha256': G.MODEL_SHA, 'model_contract': checked['model_contract'],
                'source_id': selection['source'], 'source_contract': checked['source_contract'],
                'cryostat_contract': checked['cryostat_contract'], 'primary_count': selection['primary_count'],
                'seed': selection['seed'], 'random_engine': 'CLHEP::HepJamesRandom', 'transport_threads': 1,
                'source_position_global_mm': selection['source_position_mm'], 'coordinate_transform': G.TRANSFORM,
                'material_tables': material_tables(checked['cryostat_contract']), 'source_sha256': checked['source_sha256'],
                'runtime': runtime, 'physics': {'em': 'Livermore', 'hadronic': 'None', 'optical': False,
                    'default_production_cut_mm': .1, 'sensitive_production_cut_mm': .01,
                    'cut_note': 'Range production cuts, not a universal tracking-energy threshold'},
                'files_sha256': {p.name: h.sha256(p) for p in d.iterdir() if p.is_file()}}
        meta.update(decay_metadata(checked))
        h.require(check(selection) == checked, 'GeGI inputs/runtime changed during preparation')
        h.publish_json(d/'prepared.json', meta)
        receipt['status'] = 'complete'
        return meta
    except BaseException as error:
        receipt['error'] = str(error)
        raise
    finally:
        h.publish_json(d/'prepare-receipt.json', receipt)


def read_prepared(directory):
    d = h.local_path(directory); meta = load(d/'prepared.json'); checked = load(d/'checked-plan.json')
    h.require(meta['kind'] == 'gegi_source_prepared_v1' and meta['status'] == 'complete'
              and check(meta['selection']) == checked, 'GeGI preparation no longer reconstructs')
    for ref, sha in meta['files_sha256'].items():
        h.require(h.sha256(P.safe_path(d, ref, True)) == sha, 'Prepared GeGI artifact changed: '+ref)
    authority = {'producer_adapter': ADAPTER, 'selection': checked['selection'], 'model_id': G.MODEL,
                 'model_sha256': G.MODEL_SHA, 'model_contract': checked['model_contract'],
                 'source_id': checked['selection']['source'], 'source_contract': checked['source_contract'],
                 'cryostat_contract': checked['cryostat_contract'], 'primary_count': checked['selection']['primary_count'],
                 'seed': checked['selection']['seed'], 'random_engine': 'CLHEP::HepJamesRandom', 'transport_threads': 1,
                 'source_position_global_mm': checked['selection']['source_position_mm'],
                 'coordinate_transform': G.TRANSFORM, 'material_tables': material_tables(checked['cryostat_contract']),
                 'source_sha256': checked['source_sha256'], 'runtime': checked['runtime']}
    authority.update(decay_metadata(checked))
    h.require(all(meta.get(k) == v for k, v in authority.items()), 'Rehashed GeGI preparation policy changed')
    h.require((d/'geometry.gdml').read_text() == G.gdml_text(checked['model_contract'], checked['cryostat_contract'])
              and (d/'run.mac').read_text() == macro(checked) and (d/'geometry.mac').read_text() == macro(checked, True),
              'Rehashed GeGI geometry/source macro changed')
    receipt = load(d/'prepare-receipt.json')
    h.require(receipt['status'] == 'complete' and receipt['returncode'] == 0
              and receipt['command'] == command(checked, True), 'Incomplete geometry preparation')
    geometry_log_check(d, checked)
    if 'decay_data' in checked:
        h.require(load(d/'decay-data.json')==checked['decay_data'], 'Rehashed GeGI isotope data evidence changed')
    return d, meta, checked


def decay_metadata(checked):
    source=checked['source_contract']
    if source['id']==SOURCE:
        return {}
    return {'source_mode':source['mode'], 'source_pdg':source['pdg'],
            'source_count_unit':source['count_unit'], 'clock_policy':source['clock_policy'],
            'daughter_lifetime_limit_ns':source['daughter_lifetime_limit_ns'],
            'grouping_policy':source['grouping_policy'], 'decay_data':checked['decay_data']}


def conversion_target_material(track, rows, meta):
    """Birth-material evidence for the bounded GeGI target-recoil exception.

    Scored material needs the unchanged first-step birth time/pre-position and
    track identity. World air is unscored: infer only its exact analytic region,
    strictly inside the world box and outside the whole cryostat envelope.
    Missing/ambiguous material evidence inside that envelope remains unknown.
    """
    axes=('xloc','yloc','zloc')
    born=[]
    for table,material in meta['material_tables'].items():
        steps=[r for r in rows[table] if r['trackid']==track['trackid']]
        if not steps:
            continue
        first=min(steps,key=lambda r:r['raw_row_index'])
        if (first['evtid']==track['evtid'] and first['particle']==track['particle'] and
                first['parent_trackid']==track['parent_trackid'] and first['time']==track['time'] and
                all(first[a+'_pre']==track[a] for a in axes)):
            born.append(material)
    if born:
        return born[0] if len(born)==1 else None
    cryostat=meta['cryostat_contract']
    if cryostat['world']['material']!='G4_AIR':
        return None
    position=[1000*track[a] for a in axes]
    world=cryostat['world']['half_width_mm'];assembly=G.layout(cryostat)
    z0,z1=assembly['vacuum_z_bounds_mm']
    if (all(math.isfinite(v) and abs(v)<world for v in position) and
            (math.hypot(*position[:2])>assembly['vacuum_radius_mm'] or
             position[2]<z0 or position[2]>z1)):
        return 'G4_AIR'
    return None


def primary_tracks(rows, names, meta):
    source=meta['source_contract'];position=meta['source_position_global_mm']
    vertices,particles=rows['vtx'],rows['particles']
    h.require(len(vertices)==len(particles)==1 and vertices[0]['n_part']==1
              and vertices[0]['time']==0 and particles[0]['vertexid']==0,
              'Missing/duplicate GeGI primary or changed initial GPS clock')
    vertex=[1000*vertices[0][a] for a in ('xloc','yloc','zloc')]
    h.require(h.np.allclose(vertex,position,rtol=0,atol=1e-9), 'Wrong actual source position/units')
    G.source_screen(vertex,meta['cryostat_contract'])
    if source['id']==SOURCE:
        by_id=T.tracks(rows['tracks'],names,position)
        root=next(t for t in rows['tracks'] if t['parent_trackid']==0)
        energy=source['energy_keV']/1000
        for p in (particles[0],root):
            h.require(p['particle']==22 and math.isclose(p['ekin'],energy,rel_tol=1e-12,abs_tol=1e-12)
                      and math.isclose(math.sqrt(sum(p[a]**2 for a in ('px','py','pz'))),energy,
                                       rel_tol=1e-12,abs_tol=1e-12), 'Wrong gamma energy/identity/momentum')
        h.require(all(math.isclose(root[a],particles[0][a],rel_tol=1e-12,abs_tol=1e-12)
                      for a in ('px','py','pz')), 'Primary/root gamma direction differs')
        return by_id
    p=particles[0]
    h.require(p['particle']==source['pdg'] and p['ekin']==0 and all(p[a]==0 for a in ('px','py','pz')),
              'Wrong GeGI at-rest initial isotope identity/energy/momentum')
    target_material=lambda track:conversion_target_material(track,rows,meta)
    if source['id']==CS137:
        by_id=cs.validate_decay_tracks(rows['tracks'],names)
        root=next(t for t in rows['tracks'] if t['parent_trackid']==0)
        h.require(any(t['parent_trackid']==root['trackid'] and t['particle']//10==100056137
                      for t in rows['tracks']), 'Missing intended Cs137 barium daughter')
        for track in rows['tracks']:
            if abs(track['particle'])>=1000000000:
                h.require(track['particle']//10 in (cs.ION//10,100056137) or
                    decay.is_gamma_conversion_target_recoil(track,by_id,names,target_material(track)),
                    'Unexpected Cs137 descendant nuclear family')
            parent=track['parent_trackid']
            h.require(parent in (0,root['trackid']) or track['time']>=by_id[parent]['time'],
                      'Cs137 descendant birth precedes parent')
    else:
        h.require(source['id']==CO60, 'Unsupported GeGI decay reader')
        by_id=decay.validate_tracks(rows['tracks'],names,source['registered_preset'],
                                    target_material_for_track=target_material)
        root=next(t for t in rows['tracks'] if t['parent_trackid']==0)
    h.require(h.np.allclose([1000*root[a] for a in ('xloc','yloc','zloc')],position,rtol=0,atol=1e-9)
              and all(root[a]==0 for a in ('px','py','pz')), 'At-rest ion root position/momentum differs from GPS primary')
    return by_id


def decay_record(eid, steps, tracks, names, source):
    legacy=source['id']==CS137
    photons=[{'raw_row_index':t['raw_row_index'], 'track_id':t['trackid'],
              'parent_track_id':t['parent_trackid'], 'time_ns':t['time'],
              'energy_keV':t['ekin']*1000, 'creation_process':names[t['procid']]}
             for t in tracks if t['particle']==22 and t['parent_trackid']!=0
             and (not legacy or 'radioactivedecay' in names[t['procid']].lower())]
    lines={line['name']:sum(line['window_keV'][0]<=p['energy_keV']<=line['window_keV'][1]
                            for p in photons) for line in source['diagnostic_lines']}
    return {'global_decay_id':eid, 'source_id':source['id'], 'decay_photons':photons,
            'decay_photon_count':len(photons), 'line_photon_counts':lines,
            'line_photon_count':sum(lines.values()),
            'pulse_groups':cs.group_deposits(steps,source['grouping_policy']['horizon_ns'])}


def events(path, meta):
    """Complete original primary census; positive Ge rows are the only SSD input.

    Raw step tables including zero rows and every passive hit stay in truth.lh5.
    Reuse established remage column, ancestry and bounded table cursor checks.
    """
    import h5py
    count = meta['primary_count']; materials = meta['material_tables']
    with h5py.File(path, 'r') as raw:
        h.require(set(raw) == {'detector_origins', 'vtx', 'particles', 'tracks', 'processes', 'stp',
                              'number_of_simulated_events'}, 'Unsupported raw GeGI table census')
        census = raw['number_of_simulated_events']
        h.require(census.shape == () and census.dtype.kind in 'iu' and int(census[()]) == count,
                  'Raw GeGI initial-primary census mismatch')
        T.detector_origins(raw, meta)
        T.columns(raw['vtx'], {'evtid', 'n_part'}, {'time': 'ns', **{a: 'm' for a in ('xloc','yloc','zloc')}})
        T.columns(raw['particles'], {'evtid', 'particle', 'vertexid'}, {a: 'MeV' for a in ('ekin','px','py','pz')})
        T.columns(raw['tracks'], {'evtid','parent_trackid','particle','procid','trackid'},
                  {**{a: 'MeV' for a in ('ekin','px','py','pz')}, 'time': 'ns',
                   **{a: 'm' for a in ('xloc','yloc','zloc')}})
        T.columns(raw['processes'], {'procid'}, {}, {'name'})
        processes = list(cs.table_rows(raw['processes'])); names = {p['procid']: p['name'] for p in processes}
        h.require(len(names) == len(processes), 'Duplicate process IDs')
        h.require({'stp/'+n for n in raw['stp'] if n != '__by_uid__'} == set(materials),
                  'Missing/foreign raw step table; absence is not zero')
        cs.step_aliases(raw, materials)
        for table in materials:
            floats = {'edep': 'keV', 'time': 'ns', **{a: 'm' for a in T.POSITIONS}}
            if table == 'stp/germanium':
                floats.update({'dist_to_surf'+suffix: 'm' for suffix in ('','_pre','_post')})
            T.columns(raw[table], T.STEP_INTS, floats)
        cursors = {key: cs.Cursor(raw[key], count) for key in ('vtx','particles','tracks',*materials)}
        for eid in range(count):
            rows = {key: cursor.take(eid) for key, cursor in cursors.items()}
            vertices, particles = rows['vtx'], rows['particles']
            by_id = primary_tracks(rows,names,meta)
            sums = {}; steps = []
            for table, material in materials.items():
                values = []
                for row in rows[table]:
                    track = by_id.get(row['trackid'])
                    h.require(track is not None and (track['particle'], track['parent_trackid']) ==
                              (row['particle'], row['parent_trackid']), 'Raw deposit ancestry mismatch')
                    h.require(row['edep'] >= 0 and row['time'] >= 0 and row['time']+1e-12 >= track['time'],
                              'Invalid deposit energy/time')
                    values.append(row['edep'])
                sums.setdefault(material, []).extend(values)
            for row in rows['stp/germanium']:
                coords = {suffix: [1000*row[a+suffix] for a in ('xloc','yloc','zloc')]
                          for suffix in ('','_pre','_post')}
                labels = {suffix or 'deposit': C.membership(meta['model_contract']['geometry'], xyz)
                          for suffix, xyz in coords.items()}
                h.require('outside' not in labels.values(), 'Raw GeGI row lies outside canonical crystal')
                if row['edep'] == 0:
                    continue
                steps.append({'raw_table': 'stp/germanium', 'raw_row_index': row['raw_row_index'],
                              'energy_keV': row['edep'], 'position_mm': coords[''], 'xyz_mm': coords[''],
                              'pre_position_mm': coords['_pre'], 'post_position_mm': coords['_post'],
                              'time_ns': row['time'], 'track_id': row['trackid'],
                              'parent_track_id': row['parent_trackid'], 'pdg': row['particle'],
                              'particle_pdg': row['particle'], 'boundary_classifications': labels})
            edep = math.fsum(s['energy_keV'] for s in steps)
            event = {'event_id': eid, 'initial_primary_id': eid, 'energy_keV': edep, 'truth_edep_keV': edep,
                   'steps': steps, 'primary': particles[0], 'vertex': vertices[0], 'tracks': rows['tracks'],
                   'material_energy_keV': {m: math.fsum(values) for m, values in sums.items()}}
            if meta['source_id'] in DECAY_SOURCES:
                event.update(decay_record(eid,steps,rows['tracks'],names,meta['source_contract']))
            yield event
        h.require(all(cursor.next is None for cursor in cursors.values()), 'Unconsumed raw GeGI rows')


def census(path, meta):
    totals = {'initial_primaries': 0, 'zero_deposit_primaries': 0, 'nonzero_primaries': 0,
              'positive_ge_rows': 0, 'nonzero_event_ids': []}
    if meta['source_id'] in DECAY_SOURCES:
        totals.update(initial_decays=0,pulse_groups=0,decay_photons=0,line_photons=0,
                      line_photon_counts={line['name']:0 for line in meta['source_contract']['diagnostic_lines']})
    for event in events(path, meta):
        totals['initial_primaries'] += 1
        totals['positive_ge_rows'] += len(event['steps'])
        if meta['source_id'] in DECAY_SOURCES:
            totals['initial_decays']+=1
            totals['pulse_groups']+=len(event['pulse_groups'])
            totals['decay_photons']+=event['decay_photon_count'];totals['line_photons']+=event['line_photon_count']
            for name,value in event['line_photon_counts'].items():totals['line_photon_counts'][name]+=value
        if event['steps']:
            totals['nonzero_primaries'] += 1
            totals['nonzero_event_ids'].append(event['event_id'])
        else:
            totals['zero_deposit_primaries'] += 1
    h.require(totals['initial_primaries'] == meta['primary_count'], 'Complete primary census mismatch')
    return totals


def run(directory):
    d, meta, checked = read_prepared(directory)
    h.require(not any((d/name).exists() for name in ('run.json', 'truth.lh5', 'run.log')),
              'Existing GeGI radiation or interrupted attempt is retained')
    receipt = {'kind': 'gegi_transport_run_v1', 'status': 'failed', 'command': command(checked),
               'prepared_sha256': h.sha256(d/'prepared.json'), 'random_engine': meta['random_engine'],
               'seed': meta['seed'], 'transport_threads': 1}
    started = time.perf_counter()
    try:
        with (d/'run.log').open('x', encoding='utf-8') as log:
            t = time.perf_counter()
            result = subprocess.run(receipt['command'], cwd=d, stdout=log, stderr=subprocess.STDOUT, check=False)
            receipt.update(returncode=result.returncode, remage_wall_s=time.perf_counter()-t)
        h.require(result.returncode == 0 and not re.search(DIAGNOSTIC, (d/'run.log').read_text(errors='replace'), re.I),
                  'GeGI radiation failed; retain raw data and run.log')
        receipt['source_lh5_sha256'] = h.sha256(d/'truth.lh5')
        receipt['counts'] = census(d/'truth.lh5', meta)
        h.require(h.sha256(d/'truth.lh5') == receipt['source_lh5_sha256'], 'Raw radiation changed during validation')
        dataset = load(d/'emlow-data.json')
        actual = T.emlow_manifest(dataset['directory'], dataset['package_metadata'])
        h.require({k:v for k,v in dataset.items() if k != 'hash_wall_s'} ==
                  {k:v for k,v in actual.items() if k != 'hash_wall_s'}, 'EMLOW bytes changed during run')
        read_prepared(d)
        receipt['status'] = 'complete'
    except BaseException as error:
        receipt['error'] = str(error)
        raise
    finally:
        receipt['total_wall_s'] = time.perf_counter()-started
        h.publish_json(d/'run.json', receipt)
    return receipt


def read_run(directory):
    d, meta, checked = read_prepared(directory); receipt = load(d/'run.json')
    h.require(receipt['status'] == 'complete' and receipt['returncode'] == 0
              and receipt['command'] == command(checked) and receipt['seed'] == meta['seed']
              and receipt['prepared_sha256'] == h.sha256(d/'prepared.json')
              and receipt['source_lh5_sha256'] == h.sha256(d/'truth.lh5'),
              'Incomplete or changed GeGI radiation')
    h.require(not re.search(DIAGNOSTIC, (d/'run.log').read_text(errors='replace'), re.I),
              'Retained radiation log contains a failure')
    return d, meta, checked, receipt


def stream_contract(d, meta, run_receipt):
    counts = run_receipt['counts']
    storage = {'kind': 'nonzero_deposit_v1', 'initial_primaries': meta['primary_count'],
               'zero_deposit_primaries': counts['zero_deposit_primaries'],
               'nonzero_primaries': counts['nonzero_primaries'], 'efficiency_denominator': meta['primary_count']}
    result = {'kind': KIND, 'schema_version': 1, 'status': 'complete', 'producer_adapter': ADAPTER,
            'model_id': G.MODEL, 'model_sha256': G.MODEL_SHA, 'model_contract': meta['model_contract'],
            'source_id': meta['source_id'], 'source_contract': meta['source_contract'], 'cryostat_contract': meta['cryostat_contract'],
            'coordinate_transform': G.TRANSFORM, 'primary_count': meta['primary_count'],
            'source_count_unit':meta['source_contract']['count_unit'],
            'seed': meta['seed'], 'random_engine': meta['random_engine'], 'counts': counts,
            'zero_deposit_primaries': counts['zero_deposit_primaries'], 'nonzero_primaries': counts['nonzero_primaries'],
            'event_storage': storage, 'events_file': 'events.jsonl', 'units': {'energy': 'keV', 'length': 'mm', 'time': 'ns'},
            'source_sha256': meta['source_sha256'], 'source_lh5': '../truth.lh5',
            'source_lh5_sha256': run_receipt['source_lh5_sha256'], 'prepared_sha256': h.sha256(d/'prepared.json'),
            'run_sha256': h.sha256(d/'run.json'), 'geometry_sha256': h.sha256(d/'geometry.gdml'),
            'macro_sha256': h.sha256(d/'run.mac'), 'positive_deposit_row_policy': 'Every positive Ge row of one original event stays grouped; no charge/readout selection.',
            'raw_data_scope': 'Complete original primary, track-birth and scored Ge/passive step tables, including all zero rows, retained in truth.lh5.',
            'energy_closure': None, 'limitations': ['World-air deposits and final escape energies are not scored; full energy closure is not claimed.',
                'Track rows are birth records; pre/post Ge steps are chords, not complete trajectories.',
                'Dimensioned front layers plus nominal body; pure-Al alloy approximation; source is unencapsulated.']}
    if meta['source_id'] in DECAY_SOURCES:
        result.update({key:meta[key] for key in ('source_mode','source_pdg','clock_policy',
                                               'daughter_lifetime_limit_ns','grouping_policy')})
        result['limitations'].append('Conditional isolated 100 µs reset windows retain delayed deposits in separate pulse groups; no activity, pileup or live-time acquisition model.')
    return result


def extract(directory):
    import h5py
    d, meta, checked, receipt = read_run(directory)
    dest = h.local_path(d/'stream'); h.require(not dest.exists(), 'Existing GeGI extraction is retained')
    dest.mkdir()
    attempt = {'kind': 'gegi_extract_receipt_v1', 'status': 'failed'}
    try:
        counts = census(d/'truth.lh5', meta)
        h.require(counts == receipt['counts'], 'Raw GeGI census changed')
        with (dest/'events.jsonl').open('x', encoding='utf-8', newline='\n') as out:
            for event in events(d/'truth.lh5', meta):
                if event['steps']:
                    out.write(json.dumps(event, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n')
        manifest = stream_contract(d, meta, receipt)
        manifest['events_sha256'] = h.sha256(dest/'events.jsonl')
        with h5py.File(d/'truth.lh5', 'r') as raw:
            manifest['processes'] = list(cs.table_rows(raw['processes']))
            manifest['raw_tables'] = {key: T.table_descriptor(raw[key]) for key in
                                      ('vtx', 'particles', 'tracks', 'processes', *meta['material_tables'])}
        h.publish_json(dest/'manifest.json', manifest)
        verify(d)
        attempt['status'] = 'complete'
        return manifest
    except BaseException as error:
        attempt['error'] = str(error)
        raise
    finally:
        h.publish_json(d/'extract-receipt.json', attempt)


def verify(directory, stage='event_ledger'):
    h.require(stage in ('geometry', 'radiation', 'event_ledger'), 'Unsupported transport verification stage')
    if stage == 'geometry':
        return read_prepared(directory)[2]
    d, meta, checked, receipt = read_run(directory)
    h.require(census(d/'truth.lh5', meta) == receipt['counts'], 'Raw GeGI event census changed')
    if stage == 'radiation':
        return checked
    manifest = load(d/'stream/manifest.json'); expected = stream_contract(d, meta, receipt)
    h.require(all(manifest.get(k) == v for k, v in expected.items()), 'Rehashed GeGI stream semantics changed')
    h.require(manifest['events_sha256'] == h.sha256(d/'stream/events.jsonl'), 'GeGI event stream changed')
    raw_events = (e for e in events(d/'truth.lh5', meta) if e['steps'])
    with (d/'stream/events.jsonl').open(encoding='utf-8') as stream:
        saved_events = (decode(line) for line in stream)
        for actual, saved in itertools.zip_longest(raw_events, saved_events):
            h.require(actual == saved, 'GeGI sparse output changed original event rows/identities')
    return checked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check','prepare','run','extract','verify'))
    parser.add_argument('--selection-json'); parser.add_argument('--selection')
    parser.add_argument('--checked'); parser.add_argument('--output'); parser.add_argument('--directory')
    parser.add_argument('--stage', choices=('geometry','radiation','event_ledger'), default='event_ledger')
    parser.add_argument('--windows-root')
    args = parser.parse_args(argv)
    if args.windows_root:
        # Optional host identity is checked only; it is never a path-rewrite rule.
        P.project_identity(args.windows_root)
    if args.action == 'check':
        value = check(decode(args.selection_json) if args.selection_json else load(args.selection))
    elif args.action == 'prepare':
        value = prepare(load(args.selection), args.output, load(args.checked))
    elif args.action == 'run':
        value = run(args.directory)
    elif args.action == 'extract':
        value = extract(args.directory)
    else:
        value = verify(args.directory, args.stage)
    print(json.dumps(value, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
