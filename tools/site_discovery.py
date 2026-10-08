"""Search metadata for maintained landing pages; never touch saved science bundles."""
import json
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

SITE_URL = 'https://kunming-cn.github.io/END2END_Ge_Simulation/'
PROJECT_NAME = 'GeSignal'
PROJECT_TITLE = 'GeSignal — HPGe Radiation-to-Readout Simulation'
SITEMAP = 'sitemap.xml'
# Public ownership proof supplied by the owner's Search Console property.
# Retain after verification; it is neither a credential nor a tracking script.
GOOGLE_VERIFICATION = 'wFWyU8uT-Mpj18hGTUOsVugVXg5AlW6TDcfRP2r--RE'
SOFTWARE_LICENSE = Path(__file__).resolve().parents[1] / 'LICENSE'
LEGACY_WITHOUT_SUPPORT = {'186b9008a790683486598e48e6b86ede2b1d9119008c191cc5fed32c955f6afc'}
# Exact deployed predecessor used an implicit head. Search Console rejected it;
# allow only this hash-bound snapshot while the publisher stages the repair.
LEGACY_IMPLICIT_HEAD = {'c257d2f120d5d446664f049af057f085baa2e389fe9b45ba19466bc7d794a858'}
NS = 'http://www.sitemaps.org/schemas/sitemap/0.9'
LANDINGS = {
    'index.html': 'Saved HPGe detector engineering simulations: Geant4/remage radiation deposits, SSD charge transport and electronics readout. Browse results or choose a local workflow.',
    'guide.html': 'Windows setup and supported local HPGe simulation workflows. Saved browsing, new radiation runs and private-input engineering examples have separate requirements.',
    'learn/index.html': 'Follow radiation deposits through SSD electron and hole transport, preamplifier, shaping and peak ADC. Saved engineering examples retain units and limitations.',
    'detectors/index.html': 'Explore 17 saved HPGe detector models, contacts and original configurations. Viewing a model does not establish LBNL execution support or experimental validation.',
    'results/index.html': 'Browse saved Cs137 campaigns and bounded HPGe engineering examples. Deposited energy, reconstructed energy, zero events and unavailable responses remain separate.',
    'results/cs137-1m/index.html': 'Saved AK02 and SAP22 Cs137 engineering results, with one million initial decays per detector. No measured-spectrum fit or calibrated charge-collection claim.',
    'results/cs137-10k/index.html': 'Saved four-case Cs137 10K engineering results: AK02, SAP22, GeRC02 Li50min and KMRC01 candidate. Events, spectra, charge/readout and complete ledgers retain every initial decay.',
    'methods/index.html': 'HPGe simulation methods, original model provenance and numerical, calibration and experimental limitations of the saved engineering results.',
    'scenarios/lbnl-cs137/index.html': 'Nominal LBNL cryostat with shared Cs137, Am241 and Ba133 local workflows, compatible detector choices and saved batch analysis. Legacy AK02/SAP22 CLI support and model viewing are separate.',
}

# The exact preceding saved snapshot must validate before normal restructuring.
# This permits only its two known old descriptions. check_site still binds the
# entire snapshot to this build digest; rehashed edits cannot retain admission.
HISTORICAL_DESCRIPTIONS = {
    '7b51300b9a439f311c33b75219758b07fb73e27ad6dbe9ff6ebb5fd300521ca3': {
        'results/cs137-10k/index.html': 'Earlier saved AK02 and SAP22 10k Cs137 engineering campaign, including event and response viewers. This is separate from the current million-decay campaign.',
        'scenarios/lbnl-cs137/index.html': 'Nominal LBNL Cs137 scenario and AK02/SAP22 execution boundaries, source assumptions and detector selection. Additional models require independent integration.',
    },
    '01dfa893e13a2b64652eb2ef86b2b24b4fe91e8a9b7a50b1156c183a75d0f85b': {
        'scenarios/lbnl-cs137/index.html': 'Nominal LBNL scenario with four Control configurations: AK02, SAP22, GeRC02 Li50min and KMRC01 candidate. Legacy AK02/SAP22 CLI support and model viewing are separate.',
    },
}


def landing_descriptions(site):
    site = Path(site)
    descriptions = dict(LANDINGS)
    catalog = site / 'models/catalog.json'
    if catalog.is_file():
        for item in json.loads(catalog.read_text(encoding='utf-8'))['detectors']:
            ident = item['id']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', ident):
                raise ValueError('Unsafe discovery detector ID')
            descriptions[f'detectors/{ident}/index.html'] = (
                f'{ident} HPGe model: saved geometry, contact information, field and response galleries, '
                'original configuration and provenance. Model viewing is not experimental validation.')
    return {path: description for path, description in sorted(descriptions.items())
            if (site / path).is_file()}


def canonical(path):
    return SITE_URL + ('' if path == 'index.html' else path)


def sitemap_bytes(paths):
    rows = ''.join(f'  <url><loc>{escape(canonical(path))}</loc></url>\n' for path in sorted(paths))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="{NS}">\n'
            + rows + '</urlset>\n').encode('utf-8')


def assemble(site):
    """Called only by the saved-data publisher after maintained pages are assembled."""
    site = Path(site)
    descriptions = landing_descriptions(site)
    for path, description in descriptions.items():
        page = site / path
        html = page.read_text(encoding='utf-8')
        # These pages are maintained sources, not hash-bound result presentations.
        html = re.sub(r'<meta\s+name="description"[^>]*>', '', html)
        html = re.sub(r'<link\s+rel="canonical"[^>]*>', '', html)
        html = re.sub(r'<meta\s+name="google-site-verification"[^>]*>', '', html)
        html = html.replace('END2END Ge Simulation', 'GeSignal · HPGe detector simulation')
        if not re.search(r'<head(?:\s[^>]*)?>', html, re.I):
            html, opened = re.subn(r'(<html(?:\s[^>]*)?>)', r'\1<head>', html, count=1, flags=re.I)
            html, closed = re.subn(r'(<body(?:\s[^>]*)?>)', r'</head>\1', html, count=1, flags=re.I)
            if opened != 1 or closed != 1:
                raise ValueError('Maintained discovery page cannot form an explicit head')
        if path == 'index.html':
            html = re.sub(r'<title>.*?</title>', '<title>' + escape(PROJECT_TITLE) + '</title>', html, count=1)
        tags = (f'<meta name="description" content="{escape(description, quote=True)}">'
                f'<link rel="canonical" href="{canonical(path)}">')
        if path == 'index.html':
            tags += f'<meta name="google-site-verification" content="{GOOGLE_VERIFICATION}">'
        if '<title>' not in html:
            raise ValueError(f'Maintained discovery page has no title: {path}')
        html = html.replace('<title>', tags + '<title>', 1)
        page.write_text(html, encoding='utf-8', newline='\n')
    (site / SITEMAP).write_bytes(sitemap_bytes(descriptions))
    (site / 'LICENSE').write_bytes(SOFTWARE_LICENSE.read_bytes())


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.descriptions, self.canonicals, self.verifications = [], [], []
        self.verification_in_head = []
        self.head_closed = self.body_started = False
        self.head_open = False

    def handle_starttag(self, tag, attrs):
        if tag == 'head':
            self.head_open = True
        if tag not in {'html', 'head', 'title', 'meta', 'link', 'style', 'script',
                       'base', 'noscript', 'template'}:
            self.body_started = True
        values = dict(attrs)
        if tag == 'meta' and values.get('name') == 'description':
            self.descriptions.append(values.get('content'))
        if tag == 'link' and values.get('rel') == 'canonical':
            self.canonicals.append(values.get('href'))
        if tag == 'meta' and values.get('name') == 'google-site-verification':
            self.verifications.append(values.get('content'))
            self.verification_in_head.append(self.head_open and not self.head_closed and not self.body_started)

    def handle_endtag(self, tag):
        if tag == 'head':
            self.head_closed = True
            self.head_open = False


def validate(site):
    """Optional on historical snapshots; strict once the sitemap is installed."""
    site = Path(site)
    if not (site / SITEMAP).exists():
        if (site / 'models/catalog.json').is_file() or (site / 'LICENSE').is_file():
            raise ValueError('Discovery sitemap is missing from a current publication')
        return
    descriptions = landing_descriptions(site)
    manifest = site / 'site-manifest.json'
    build_id = json.loads(manifest.read_bytes()).get('build_id') if manifest.is_file() else None
    historical = HISTORICAL_DESCRIPTIONS.get(build_id, {})
    has_license = (site / 'LICENSE').is_file()
    if has_license and (site / 'LICENSE').read_bytes() != SOFTWARE_LICENSE.read_bytes():
        raise ValueError('Published software LICENSE differs from maintained source')
    # Full old snapshots may be validated before generation/rollback. New full
    # snapshots and small assembled fixtures must carry the ownership proof.
    legacy = not has_license and build_id in LEGACY_WITHOUT_SUPPORT
    if (site / 'models/catalog.json').is_file() and not has_license and not legacy:
        raise ValueError('Published software LICENSE is missing')
    raw = (site / SITEMAP).read_bytes()
    tree = ET.fromstring(raw)
    urls = [node.text for node in tree.findall(f'{{{NS}}}url/{{{NS}}}loc')]
    expected = [canonical(path) for path in sorted(descriptions)]
    if tree.tag != f'{{{NS}}}urlset' or urls != expected or raw != sitemap_bytes(descriptions):
        raise ValueError('Discovery sitemap differs from maintained landing URLs')
    for path, description in descriptions.items():
        parser = Metadata()
        parser.feed((site / path).read_text(encoding='utf-8'))
        accepted = ([description], [historical[path]]) if path in historical else ([description],)
        if parser.descriptions not in accepted or parser.canonicals != [canonical(path)]:
            raise ValueError(f'Discovery metadata differs: {path}')
        expected = [GOOGLE_VERIFICATION] if path == 'index.html' and has_license else []
        if parser.verifications != expected:
            raise ValueError(f'Google ownership metadata differs: {path}')
        accepted_positions = [[True] * len(expected)]
        if path == 'index.html' and build_id in LEGACY_IMPLICIT_HEAD:
            accepted_positions.append([False])
        if parser.verification_in_head not in accepted_positions:
            raise ValueError(f'Google ownership metadata is outside the head: {path}')
