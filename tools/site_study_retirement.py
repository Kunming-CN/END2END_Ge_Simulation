"""Retire three explicitly approved public studies; retain local science originals."""
from __future__ import annotations

import hashlib
from html import escape
import json
from pathlib import Path
import posixpath

from site_video_curation import checked_stage, checked_file, no_reparse, require

RECEIPT = 'retired-studies.json'
# Exact completed f4422554 site inputs, before approved public cleanup.
INVENTORY = {
    'examples/pipeline.html': (9810997, 'ab2f473328e03fadbc4036613b37993be46254d5d5770f976b152636efec3760'),
    'examples/data.json': (9766838, 'dfc87b1814fb1a0e2c2324469f5e81a8383e56c00969ce4e3148425fab8d08d6'),
    'examples/pipeline-display.json': (1677, '92e554fe166f78603de56df185630e3068729bc9943df1c86d8c1dd6706d6cf9'),
    'examples/gamma-native/gamma.html': (5470913, 'aed4753c96e6a9a9137e8825a072cbe74fed522b79f110b4e2e3224dbd045c21'),
    'examples/gamma-native/data.json': (5412764, 'c96bec9da168cdd07c23b8748c0d3717bf9ace77f430246e38f7a23fd4a11f49'),
    'examples/gamma-native/publication.json': (24399, 'dfb949f6cd5f33d058c43a81e846974610ba6f7e8c5dabe0732f7dcb24b2a1bb'),
    'examples/gamma-native/AK02-signals.csv': (836427, '3761830408226e31fe71693284d1518c5bcf5f5575655b0b1244be5ebd94b15a'),
    'examples/gamma-native/SAP22-signals.csv': (7699, '96b4ca3da9a8d58415af4b12a559307565a6e9157cc9a963088c8263ee1a9241'),
    'examples/gegi/index.html': (2534, '0c3525970d11416f800c5836c07138b57b83f666631c26ab580ed91fc839cee2'),
    'examples/gegi/publication.json': (2348, '8ee7d5f410e26253450919abd685235b3d6847e2710de8591b8bfa12dff82017'),
    'examples/gegi/selected-channel.json': (186617, '64b8cc598a92c3dfd0117647275e03c62610f028bef45f085600148b6013911d'),
    'examples/gegi/summary.json': (840148, '16dd34ebb1b8effff7975a36fb99c7dcedc50bdcc3a1905a98dfbdad5ebacba8'),
}
STUDIES = {
    'examples/pipeline.html': ('Earlier 200-primary gamma example', 'spectra/pipeline.html',
        'six selected Cs137 signals from the completed four-case 10K study',
        ('source-label model-select event-select previous next first-deposit zero-deposit largest-deposit '
         'run-settings selection-note error panels event-heading badges edep eind erec event-facts '
         'event-warning event-details event-json event-key geometry-heading geometry geometry-caption '
         'deposit-summary deposits charge-plot charge-caption current-plot current-caption preamp-plot '
         'shaped-plot peak-caption truth-legend rec-legend histogram counts spectrum-warning '
         'calibration-facts calibration-json limitations provenance references export-id pipeline-data').split()),
    'examples/gamma-native/gamma.html': ('Earlier 40-primary cryostat gamma example', 'spectra/pipeline.html',
        'six selected Cs137 signals from the completed four-case 10K study',
        ('page-navigation site-navigation-style total-count processed-count positive-count zero-count '
         'hero-note model-select event-select previous next run-settings selection-note error panels '
         'event-heading badges edep eind erec event-facts event-warning event-details event-json '
         'deposit-details deposit-summary deposits material-details material-content endpoint-details '
         'endpoint-summary endpoint-content charge-plot charge-caption current-plot current-caption '
         'preamp-plot preamp-caption shaped-plot peak-caption calibration-heading calibration-facts '
         'calibration-details calibration-json census-heading census-table limitations provenance-details '
         'provenance-json export-id gamma-data').split()),
    'examples/gegi/index.html': ('Earlier GeGI two-position study', 'results/gegi-campaign/index.html',
        'current saved GeGI conditional image and signal study',
        ['page-navigation', 'site-navigation-style']),
}


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode('utf-8')


def stub(entry):
    title, destination, label, anchors = STUDIES[entry]
    href = posixpath.relpath(destination, posixpath.dirname(entry))
    spans = ''.join('<span id="' + escape(anchor, quote=True) + '"></span>' for anchor in anchors)
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex"><title>' + escape(title) + ' · retired</title>'
        '<body><main data-retired-study="public-cleanup-v1"><h1>' + escape(title) + '</h1>'
        '<p>This small public study has been retired. Its original scientific records remain in the local workspace.</p>'
        '<p><a href="' + escape(href, quote=True) + '">Open the ' + escape(label) + '</a>. '
        'This is a separate dataset; event IDs and selections do not carry over.</p>' + spans + '</main></body></html>\n').encode('utf-8')


def receipt():
    return {'kind': 'public_study_retirement_v1', 'new_simulations': 0,
            'original_local_science_modified': False,
            'former_public_files': {path: {'bytes': count, 'sha256': digest}
                                    for path, (count, digest) in INVENTORY.items()},
            'entry_pages': {entry: {'current_dataset': data[1], 'bytes': len(stub(entry)),
                                   'sha256': hashlib.sha256(stub(entry)).hexdigest()}
                            for entry, data in STUDIES.items()}}


def is_retired(site, entry):
    """A folder's existence alone no longer establishes an active study."""
    if not (Path(site) / RECEIPT).is_file():
        return False
    record = validate(site)
    return entry in record['entry_pages']


def validate(site):
    site = Path(site)
    require(checked_file(site, RECEIPT).read_bytes() == encoded(receipt()),
            'Retired study receipt changed')
    for path in INVENTORY:
        if path in STUDIES:
            require(checked_file(site, path).read_bytes() == stub(path), 'Retired entry page changed: ' + path)
        else:
            candidate = site / path
            require(not candidate.exists() and not candidate.is_symlink(),
                    'Retired study payload reappeared: ' + path)
    for folder in ('examples/gamma-native', 'examples/gegi'):
        parent = site / folder; no_reparse(parent)
        expected = {'gamma.html'} if folder.endswith('gamma-native') else {'index.html'}
        require({path.name for path in parent.iterdir()} == expected,
                'Unexpected retired study directory contents: ' + folder)
    return receipt()


def apply(stage):
    stage = checked_stage(stage)
    if (stage / RECEIPT).exists():
        return validate(stage)
    # Full fixed inventory first: a partial or changed derivative is preserved.
    paths = {}
    for relative, (count, digest) in INVENTORY.items():
        path = checked_file(stage, relative)
        require(path.stat().st_size == count and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                'Unapproved former public study bytes: ' + relative)
        paths[relative] = path
    for folder in ('examples/gamma-native', 'examples/gegi'):
        expected = {Path(path).name for path in INVENTORY if str(Path(path).parent).replace('\\', '/') == folder}
        require({path.name for path in (stage / folder).iterdir()} == expected,
                'Unexpected former public study directory contents: ' + folder)
    for relative, path in paths.items():
        if relative in STUDIES:
            path.write_bytes(stub(relative))
        else:
            path.unlink()
    (stage / RECEIPT).write_bytes(encoded(receipt()))
    return validate(stage)
