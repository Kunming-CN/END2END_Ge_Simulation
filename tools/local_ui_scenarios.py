"""Read-only, all-or-none preview of four byte-pinned source configurations."""
import hashlib
from pathlib import Path
import stat
from types import ModuleType

ROOT = Path(__file__).absolute().parents[1]
CHECKER_PATH = 'transport/scenario_prepare.py'
CHECKER_SHA256 = '4dd27621d0b91f53552428c5238d219459feff72cdcdd26609bc140460f9906c'
PRESETS = (
    ('m11a-ak02-cs137_point_decay_v1-nominal',
     '8c5d806338ad718dbc21ba7d4ee219666ca00baea650af68601844182dc26b1a',
     'AK02', 'cs137_point_decay_v1', 'nominal'),
    ('m11a-ak02-mono_gamma_662_axis_v1-plus5mm',
     'fbe439cadf934899c566762b8fb836d795cf251fbad8c6afe424d627ed829586',
     'AK02', 'mono_gamma_662_axis_v1', 'plus5mm'),
    ('m11a-sap22-cs137_point_decay_v1-nominal',
     'b514968e3a5beadbf809d03cb236790ee84a29df97936848f0f1724b2a74aac0',
     'SAP22', 'cs137_point_decay_v1', 'nominal'),
    ('m11a-sap22-mono_gamma_662_axis_v1-plus5mm',
     '5e93ee3fe12329d922ac07c13bc73756e22514c42b09e22111cb97bcf9354580',
     'SAP22', 'mono_gamma_662_axis_v1', 'plus5mm'),
)
UNAVAILABLE = 'Scenario configuration preview is unavailable'


class ScenarioPreviewUnavailable(ValueError):
    """Fixed public failure; no paths, input details or underlying exception."""


def _guarded_file(relative):
    root = ROOT.absolute()
    current = root
    paths = [root]
    for bit in Path(relative).parts:
        current = current / bit
        paths.append(current)
    for current in paths:
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Linked preview input')
    if not current.is_file() or current.resolve() != current or not current.is_relative_to(root):
        raise ValueError('Unsafe preview input')
    return current


def _checker_snapshot():
    path = _guarded_file(CHECKER_PATH)
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != CHECKER_SHA256:
        raise ValueError('Preview checker changed')
    return path, source


def _load_checker(path, source):
    # The verified byte snapshot is the executed code. No sys.path, module-cache,
    # environment or import-loader changes, and no checker pycache is created.
    checker = ModuleType('_finite_scenario_preview_checker')
    checker.__file__ = str(path)
    exec(compile(source, str(path), 'exec'), checker.__dict__)
    if checker.ROOT != ROOT.absolute():
        raise ValueError('Preview root mismatch')
    return checker


def _summary(plan, preset):
    instance_id, digest, detector_id, source_id, pose_id = preset
    relative = 'scenarios/' + instance_id + '.json'
    instance, assets = plan['instance'], plan['assets']
    if (plan['input_sha256'][relative] != digest or
        instance['cryostat']['id'] != 'lbnl_modular_nominal_v1' or
        instance['detector']['id'] != detector_id or
        instance['source']['id'] != source_id or instance['source_pose'] != pose_id or
        assets['cryostat']['id'] != 'lbnl_modular_nominal_v1' or
        assets['detector']['id'] != detector_id or assets['source']['id'] != source_id):
        raise ValueError('Preview preset identity changed')
    detector, cryostat, source = assets['detector'], assets['cryostat'], assets['source']
    source_fields = ('id', 'particle', 'pdg', 'kinetic_energy_keV', 'angular_policy',
                     'direction_global', 'clock_policy', 'time_ns', 'normalization')
    public_source = {key: source[key] for key in source_fields}
    if source['particle'] == 'ion':
        public_source.update(Z=source['Z'], A=source['A'])
    return {
        'id': instance_id, 'configuration_sha256': digest,
        'detector': {key: detector[key] for key in
                     ('id', 'model_sha256', 'temperature_K', 'contacts', 'readout_contact_id')},
        'cryostat': {key: cryostat[key] for key in ('id', 'capsule_axis_global')},
        'source_pose': {'id': pose_id, 'position_global_mm': plan['source_position_global_mm']},
        'source': public_source,
        'planned_primary_count': instance['primary_count'], 'seed': instance['seed'],
        'units': instance['units'], 'source_pose_status': plan['source_pose_status'],
        'model_check': plan['model_check'], 'stages': plan['stages'],
    }


def checked_scenarios():
    """Return the complete public catalog, or one sanitized unavailable failure."""
    try:
        path, source = _checker_snapshot()
        checker = _load_checker(path, source)
        summaries = []
        for preset in PRESETS:
            config = _guarded_file('scenarios/' + preset[0] + '.json')
            summaries.append(_summary(checker.check(config), preset))
        # A mutable checker on disk must still be the approved source after every
        # check; partial catalogs never leave this function.
        _checker_snapshot()
        return {'kind': 'finite_scenario_preview_v1', 'schema_version': 1,
                'configuration_status': 'checked', 'read_only': True,
                'scientific_workers_launched': 0, 'scenarios': summaries}
    except Exception:
        raise ScenarioPreviewUnavailable(UNAVAILABLE) from None
