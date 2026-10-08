"""Inventory every published HTML route and static action without a browser.

Usage: python tools/audit_site_navigation.py --site docs --output .local/navigation.json
JavaScript-dependent links and external URLs are inventoried, never declared
executed or reachable by this static audit. No Download/Save As is triggered.
"""
import argparse
import hashlib
import json
import posixpath
import re
from collections import Counter
from pathlib import Path

from check_site import Links, reference_kind, resolve_reference
from site_routes import registry


class NavigationLinks(Links):
    def __init__(self):
        super().__init__()
        self.regions, self.navigation_regions = [], []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'nav':
            name = values.get('aria-label', values.get('id', 'Unlabelled nav'))
            self.regions.append(name)
            self.navigation_regions.append(name)
        begin = len(self.references)
        super().handle_starttag(tag, attrs)
        for reference in self.references[begin:]:
            reference['region'] = self.regions[-1] if self.regions else 'Content'

    def handle_endtag(self, tag):
        if tag == 'nav' and self.regions:
            self.regions.pop()


def audit(site):
    """Account for disconnected pages independently of the link graph."""
    site = Path(site).resolve()
    records = registry(site)
    parsed, hashes = {}, {}
    for path in records:
        raw = (site / path).read_bytes()
        parser = NavigationLinks()
        parser.feed(raw.decode('utf-8-sig'))
        parsed[path] = parser
        hashes[path] = hashlib.sha256(raw).hexdigest()
    counts, pages, failures = Counter(), [], []
    for path, record in records.items():
        parser = parsed[path]
        references = []
        for reference in parser.references:
            resolved = resolve_reference(path, reference['url'])
            row = dict(reference, kind=reference_kind(reference, resolved),
                       scope='internal' if resolved else 'external',
                       resolution='static_only')
            if resolved:
                target = resolved['path']
                if (site / target).is_dir():
                    target = posixpath.join(target, 'index.html')
                row.update(resolved, path=target,
                           target_exists=(site / target).is_file())
                row['resolved_url'] = (target + ('?' + resolved['query'] if resolved['query'] else '')
                                       + ('#' + resolved['fragment'] if resolved['fragment'] else ''))
                if target in records:
                    row['target_role'] = records[target]['role']
                if row['kind'] == 'page_navigation' and target == path and resolved['fragment']:
                    row['kind'] = 'fragment'
                fragment = resolved['fragment'].split(':~:text=', 1)[0]
                if fragment and target in parsed:
                    row['fragment_exists'] = fragment in parsed[target].anchors
                    counts['fragment_references'] += 1
                if not row['target_exists'] or row.get('fragment_exists') is False:
                    failures.append(dict(page=path, url=reference['url'],
                                         target_exists=row['target_exists'],
                                         fragment_exists=row.get('fragment_exists')))
            else:
                row['external_status'] = 'not_retrieved'
            counts[row['scope'] + '_' + row['kind']] += 1
            references.append(row)
        text = (site / path).read_text(encoding='utf-8-sig')
        operations = Counter(re.findall(r'location\.(?:replace|assign)|history\.(?:replaceState|pushState)|\.href\s*=|\bfetch\s*\(', text))
        literal_fetches = []
        for match in re.finditer(r'''\bfetch\s*\(\s*(["'])([^"']+)\1''', text):
            url = match.group(2)
            resolved = resolve_reference(path, url)
            literal_fetches.append(dict(url=url, status='not_executed',
                                       resolved=resolved,
                                       static_target_exists=(site / resolved['path']).is_file() if resolved else None))
        pages.append(dict(record, html_sha256=hashes[path],
                          navigation_regions=parser.navigation_regions,
                          references=references,
                          dynamic=dict(status='not_executed', script_blocks=parser.script_blocks,
                                       marked_elements=parser.dynamic,
                                       source_navigation_operations=dict(operations),
                                       literal_fetch_resources=literal_fetches)))
    for path, record in records.items():
        parent, seen = record['parent_id'], {path}
        while parent:
            if parent not in records:
                failures.append(dict(page=path, missing_parent=parent))
                break
            if parent in seen:
                failures.append(dict(page=path, parent_cycle=parent))
                break
            seen.add(parent)
            parent = records[parent]['parent_id']
    return dict(schema_version=1, html_pages=len(pages),
                role_counts=dict(Counter(row['role'] for row in pages)),
                reference_counts=dict(sorted(counts.items())),
                limits=['Static href/src/poster and fragment resolution only.',
                        'JavaScript transitions, refresh/back and external retrieval require separate acceptance.',
                        'Only page ownership is checked for cycles; valid navigation may cross-link.'],
                failures=failures, pages=pages)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, default=Path(__file__).resolve().parents[1] / 'docs')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.site)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'pages'}, indent=2))
    if report['failures']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
