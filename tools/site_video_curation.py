"""Keep two saved movie examples per detector in the generated public stage."""
from __future__ import annotations

import hashlib
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
RUN = '20260922_suite_v3'
MODELS = ('AK01', 'AK02', 'BEGe_GD32B_reference', 'BEGe_reference',
          'Bipolar_reference_3D', 'COAX_ANG2_reference', 'GeGI_3D', 'GeRC02',
          'ICPC_48A_reference', 'ICPC_large_reference', 'KL01_3D',
          'KMRC01_candidate', 'PPC_PONaMa1_reference', 'SAP16', 'SAP17',
          'SAP18_ring08_scenario', 'SAP22')
STEMS = ('01_single_event', '02_charge_cloud', '03_two_sites', '04_three_sites')
KEEP = ('01_single_event.mp4', '03_two_sites.mp4')
ALL = tuple(stem + extension for stem in STEMS for extension in ('.mp4', '.webm'))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def no_reparse(path):
    value = Path(path).lstat()
    require(not stat.S_ISLNK(value.st_mode) and
            not getattr(value, 'st_file_attributes', 0) & 0x400,
            'Reparse point is not an owned generated file: ' + str(path))


def checked_stage(stage):
    """Only the builder's explicit generated stage may be mutated."""
    stage = Path(stage).absolute()
    require(stage == (ROOT / '.local/site-build').absolute(),
            'Expected the generated .local/site-build stage')
    for path in (ROOT, ROOT / '.local', stage):
        no_reparse(path)
    require(stage.is_dir(), 'Generated stage is missing')
    return stage


def checked_file(stage, relative):
    relative = PurePosixPath(relative)
    require(not relative.is_absolute() and not any(p in ('', '.', '..') for p in relative.parts),
            'Unsafe generated path')
    path = stage
    for part in relative.parts:
        path /= part
        no_reparse(path)
    require(path.is_file(), 'Generated file is missing: ' + str(relative))
    return path


class References(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []; self.anchors = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get('id'):
            self.anchors.append(('id', values['id']))
        if tag == 'a' and values.get('name'):
            self.anchors.append(('name', values['name']))
        self.links.extend(value for key, value in attrs if key in ('href', 'src', 'poster') and value)


def references(text):
    parsed = References(); parsed.feed(text)
    return parsed


def curate_gallery(text):
    """Remove only the two declared extra movie cards and alternate encodings."""
    seen = []

    def card(match):
        block = match[0]
        if '<video' not in block:
            return block
        require(block.count('<video') == 1 and len(re.findall(r'<section\b', block)) == 1,
                'Unexpected nested movie card')
        sources = re.findall(r'<source\b[^>]*\bsrc="([^"]+)"[^>]*>', block)
        names = {PurePosixPath(source).name for source in sources}
        require(names and names <= set(ALL), 'Unexpected movie card sources')
        stems = {PurePosixPath(name).stem for name in names}
        require(len(stems) == 1, 'Movie card mixes different saved events')
        stem = stems.pop(); seen.append(stem)
        require(stem + '.mp4' in names, 'Movie card has no retained MP4')
        if stem + '.mp4' in KEEP:
            return re.sub(r'<source\b[^>]*\bsrc="[^"]+\.webm"[^>]*>', '', block)
        # These cards contain only a title, movie and its download link. Reject
        # new scientific figures/data instead of silently discarding them.
        outside = re.sub(r'<video\b.*?</video>', '', block, flags=re.S)
        require(not re.search(r'<(?:img|svg|table|script|figure)\b', outside),
                'Nonvideo evidence appeared in an extra movie card')
        require(all(PurePosixPath(urlsplit(url).path).name == stem + '.mp4'
                    for url in references(outside).links),
                'Extra movie card contains another destination')
        return ''.join('<span id="' + escape(value, quote=True) + '"></span>'
                       if kind == 'id' else '<a name="' + escape(value, quote=True) + '"></a>'
                       for kind, value in references(block).anchors)

    updated = re.sub(r'<section\b[^>]*>.*?</section>', card, text, flags=re.S)
    require(sorted(seen) in (sorted(STEMS), sorted(PurePosixPath(name).stem for name in KEEP)),
            'Unexpected saved movie card inventory')
    require(updated.count('<video') == 2, 'Expected two representative movie cards')
    require(references(text).anchors == references(updated).anchors,
            'Movie curation changed gallery anchors')
    return updated


def html_pages(stage):
    """Inspect links without traversing a junction or symlink."""
    pending = [stage]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            children = list(entries)
        for entry in children:
            path = Path(entry.path); no_reparse(path)
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
            elif path.suffix == '.html':
                yield path


def validate(site):
    """Portable read-only check of the selected public movie inventory."""
    site = Path(site); no_reparse(site)
    retained = []
    for model in MODELS:
        base = f'detectors/{model}/runs/{RUN}/presentation/'
        directory = checked_file(site, base + KEEP[0]).parent
        for path in directory.iterdir():
            no_reparse(path)
        require({path.name for path in directory.iterdir() if path.suffix in ('.mp4', '.webm')}
                == set(KEEP), 'Curated public movie inventory changed: ' + model)
        text = checked_file(site, f'detectors/{model}/gallery.html').read_text(encoding='utf-8')
        require(curate_gallery(text) == text, 'Curated public movie cards changed: ' + model)
        for name in KEEP:
            path = checked_file(site, base + name)
            retained.append({'path': base + name, 'bytes': path.stat().st_size, 'sha256': sha(path)})
    return {'kind': 'saved_video_curation_v1', 'retained': retained, 'new_simulations': 0}


def apply(stage):
    stage = checked_stage(stage)
    catalog = json.loads(checked_file(stage, 'models/catalog.json').read_text(encoding='utf-8'))
    require({row['id'] for row in catalog['detectors']} == set(MODELS) and
            len(catalog['detectors']) == len(MODELS), 'Unexpected movie detector inventory')
    changes = {}; removed = []; retained = []
    for model in MODELS:
        base = f'detectors/{model}/runs/{RUN}/presentation/'
        directory = checked_file(stage, base + KEEP[0]).parent
        for path in directory.iterdir():
            no_reparse(path)
        videos = {path.name for path in directory.iterdir() if path.suffix in ('.mp4', '.webm')}
        require(videos in (set(ALL), set(KEEP)), 'Unexpected staged movie inventory: ' + model)
        gallery = checked_file(stage, f'detectors/{model}/gallery.html')
        before = gallery.read_text(encoding='utf-8')
        changes[gallery] = curate_gallery(before)
        for name in sorted(videos):
            rel = base + name; path = checked_file(stage, rel)
            original = ROOT / 'Additional_Simulations/Visualization_3D' / rel
            for component in [original, *original.parents]:
                no_reparse(component)
                if component == ROOT:
                    break
            require(original.is_file() and sha(path) == sha(original),
                    'Retained local movie original differs: ' + rel)
            record = {'path': rel, 'bytes': path.stat().st_size, 'sha256': sha(path)}
            (retained if name in KEEP else removed).append(record)
    removed_paths = {row['path'] for row in removed}
    for page in html_pages(stage):
        text = changes.get(page)
        if text is None:
            text = page.read_text(encoding='utf-8')
        for url in references(text).links:
            parts = urlsplit(url)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            target = (page.parent / unquote(parts.path)).resolve()
            require(not target.is_relative_to(stage) or target.relative_to(stage).as_posix() not in removed_paths,
                    'Another page still references a retired movie: ' + page.relative_to(stage).as_posix())
    # Every candidate and destination has been checked before the first write.
    for path, text in changes.items():
        data = text.encode('utf-8')
        if path.read_bytes() != data:
            path.write_bytes(data)
    for row in removed:
        path = checked_file(stage, row['path'])
        require(sha(path) == row['sha256'], 'Movie changed during curation')
        path.unlink()
    return {'kind': 'saved_video_curation_v1', 'retained': retained, 'removed': removed,
            'removed_bytes': sum(row['bytes'] for row in removed), 'new_simulations': 0}
