"""Canonical GeGI CSG and a dimensioned-front, nominal-body cryostat.

No original drawing is distributed and no frozen detector parameter is changed.
The common catalog GDML compiler owns the semiconductor primitive translation.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import handoff as h
import catalog_geometry as C

MODEL = 'GeGI_3D'
MODEL_SHA = '4b6c71c178c81e68bc1fe093d491b59ab99f19aed5adaba5fc61bba74d445c04'
ASSET = 'scenarios/assets/gegi_cryostat_v1.json'
TRANSFORM = {'rotation_local_to_global': [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
             'translation_global_mm': [0, 0, 0],
             'definition': 'x_global_mm=R*x_local_mm+t'}


def load_model(root=h.ROOT):
    import yaml
    root = Path(root)
    path = root / 'models/GeGI_3D.yaml'
    h.require(h.sha256(path) == MODEL_SHA, 'Canonical GeGI model changed')
    document = yaml.safe_load(path.read_bytes())
    catalog = json.loads((root / 'models/catalog.json').read_text())
    entries = [d for d in catalog['detectors'] if d['id'] == MODEL]
    h.require(len(entries) == 1 and entries[0]['model_sha256'] == MODEL_SHA,
              'Canonical GeGI catalog identity changed')
    entry = entries[0]
    h.require(document['name'] == MODEL and document['units'] ==
              {'length': 'mm', 'angle': 'deg', 'potential': 'V', 'temperature': 'K'}
              and document['medium'] == 'vacuum' and len(document['detectors']) == 1,
              'Unsupported GeGI identity or units')
    detector = document['detectors'][0]
    semiconductor = detector['semiconductor']
    geometry = C.validate_geometry(semiconductor['geometry'])
    contacts = [{'id': c['id'], 'name': c['name'], 'potential_V': c['potential']}
                for c in detector['contacts']]
    h.require(contacts == [{k: c[k] for k in ('id', 'name', 'potential_V')}
                          for c in entry['contacts']], 'GeGI contact catalog changed')
    return {'kind': 'gegi_model_contract_v1', 'model_id': MODEL,
            'model_ref': 'models/GeGI_3D.yaml', 'model_sha256': MODEL_SHA,
            'geometry': geometry, 'bounds_mm': [-45., 45., -45., 45., -5.5, 5.5],
            'coordinate_system': 'cartesian', 'coordinate_transform': TRANSFORM,
            'contacts': contacts, 'readout_contact_ids': list(range(1, 17)) + list(range(18, 34)),
            'guard_contact_ids': [17, 34], 'temperature_K': semiconductor['temperature'],
            'impurity_density': semiconductor['impurity_density'],
            'analytic_crystal_volume_mm3': 2 * (math.sqrt(2) - 1) * 90**2 * 11,
            'active_area_cm2': 54.16,
            'qualification': 'Existing user model: area-fit strips and selected gap, guard, impurity and orientation retained; not experimental response validation.'}


def load_cryostat(root=h.ROOT):
    data = json.loads((Path(root) / ASSET).read_text())
    h.require(data['id'] == 'gegi_cryostat_v1' and data['compatible_detectors'] == [MODEL],
              'Wrong GeGI cryostat asset')
    m, n = data['measured_front'], data['nominal_enclosure']
    h.require(m['crystal_front_z_mm'] == 5.5 and m['crystal_to_outer_front_mm'] == 8.1
              and m['outer_cover_thickness_mm'] == 1.6 and m['inner_shield_thickness_mm'] == .8
              and m['rear_shield_thickness_mm'] == 1., 'Dimensioned GeGI layers changed')
    h.require(math.isclose(n['crystal_to_inner_shield_gap_mm'] + .8 +
                          n['inner_to_outer_cover_gap_mm'] + 1.6, 8.1, abs_tol=1e-12),
              'GeGI front stack does not reproduce the dimensioned 8.1 mm')
    h.require(data['radiation_material']['geant4_material'] == 'G4_Al',
              'Unsupported cryostat material policy')
    return data


def layout(cryostat):
    """Disjoint daughter solids inside the exact outer vacuum envelope."""
    m, n = cryostat['measured_front'], cryostat['nominal_enclosure']
    front = m['crystal_front_z_mm'] + m['crystal_to_outer_front_mm']
    cap_inner = front - m['outer_cover_thickness_mm']
    rear, radius = n['outer_rear_z_mm'], n['outer_radius_mm']
    shield_front = 5.5 + n['crystal_to_inner_shield_gap_mm'] + m['inner_shield_thickness_mm']
    shield_rear, shield_radius = n['inner_shield_rear_z_mm'], n['inner_shield_radius_mm']
    values = [
        ('outer_front', 0., radius, cap_inner, front, '7075 aluminium', 'dimensioned front thickness'),
        ('outer_side', radius-n['outer_side_thickness_mm'], radius,
         rear+n['outer_rear_thickness_mm'], cap_inner, '7075 aluminium', 'nominal side'),
        ('outer_rear', 0., radius, rear, rear+n['outer_rear_thickness_mm'],
         '7075 aluminium', 'nominal rear'),
        ('inner_front', 0., shield_radius, shield_front-m['inner_shield_thickness_mm'],
         shield_front, '6061 aluminium', 'dimensioned front thickness; nominal gap split'),
        ('inner_side', shield_radius-n['inner_shield_side_thickness_mm'], shield_radius,
         shield_rear+m['rear_shield_thickness_mm'], shield_front-m['inner_shield_thickness_mm'],
         '6061 aluminium', 'nominal side'),
        ('inner_rear', 0., shield_radius, shield_rear, shield_rear+m['rear_shield_thickness_mm'],
         '6061 aluminium', 'dimensioned rear wall thickness; nominal rear placement'),
    ]
    h.require(radius > shield_radius > 45 / math.cos(math.pi/8) and rear < shield_rear < -5.5,
              'Nominal GeGI enclosure does not contain the crystal')
    parts = [{'name': name, 'rmin_mm': ri, 'rmax_mm': ro, 'zmin_mm': z0, 'zmax_mm': z1,
              'material': 'G4_Al', 'material_label': alloy, 'basis': basis, 'copy_number': 0}
             for name, ri, ro, z0, z1, alloy, basis in values]
    return {'vacuum_radius_mm': radius, 'vacuum_z_bounds_mm': [rear, front], 'parts': parts}


def source_screen(position, cryostat):
    h.require(type(position) is list and len(position) == 3 and
              all(type(v) in (int, float) and math.isfinite(v) for v in position),
              'Source needs three finite millimetre coordinates')
    assembly = layout(cryostat)
    world = cryostat['world']['half_width_mm']
    h.require(all(abs(v) < world-1 for v in position), 'Source must be inside the air world')
    z0, z1 = assembly['vacuum_z_bounds_mm']
    h.require(math.hypot(*position[:2]) > assembly['vacuum_radius_mm']+1e-6 or
              position[2] < z0-1e-6 or position[2] > z1+1e-6,
              'Source must be outside the GeGI cryostat enclosure')
    return {'inside_world': True, 'outside_assembly': True,
            'basis': 'Exact analytic containment of the same GDML world box and outer envelope cylinder'}


def gdml_text(model, cryostat):
    root = ET.fromstring(C.gdml_text(model['geometry']))
    solids, structure = root.find('solids'), root.find('structure')
    world = structure.find("volume[@name='world']")
    ge_placement = world.find('physvol')
    world.remove(ge_placement)
    world.find('materialref').set('ref', cryostat['world']['material'])
    world_solid = solids.find("box[@name='world_solid']")
    for axis in 'xyz':
        world_solid.set(axis, format(2*cryostat['world']['half_width_mm'], '.17g'))
    a = layout(cryostat)

    def tube(name, ri, ro, z0, z1):
        ET.SubElement(solids, 'tube', name=name, rmin=format(ri, '.17g'),
                      rmax=format(ro, '.17g'), z=format(z1-z0, '.17g'),
                      startphi='0', deltaphi='360', aunit='deg', lunit='mm')

    def place(parent, name, z):
        pv = ET.SubElement(parent, 'physvol', name=name, copynumber='0')
        ET.SubElement(pv, 'volumeref', ref=name)
        ET.SubElement(pv, 'position', name=name+'_position', unit='mm', x='0', y='0', z=format(z, '.17g'))

    z0, z1 = a['vacuum_z_bounds_mm']; centre = (z0+z1)/2
    tube('cryostat_vacuum_solid', 0, a['vacuum_radius_mm'], z0, z1)
    vacuum = ET.Element('volume', name='cryostat_vacuum')
    ET.SubElement(vacuum, 'materialref', ref='G4_Galactic')
    ET.SubElement(vacuum, 'solidref', ref='cryostat_vacuum_solid')
    # The common compiler fixes the crystal solid at its canonical origin.
    ge_placement.find('position').set('z', format(-centre, '.17g'))
    vacuum.append(ge_placement)
    for p in a['parts']:
        tube(p['name']+'_solid', p['rmin_mm'], p['rmax_mm'], p['zmin_mm'], p['zmax_mm'])
        vol = ET.Element('volume', name=p['name'])
        ET.SubElement(vol, 'materialref', ref=p['material'])
        ET.SubElement(vol, 'solidref', ref=p['name']+'_solid')
        structure.insert(list(structure).index(world), vol)
        place(vacuum, p['name'], (p['zmin_mm']+p['zmax_mm'])/2-centre)
    structure.insert(list(structure).index(world), vacuum)
    place(world, 'cryostat_vacuum', centre)
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n'+ET.tostring(root, encoding='unicode')+'\n'
