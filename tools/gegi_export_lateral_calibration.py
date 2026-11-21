"""Export the six previously evaluated GeGI lateral correction grids for Control."""

import argparse
import json
from pathlib import Path

import numpy as np

import gegi_cs_joint_lateral_holdout as cs
import gegi_joint_calibration as calibration
import gegi_joint_two_site_study as study
import scenario_workflow as W


EVIDENCE = W.ROOT/'.local/gegi-reconstruction-v1'
CENTER = W.ROOT/'.local/gegi-joint-two-site/gegi-center-calibration.npz'


def export(center, output):
    evaluation_path = EVIDENCE/'position-compatibility.json'
    partial_path = EVIDENCE/'partial-lateral-compatibility.json'
    evidence = W.read(evaluation_path)['candidates']
    partial = W.read(partial_path)['retained_candidates']
    manifest, centers, center_content_sha, center_archive_sha = calibration.load(center)
    if any(result['input_sha256']['calibration'] != center_archive_sha for result in (evidence, partial)):
        raise ValueError('Select the exact center calibration used in the retained lateral evaluation')
    cells = {tuple(cell) for cell in evidence['lateral_grid_cells']}
    inputs = study.cfd.scan.Inputs()
    evaluated = study.load_templates(inputs, cells, manifest['identity'], manifest['channels'], set(),
                                     lateral_captures=((cs.CAPTURE, cs.CAPTURE_SHA),))
    if (inputs.hashes != evidence['lateral_input_sha256'] or inputs.hashes != partial['lateral_training_input_sha256']
            or set(evaluated) != cells):
        raise ValueError('Archived lateral inputs or coverage differ from the saved standalone evaluations')
    corrections = {}
    for cell in sorted(cells):
        template = evaluated[cell]
        if template.lateral_correction_v_per_keV is None or not np.array_equal(template.center_v_per_keV, centers[cell].center_v_per_keV):
            raise ValueError(f'Evaluated lateral grid and portable center differ at {cell}')
        corrections[cell] = template.lateral_correction_v_per_keV
    provenance = {'kind': 'evaluated_archived_point_captures', 'training_input_sha256': inputs.hashes,
                  'evaluation_sha256': {p.name: W.sha(p) for p in (evaluation_path, partial_path)},
                  'source_sha256': {Path(file).name: W.sha(Path(file)) for file in
                                    (__file__, calibration.__file__, study.__file__, cs.__file__)}}
    saved, content_sha = calibration.save_lateral(output, center_manifest=manifest, center_content_sha=center_content_sha,
                                                  center_archive_sha=center_archive_sha, corrections=corrections,
                                                  provenance=provenance)
    loaded, adapted, loaded_content, archive_sha = calibration.load_lateral(output, manifest, centers, center_content_sha,
                                                                             center_archive_sha)
    if (loaded != json.loads(json.dumps(saved)) or loaded_content != content_sha
            or any(not np.array_equal(adapted[cell].lateral_correction_v_per_keV, value) for cell, value in corrections.items())
            or any(adapted[cell].center_v_per_keV is not centers[cell].center_v_per_keV for cell in centers)
            or W.sha(center) != center_archive_sha):
        raise ValueError('Portable lateral calibration failed its exact round-trip or center binding')
    return {'sha256': archive_sha, 'content_sha256': content_sha, 'supported_cells': sorted(cells),
            'center_only_cells': len(loaded['center_only_cells']), 'bytes': output.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--center', type=Path, default=CENTER)
    parser.add_argument('--output', type=Path, default=EVIDENCE/'gegi-lateral-calibration.npz')
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(W.ROOT/'.local') or args.output.exists():
        parser.error('Choose a new lateral calibration path inside the project .local directory')
    print(json.dumps(export(args.center, args.output), indent=2))


if __name__ == '__main__':
    main()
