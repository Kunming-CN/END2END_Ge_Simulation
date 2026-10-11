"""One degree-valued source/capsule pose; fixed detector mounting is independent."""
from __future__ import annotations
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import decay_workflow as DW
import scenario_workflow as W

KIND = 'source_capsule_angular_pose_v1'
CONVENTION = 'degrees from global +y toward +x about axis x=0,y=1.473mm; local +z follows outward radius; z fixed'
BOUNDS = [-30, 30]
ROTATION = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]


def degrees(value):
    W.require(type(value) in (int, float) and BOUNDS[0] <= value <= BOUNDS[1] and math.isfinite(value),
              'Source angle must be a finite number between -30 and +30 degrees.')
    return value


def angle(selection):
    value = degrees(selection.get('angle_deg', 0))
    W.require(value == 0 or selection.get('source') != W.GAMMA,
              'The legacy synthetic gamma source retains its fixed position and direction.')
    return value


def resolve(value, root=ROOT):
    value = degrees(value)
    root = Path(root)
    a = DW.anchors(root)
    centre = a['source_pose']['position_global_mm']
    axis_y = a['expected_vacuum_global_translation_mm'][1]
    W.require(centre == [0, 37.073, .290] and axis_y == 1.473,
              'Source-angle reference anchor differs from the supported cryostat.')
    if value == 0:
        position, rotation, axis = list(centre), [list(row) for row in ROTATION], [0, 1, 0]
    else:
        radians = math.radians(value)
        s, c = math.sin(radians), math.cos(radians)
        radius = centre[1] - axis_y
        position = [radius*s, axis_y+radius*c, centre[2]]
        rotation = [[c, 0, s], [-s, 0, c], [0, -1, 0]]
        axis = [s, c, 0]
    return {'kind': KIND, 'schema_version': 1, 'angle_deg': value,
            'position_global_mm': position, 'capsule_rotation_local_to_global': rotation,
            'capsule_axis_global': axis, 'coordinate_convention': CONVENTION,
            'anchors_sha256': W.sha(root / DW.ANCHORS)}


def geometry_screen(pose, root=ROOT):
    """Conservative finite-cylinder bounds from the hash-checked actual chamber.

    This necessary screen is not a replacement for native assembly overlap checks.
    It applies continuously to requested bounded angles because it uses worst-case
    radial and axial extents, rather than interpolation between sampled poses.
    """
    import cs137 as cs
    root = Path(root)
    W.require(root.resolve() == ROOT, 'Native source-angle screen needs this project root.')
    hashes = cs.upstream_hashes()
    text = (root / '.local/transport/LBNL/chamber.tg').read_text()
    facts = (':volu RmP124 TUBE 0 50 130 G4_AIR',
             ':volu endCap TUBE 0 70.2/2 ($Lec-$Tfl)/2 G4_Al',
             ':p Tfl 10.5', ':p Lec 165.5', ':p y0 1.473', ':p z0 44.98')
    W.require(all(line in text.splitlines() for line in facts), 'Unsupported actual chamber dimensions.')
    a = DW.anchors(root)
    cap = a['capsule']
    radius, outer = 35.6, 35.1
    inward_face = radius-cap['thickness_mm']/2
    # A radial cylinder's tangent disk is outside the shell when its inward
    # plane is at/above the shell radius. No signed-angle symmetry is assumed.
    world_radial_bound = abs(1.473)+radius+cap['thickness_mm']/2+cap['radius_mm']
    zlo, zhi = .290-cap['radius_mm'], .290+cap['radius_mm']
    endlo, endhi = 44.98+10.5-165.5, 44.98
    W.require(inward_face >= outer and world_radial_bound < 50 and
              -130 < zlo < zhi < 130 and endlo < zlo < zhi < endhi,
              'Source/capsule fails conservative chamber/world containment screen.')
    W.require(pose == resolve(pose['angle_deg'], root), 'Changed resolved source pose.')
    return {'kind': 'source_angle_actual_chamber_screen_v1', 'upstream_sha256': hashes,
            'shell_outer_radius_mm': outer, 'capsule_inward_radial_plane_mm': inward_face,
            'world_radial_upper_bound_mm': world_radial_bound, 'world_radius_mm': 50,
            'capsule_z_bounds_mm': [zlo, zhi], 'endcap_z_bounds_mm': [endlo, endhi],
            'scope': 'conservative finite-solid bound; native containment and all-volume overlaps still required',
            'passed': True}
