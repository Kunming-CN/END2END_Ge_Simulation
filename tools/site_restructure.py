"""Generate a small stable information architecture over an already-built static site.

This is presentation only. It never runs physics and never rewrites scientific
campaign artifacts. Existing report/detector URLs remain valid.
"""
import json
import site_detector_pages as detector_pages
import re
from html import escape
from pathlib import Path
from site_detector_pages import apply as apply_detector_pages

from site_routes import (PRIMARY as DISPLAY_PRIMARY, page_navigation,
                         primary_navigation, dataset_navigation as dataset_context,
                         DATASETS, footer as display_footer)
PRIMARY = tuple(label for path, label in DISPLAY_PRIMARY)
STYLE = """
:root{font:16px/1.55 system-ui;color:#173047;background:#f6f8fa}
*{box-sizing:border-box}body{margin:0}.wrap{max-width:1120px;margin:auto;padding:24px}
a{color:#075e9b}.top{display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.top nav{display:flex;gap:8px;flex-wrap:wrap}.top nav a,.button{padding:10px 14px;border-radius:8px;background:#edf3f7;text-decoration:none}
.hero{padding:44px 0 24px;max-width:820px}.hero h1{overflow-wrap:anywhere;font-size:clamp(2rem,5vw,3.4rem);line-height:1.05;margin:.2em 0}
.muted{color:#526575}.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:22px 0}
.card,.panel{background:#fff;border:1px solid #d7e0e7;border-radius:12px;padding:20px}.card h2{margin-top:0}
.card a{font-weight:700}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
table{border-collapse:collapse;width:100%;background:white}th,td{padding:9px;border-bottom:1px solid #dce3e8;text-align:left}
.preview{margin:12px 0}.preview img,.preview svg{width:100%;height:180px;object-fit:contain}.preview figcaption{font-size:.82rem;color:#526575}.legend span{display:inline-block;width:12px;height:12px;margin-right:4px}iframe{max-width:100%}td,th{overflow-wrap:anywhere}.tag{display:inline-block;padding:3px 8px;border-radius:999px;background:#edf3f7;font-size:.85rem;margin-right:5px}
footer{margin-top:32px;padding-top:18px;border-top:1px solid #ccd6de;color:#526575}
summary{cursor:pointer}
a:focus-visible,summary:focus-visible{outline:3px solid #087b89;outline-offset:4px}
@media(max-width:760px){.cards,.grid{grid-template-columns:1fr}.wrap{padding:16px}.hero{padding-top:26px}}
"""
def require(ok,msg):
    if not ok: raise ValueError(msg)

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def navigation(up='', *, page_path=None):
    """Task routes; selecting a saved view belongs to its dataset context."""
    if page_path is not None:
        return primary_navigation(page_path)
    links=DISPLAY_PRIMARY
    return '<nav aria-label="Primary" style="display:flex;gap:8px;flex-wrap:wrap">'+''.join(
        f'<a href="{up}{path}" style="padding:8px 10px">{label}</a>' for path,label in links)+'</nav>'

def dataset_navigation(dataset,up='', *, model=None, model_label=None, current_path=None):
    """Name one saved dataset and link only to its existing views."""
    require(dataset in DATASETS,'Unknown saved dataset')
    return dataset_context(dataset,current_path or DATASETS[dataset][1],model,model_label)

def write_page(path,title,body,depth=0,*,fold_footer=False,page_path=None,dataset=None,model=None,model_label=None,nav_html=None,extra_style=''):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    up='../'*depth
    page_path=page_path or '/'.join(path.parts[-(depth+1):])
    nav=nav_html if nav_html is not None else page_navigation(page_path,dataset,model,model_label)
    footer=display_footer(page_path)
    if fold_footer:
        footer=footer.replace('<footer>','<footer><details><summary>More project resources</summary><p>',1).replace('</footer>','</p></details></footer>',1)
    html=(f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
          f'<meta name="viewport" content="width=device-width,initial-scale=1">'
          f'<title>{escape(title)}</title><style>{STYLE}{extra_style}</style></head><body><main class="wrap">'
          f'<header class="top">{nav}</header>{body}{footer}</main></body></html>')
    path.write_text(html,encoding='utf-8',newline='\n')

def detector_cards(catalog):
    rows=[]
    for item in catalog['detectors']:
        ident=item['id']; require(re.fullmatch(r'[A-Za-z0-9_-]+',ident) is not None,'Unsafe detector ID')
        kind=detector_pages.TYPE_LABELS[ident];poster=f'{ident}/runs/{detector_pages.RUN}/01_geometry.png'
        capability=detector_pages.catalog_model_summary(ident)
        assembly='gegi' if ident=='GeGI_3D' else 'lbnl' if capability['assembly_href'] else 'larger'
        status=detector_pages.model_status(item)
        name=detector_pages.model_name(ident)
        rows.append(f'<article class="card" data-model="{escape(ident)}" data-geometry="{escape(kind,quote=True)}" data-assembly="{assembly}" data-status="{status}"><a href="{escape(ident)}/index.html" aria-label="{escape(name)} detector overview">'
                    f'<img loading="lazy" style="width:100%;height:220px;object-fit:contain" src="{escape(poster)}" '
                    f'alt="{escape(ident)} {escape(kind)}, saved geometry"></a>'
                    f'<h2><a href="{escape(ident)}/index.html">{escape(name)}</a></h2><p><code>{escape(ident)}</code></p><p>{escape(kind)}</p>'
                    f'<p><strong>{escape(capability["label"])}</strong></p><p>{escape(capability["detail"])}</p>'
                    f'<p>Model status: {escape(item.get("status","saved model"))}. Public studies and validation limits are listed on its overview.</p></article>')
    return ''.join(rows)

HOME_STYLE='''
body{background:#f7fafb}.wrap{max-width:1180px}.top{padding-bottom:16px;border-bottom:1px solid #d7e0e7}
.top>a{text-decoration:none;font-size:21px;color:#173047}.top nav a{background:transparent;font-size:14px;padding:8px}
.home-hero{padding:30px 0 20px;max-width:900px}.home-hero .eyebrow{font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:#526575;margin:0 0 12px}
.home-hero h1{font-size:clamp(2rem,4vw,3rem);letter-spacing:-.035em;line-height:1.12;margin:0 0 16px;color:#102d40}
.home-hero .lead{font-size:18px;line-height:1.6;max-width:760px;margin:0;color:#405d6c}
.home-actions{display:flex;align-items:center;flex-wrap:wrap;gap:12px 20px;margin:24px 0 10px}
.home-actions a{font-weight:700}.home-actions .button{background:#076b79;color:white}
.home-feature{display:grid;grid-template-columns:1fr 1.2fr;gap:28px;align-items:center;margin:22px 0 32px}.home-feature h2{font-size:27px;line-height:1.2;margin:8px 0 14px}.home-feature figure{margin:0}.home-feature img{width:100%;height:auto}.home-feature figcaption{font-size:13px;color:#526575}.home-objects{grid-template-columns:repeat(3,minmax(0,1fr));gap:28px}.home-objects h2{font-size:20px}.home-objects p{font-size:15px}.home-scope{margin:18px 0 0;font-size:15px;color:#405d6c}footer{font-size:13px;margin-top:24px}
@media(max-width:760px){.home-feature,.home-objects{grid-template-columns:1fr}.top{gap:10px}.home-hero{padding-top:24px}.home-hero .lead{font-size:16px}}
'''


def homepage(commercial=False):
    featured = ''
    if commercial:
        featured = '''<section class="home-feature panel" aria-labelledby="featured-study-title">
<div><p class="eyebrow">Featured study</p><h2 id="featured-study-title">GeGI shared readout · 25 × 250 ms</h2>
<p>Cs-137 and Co-60 archived single-isotope histories feed shared 34-electrode electronics. The 25 independent windows total 6.25 s, with a reset between windows.</p>
<p>40,979 accepted energies from 53,033 qualified triggers; image peaks depend on the source-plane prior.</p>
<p><a id="main-result-link" href="results/gegi-shared-readout/index.html">Read the study, spectra and images →</a></p></div>
<figure><a href="results/gegi-shared-readout/index.html"><img width="2340" height="1155" src="results/gegi-digital/simultaneous-spectrum-and-images.png" alt="Saved combined energy spectrum and source-plane maps for the GeGI archived-library study"></a><figcaption>Saved spectrum and reconstructed source-plane maps.</figcaption></figure></section>'''
    return '''<section class="home-hero"><p class="eyebrow">GeSignal · END2END_Ge_Simulation</p>
<h1>From gamma-ray deposits to detector readout</h1>
<p class="lead">Explore radiation transport, charge induction and readout in high-purity germanium (HPGe) detectors. Follow saved studies or run and analyze your own simulation.</p>
<div class="home-actions" id="reader-paths-title"><a class="button" href="results/index.html">Browse research results</a>
<a href="learn/signals/index.html">Start with one signal</a><a href="guide.html">Run locally</a></div></section>''' + featured + '''
<section class="home-objects grid" aria-label="Models, assemblies and studies">
<article><h2>Detector models</h2><p>Browse 17 models with their geometry, fields, signals and original parameters. Reference, candidate and scenario qualifications stay with each model.</p><a href="detectors/index.html">Explore detector models →</a></article>
<article><h2>Cryostat assemblies</h2><p>Ten configurations fit the nominal LBNL cryostat. GeGI has its own assembly; six catalog models require a larger cryostat.</p><a href="assemblies/index.html">Compare the two assemblies →</a></article>
<article><h2 id="signal-chain-title">Research and learning</h2><p>Each study keeps its own source, model variant and event identities. Learn how deposited energy differs from energy inferred by the readout.</p><a href="learn/index.html">Learn the signal chain →</a></article></section>
<span id="pipeline-example"></span><span id="native-cs137-10k"></span><span id="current-ring-10k"></span>'''


READER_STYLE = '''
.top{padding-bottom:16px;border-bottom:1px solid #d7e0e7}
.top #page-navigation{width:100%;margin:0}
.reader-intro{padding:24px 0 14px;max-width:760px}
.reader-intro h1{font-size:clamp(2rem,4vw,2.75rem);line-height:1.1;margin:0 0 10px}
.reader-intro p{margin:0;color:#405d6c}
.reader-page .panel{margin:0 0 24px}.study-cards{margin:16px 0 32px;align-items:stretch}.study-cards h2{font-size:23px;line-height:1.3}.study-cards dl{font-size:15px}.study-cards dt{font-weight:700;margin-top:10px}.study-cards dd{margin:2px 0 0}.topic-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 28px}.topic-grid h3{font-size:18px;margin:12px 0 6px}.topic-grid p{margin-top:0}@media(max-width:760px){.topic-grid{grid-template-columns:1fr}}
.reader-page .panel h2:first-child{margin-top:0}
.reader-page details{padding:10px 0}
.reader-page .panel>details+details{border-top:1px solid #d7e0e7}
.reader-page summary{font-weight:650;padding:6px 0}
.reader-page .study-list{list-style:none;padding:0;margin:8px 0 0}
.reader-page .study-list>section{border-top:1px solid #d7e0e7;padding:12px 0}
.reader-page .study-list h3,.reader-page .study-list p{margin:4px 0}
.reader-page figcaption{color:#405d6c;font-size:.92rem}
.reader-page figure img{display:block;max-width:100%;margin-inline:auto}
.reader-page [tabindex="0"]{max-width:100%}
#gegi-data-methods{background:#edf6f7;border-radius:8px;padding:14px 18px;margin:20px 0}
#gegi-data-methods h3,#gegi-data-methods p{margin:0}
#gegi-data-methods p+p{margin-top:6px}
.gegi-result-figure{margin:16px 0}.gegi-result-figure figcaption{margin-top:8px}
.gegi-result-figure img{width:100%;height:auto}
.gegi-result-summary{max-width:900px}
.gegi-result-summary p{margin:8px 0}
'''

def write_methods(site):
    methods='''<div class="reader-page"><header class="reader-intro"><h1>Simulation methods</h1>
<p>How radiation deposits become electrode signals, readout energies and interaction candidates.</p></header>
<section class="panel"><h2>Radiation transport</h2><p>Geant4/remage records deposited energy E<sub>dep</sub> in keV, positions in mm, creation and deposition times in ns, and original primary and track identities. A primary may miss the crystal, interact more than once or produce delayed daughter deposits. Keep relevant deposits of one primary and pulse group together.</p></section>
<section class="panel"><h2>Charge transport and induction</h2><p>SolidStateDetectors.jl transports electrons and holes through the detector electric field. Electrode weighting potentials determine signed induced charge through the Shockley–Ramo relation. Charge in fC and current in nA belong to this stage; deposition time is not carrier drift time. Incomplete collection, guard contacts and numerical termination flags stay with the response.</p></section>
<section class="panel"><h2>Two readout branches</h2><div class="grid">
<article><h3>LBNL analog electronics</h3><p>Signed current passes through fixed wiring, a preamplifier and analog shaper. A peak ADC (analog-to-digital converter) records one peak code. The analog numerical time grid is separate from a waveform digitizer.</p><p><a href="../learn/signals/index.html">Follow six saved 10K signals →</a></p></article>
<article><h3>GeGI digitized strip readout</h3><p>The nominal digital branch samples preamplifier voltages on 34 electrodes. Fast neighboring-strip responses inform position, while the slow branch measures energy. X and Y are two measurements of the same deposited charge; their energies are not added.</p><p>Shared-readout studies combine overlapping signals before common noise, digitization and triggering. Their source history, clock organization and reset conditions belong to each study.</p><p><a href="../results/gegi-shared-readout/index.html">25 × 250 ms archived-library study →</a></p></article></div>
<p>Voltages are in V and reconstructed energy E<sub>rec</sub> is in keV. Independent synthetic injections provide a fixed calibration shared across events. Gain is never chosen separately to match each event's E<sub>dep</sub>. Thresholds, clipping or rejection can leave energy unavailable; an unknown response is not zero.</p></section>
<section class="panel" id="gegi-acquisition-method"><h2>Interaction candidates and Compton imaging</h2><p>A two-strip trigger may admit multiple pairings and interaction orders. Permitted Compton cones retain their assigned weights. A source-plane reconstruction then combines them under a stated spatial prior. Uniform area gives equal cells equal initial weight; uniform solid angle weights their angular area from the detector center. Weight without a usable projection remains unresolved.</p><p>Signal-derived positions and source truth have separate roles. Programmed source coordinates may evaluate a reconstructed peak; they do not choose measured candidates. Study pages retain the precise calibration, candidate policy, numerical budget and validation limits.</p><p><a href="../results/gegi-campaign/index.html">Four independent acquisitions and conditional imaging</a> · <a href="../results/gegi-plane-prior-study/index.html">Historical prior and weak-strip study</a></p></section>
<section class="panel"><h2>Counts, identity and interpretation</h2><p>Initial primaries or decays, positive-deposit primaries, pulse groups, accepted energies and candidate orders are different populations. Each plot names its denominator and selection. An event number identifies a record together with its study, run, model variant and pulse group. Zero deposits, native failures, electronics rejections and unresolved imaging weight remain distinct.</p><p>Engineering completion, numerical convergence and agreement with measurement are separate conclusions. Plot rounding does not alter stored numbers or histogram bins. Exact settings, seeds, units, failure/null accounting and downloadable records remain in each study.</p></section>
<div class="grid"><article class="card"><h2>Geometry and sources</h2><p>Read assembly dimensions, compatibility, coordinates and nominal assumptions.</p><a href="../assemblies/index.html">Compare the assemblies →</a></article>
<article class="card"><h2>Run and analyze</h2><p>Configure a compatible detector and inspect your own saved result.</p><a href="../guide.html">Open the practical guide →</a></article></div>
<p><a href="../results/native-li-selected-events/index.html">Native Li selected events</a> and <a href="../results/lithium-diagnostics/index.html">Li numerical diagnostics</a> retain their separate samples and unresolved limits.</p></div>'''
    write_page(site/'methods/index.html','Methods · GeSignal',methods,1,extra_style=READER_STYLE)


def write_public_guide(site):
    """The student and public guide share one maintained task order."""
    guide=(Path(__file__).parent/'site_guide.html').read_text(encoding='utf-8')
    (site/'guide.html').write_text(guide.replace('__PAGE_NAVIGATION__',page_navigation('guide.html')),
                                  encoding='utf-8',newline='\n')


def write_reader_pages(site):
    from gegi_plane_prior_display import SUMMARY, COMMERCIAL_KEY

    path = site/SUMMARY
    commercial = path.is_file() and COMMERCIAL_KEY in read(path)
    write_page(site/'index.html','GeSignal — HPGe Radiation-to-Readout Simulation',homepage(commercial),0,
               fold_footer=True,extra_style=HOME_STYLE)

    def study(ident,title,purpose,nature,sample,outputs,limit,url,available=True):
        action=('<p><a href="'+url+'">Open study →</a></p>' if available else '<p>Unavailable in this saved snapshot.</p>')
        return ('<article class="card" id="'+ident+'" data-study="'+ident+'"><h2>'+title+'</h2>'
                '<p>'+purpose+'</p><dl><dt>Data</dt><dd>'+nature+'</dd><dt>Sample</dt><dd>'+sample+'</dd>'
                '<dt>Outputs</dt><dd>'+outputs+'</dd></dl><p class="muted">'+limit+'</p>'+action+'</article>')

    formal=site/'results/gegi-campaign'
    campaign_available=(formal/'publication.json').is_file()
    campaign_outputs='Conditional source-plane images, candidate cones, historical spectra and signal examples.'
    campaign_limit='Exact populations and saved iteration status are reported inside the study.'
    if campaign_available:
        summary=read(formal/'summary.json')
        if summary.get('kind')=='gegi_saved_publication_v3':
            groups=summary['counts']['conditional_candidate_groups']
            selected=summary['selected_conditional_imaging_groups']
            orders=summary['counts'].get('conditional_candidates')
            campaign_outputs=f'{groups:,} conditional signal groups; {selected:,} selected for the joint map'
            if orders is not None:campaign_outputs+=f'; {orders:,} candidate orders'
            campaign_outputs+='; separate 708-group historical control.'
            campaign_limit='The conditional image reached its 40-iteration budget; convergence remains unestablished. Same-energy source separation remains unresolved.'
        else:
            accepted=sum(row['counts']['imaging_accepted_groups'] for row in summary['groups'].values())
            campaign_outputs=f'{summary["processed_initial_records"]:,} initial records and {accepted:,} imaging-accepted pulse groups in this earlier snapshot.'

    results='''<div class="reader-page"><header class="reader-intro"><h1>Research results</h1>
<p>Choose a study by its question and saved sample. Each study keeps its original models, counts, event identities and data.</p></header>
<section aria-labelledby="main-studies"><h2 id="main-studies">Main studies</h2><div class="grid study-cards">'''
    results+=study('gegi-shared-readout','GeGI shared readout · 25 × 250 ms',
        'How do shared electronics and imaging priors affect a two-source readout?',
        'Archived single-isotope histories sampled with replacement; shared 34-electrode electronics.',
        '25 independent windows, 6.25 s total clock, with electronics reset between windows.',
        'Energy spectra, source-plane images, sampling variation and prior sensitivity.',
        'Historical library replay; the planned continuous joint-source acquisition is a separate design.',
        'gegi-shared-readout/index.html',commercial)
    results+=study('gegi-campaign','GeGI four independent source acquisitions',
        'Which interaction candidates support a conditional Compton image?',
        'Four separate radiation and charge acquisitions at two positions.',
        'Two 662 keV photon runs of 200,000 primaries each; Cs-137 and Co-60 runs of 300,000 initial records each.',
        campaign_outputs,campaign_limit,'gegi-campaign/index.html',campaign_available)
    results+=study('tenk','Cs-137 10K · four detector cases',
        'Follow radiation, charge and readout across four distinct detector cases.',
        'Independent AK02, SAP22, GeRC02 Li50min and KMRC01 candidate simulations.',
        '10,000 initial decays per case.',
        'Readout, stage spectra, original event records and data ledgers.',
        'Saved waveforms: four each for AK02, SAP22 and GeRC02; 231 for KMRC01 candidate. Scalar ledgers have broader coverage.',
        'cs137-10k/index.html',(site/'examples/cs137-10k/comparison.html').is_file())
    results+=study('million','Cs-137 1M · AK02 and SAP22',
        'Compare deposition truth and measured-energy response at a larger sample size.',
        'Two independent detector runs, separate from the 10K study.',
        '1,000,000 initial Cs-137 decays per detector.',
        'Deposition and response spectra, group records and failure counts.',
        'Isolated 100 µs reset windows; no activity or pileup acquisition model. This study has no published 3D event viewer.',
        'cs137-1m/index.html',all((site/path).is_file() for path in ('examples/cs137-1m/summary.json','examples/cs137-1m-response/summary.json')))
    results+='</div></section><section class="panel" id="historical-studies" aria-labelledby="earlier-studies-title"><h2 id="earlier-studies-title">GeGI readout and imaging questions</h2><p>Earlier samples and controls remain distinct within each topic.</p><div class="topic-grid">'
    topics=(
        ('gegi-short-exposure','Short exposures and energy reconstruction','Early 250 ms exposures, hit maps and single-pixel versus multi-strip energy.'),
        ('gegi-shared-clock-controls','Shared clock and merged triggers','The 3,905-trigger census, 324 two-strip records and controlled studies of triggers 683 and 598.'),
        ('gegi-plane-prior-study','Imaging priors and weak strips','One-second sample, split exposures, area and solid-angle priors, intersections and weak-strip evidence.'),
        ('gegi-position-calibration','Position, depth and threshold calibration','Fast neighboring strips, noise thresholds, apparent depth, joint fits and edge coverage.'),
        ('gegi-double-pulse','Double-pulse resolution','1,368 pulse-pair trials with timing scans and separate trigger, energy and position criteria.'),
        ('gegi-pairing-benchmark','Strip pairing and interaction order','Monoenergetic photons, original events and distinct training, control and held-out mixtures.'),
    )
    results+=''.join('<article><h3><a href="'+ident+'/index.html">'+title+'</a></h3><p>'+description+'</p></article>' for ident,title,description in topics)
    results+='''</div></section><section class="panel" aria-labelledby="other-questions"><h2 id="other-questions">Other research and numerical evidence</h2><div class="topic-grid">
<article><h3><a href="native-li-selected-events/index.html">Native Li readout · selected events</a></h3><p>Four selected events with signed charge, endpoints and readout; distinct from the numerical diagnostics.</p></article>
<article><h3><a href="lithium-diagnostics/index.html">Li numerical diagnostics</a></h3><p>Grid, initialization and collection sensitivity, including retained numerical failures and limits on convergence claims.</p></article>
<article><h3><a href="gegi-strip-study/index.html">GeGI early strip signals</a></h3><p>20 synthetic deposit and charge-cloud examples, 34 channels, truth points and induced signals.</p></article>
<article><h3><a href="gegi-notebook-study/index.html">GeGI executed fields and signals notebook</a></h3><p>Saved historical outputs under their recorded parameters; the notebook is separate from later acquisition studies.</p></article>
<article><h3><a href="../examples/cs137-10k-rings/KMRC01_candidate/response/original-native/summary.html">KM native negative-charge readout</a></h3><p>The original 0/231 accepted result is a separate control for the later fixed −1 wiring.</p></article>
</div></section>
<section class="panel" id="teaching"><h2>Start with one saved signal</h2><p><a href="../learn/signals/index.html">Follow six selected 10K events from energy deposits to readout</a>. Each example keeps its model variant, primary and pulse-group identity.</p></section>
<section class="panel" id="gamma"><h2>Retired pilot studies</h2><p>The 200-primary bare-detector, 40-primary cryostat gamma and early GeGI two-position bundles have been retired. Their original data remain in the project workspace.</p>
<p><a href="../examples/gamma-native/gamma.html">Cryostat gamma retirement record</a> · <a href="../examples/gegi/index.html">Early GeGI retirement record</a></p></section>
<span id="current-ring-10k"></span></div>'''
    if not (site/'spectra/teaching-examples.json').is_file():
        results=results.replace('<p><a href="../learn/signals/index.html">Follow six selected 10K events from energy deposits to readout</a>. Each example keeps its model variant, primary and pulse-group identity.</p>',
                                '<p>The six saved teaching signals are unavailable in this snapshot. <a href="../learn/index.html">Open the learning directory</a>.</p>')
    write_page(site/'results/index.html','Research results · GeSignal',results,1,extra_style=READER_STYLE)

    write_methods(site)
    write_public_guide(site)


def defer_gegi_journey(directory, text, record):
    """Move the exact historical payload to its existing, deferred script asset."""
    import hashlib
    directory=Path(directory)
    embedded=re.search(r'<script type="application/json" id="gegi-journey-data">(.*?)</script>',text,re.S)
    if embedded is None:
        require(record.get('deferred_historical_journey') is not None,
                'Missing saved historical journey payload')
        return text
    payload=embedded[1]
    json.loads(payload)
    script=directory/'gegi_signal_journey.js'
    original=script.read_bytes()
    require(original==(Path(__file__).parent/'gegi_signal_journey.js').read_bytes(),
            'Historical journey script changed before deferred export')
    mount=('<script>GeGISignalJourney.mount(document.getElementById("gegi-signal-journey"),'
           'JSON.parse(document.getElementById("gegi-journey-data").textContent),{scope:"student"});</script>')
    require(text.count(mount)==1 and text.count('<script src="gegi_signal_journey.js"></script>')==1,
            'Historical journey initialization changed')
    # A normal script element also works for a downloaded file:// directory.
    # Neither the payload nor its 34-channel renderer is loaded before expansion.
    deferred=original+('\n/* Deferred exact saved historical payload. */\n'
        'globalThis.mountGeGIHistoricalJourney=function(host){return GeGISignalJourney.mount(host,'
        +payload+',{scope:"student"});};\n').encode('utf-8')
    script.write_bytes(deferred)
    record['deferred_historical_journey']={
        'payload_bytes':len(payload.encode('utf-8')),
        'payload_sha256':hashlib.sha256(payload.encode('utf-8')).hexdigest(),
        'renderer_sha256':hashlib.sha256(original).hexdigest(),
        'load_on':'first historical teaching details expansion'}
    record['artifacts']['gegi_signal_journey.js']={
        'bytes':len(deferred),'sha256':hashlib.sha256(deferred).hexdigest()}
    loader='''<script>(function(){
const host=document.getElementById('gegi-signal-journey'),panel=host.closest('details');let loading=false,ready=false;
function load(){if(!panel.open||loading||ready)return;loading=true;host.textContent='Loading saved historical signals…';
const script=document.createElement('script');script.src='gegi_signal_journey.js?display=__JOURNEY_SCRIPT_SHA__';
script.onload=function(){try{mountGeGIHistoricalJourney(host);ready=true;}catch(error){failed();}};
script.onerror=failed;function failed(){loading=false;script.remove();host.replaceChildren();
const retry=document.createElement('button');retry.type='button';retry.textContent='Retry loading historical signals';retry.onclick=load;host.append(retry);}
document.head.append(script);}
panel.addEventListener('toggle',load);load();
})();</script>'''.replace('__JOURNEY_SCRIPT_SHA__',record['artifacts']['gegi_signal_journey.js']['sha256'])
    text=text.replace(embedded[0],'').replace('<script src="gegi_signal_journey.js"></script>','').replace(mount,loader)
    return text


def refresh_gegi_reading_order(site):
    """A display layer over the exact saved aggregate bundle; no analysis."""
    import hashlib
    from gegi_saved_publication import validate_public, encoded, public
    directory=Path(site)/'results/gegi-campaign'
    if not (directory/'publication.json').is_file():return
    record=read(directory/'publication.json')
    if record.get('kind')!='gegi_saved_publication_v3':return
    validate_public(directory)
    path=directory/'index.html';text=path.read_text(encoding='utf-8')
    text=defer_gegi_journey(directory,text,record)
    text=re.sub(r'<!-- page-navigation:start -->.*?<!-- page-navigation:end -->',
                lambda _:page_navigation('results/gegi-campaign/index.html'),text,count=1,flags=re.S)
    blocks={}
    for ident in ('new-map','spectra','journey','saved-evidence'):
        pattern=r'<section id="'+ident+r'">.*?</section>'
        match=re.search(pattern,text,re.S)
        if match:
            blocks[ident]=match[0];text=text[:match.start()]+text[match.end():]
    require(all(ident in blocks for ident in ('new-map','spectra','journey')),'Saved GeGI reading sections missing')
    # Diagnostics remain available, after the scientific result and example.
    evidence=blocks.get('saved-evidence','')
    if evidence:
        evidence=evidence.replace('<section id="saved-evidence">','<details id="saved-evidence"><summary>Technical evidence and historical implementation notes</summary>',1)
        evidence=evidence.rsplit('</section>',1)[0]+'</details>'
    text=re.sub(r'<section id="campaign-study-identity">.*?</section>','',text,flags=re.S)
    text=re.sub(r'<h1\b[^>]*>.*?</h1>','<h1>GeGI four independent source acquisitions and conditional imaging</h1>',text,count=1,flags=re.S)
    identity=('<section id="campaign-study-identity"><h2>Study design and saved populations</h2>'
              '<p>Four independent acquisitions: two 662 keV monoenergetic photon runs of 200,000 initial primaries each, '
              'plus Cs-137 and Co-60 runs of 300,000 initial records each. The combined count is 1,000,000 initial records.</p>'
              '<p>The current conditional image uses <strong>434 signal-selected groups and 837 candidate orders</strong>. '
              'Its 40 iterations reached the saved budget; convergence remains unestablished. '
              'The separate historical control contains 708 groups.</p></section>')
    ordered=identity+''.join(blocks[ident] for ident in ('new-map','journey','spectra'))+evidence
    # Dataset views in the common page header are the only study-level menu.
    nav=re.search(r'<nav class="local">.*?</nav>|<span id="campaign-reading-order"></span>',text,re.S)
    require(nav is not None,'Saved GeGI reading-order marker missing')
    text=text[:nav.start()]+'<span id="campaign-reading-order"></span>'+ordered+text[nav.end():]
    text=text.replace('<p><strong>Next operation:</strong>', '<p><strong>Historical development note at export:</strong>')
    from site_discovery import landing_metadata_html
    from site_routes import page_record
    route='results/gegi-campaign/index.html'
    description=page_record(route)['title']+'. Saved study evidence, original identities, data and methods.'
    text=landing_metadata_html(text,route,description)
    body=public(text.encode('utf-8'));path.write_bytes(body)
    record['artifacts']['index.html']={'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
    record['display_source_sha256']={'tools/site_restructure.py':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (directory/'publication.json').write_bytes(public(encoded(record)))
    validate_public(directory)
def apply(site):
    site=Path(site)
    require((site/'index.html').is_file(),'Site snapshot missing index')
    catalog=read(site/'models/catalog.json')
    capabilities=detector_pages.execution_capabilities()
    execution_ids={key for key,row in capabilities.items() if row['lbnl_execution_implemented']}
    control_ids=detector_pages.control_capabilities(capabilities)
    catalog_control=detector_pages.catalog_control_capabilities(capabilities)
    dedicated_ids=detector_pages.dedicated_control_capabilities(capabilities)
    control_count=len(control_ids)
    control_choices=', '.join(escape(item['id']) for item in catalog['detectors'] if item['id'] in control_ids)
    blocked_count=sum(not row['available'] and model not in dedicated_ids for model,row in catalog_control.items())
    require(len(catalog.get('detectors',[]))>=2,'Detector catalog missing')

    response=site/'examples/cs137-1m-response/summary.json'
    truth=site/'examples/cs137-1m/summary.json'
    response_summary=read(response) if response.exists() else None
    has_1m=response.exists() and truth.exists()
    has_10k=(site/'examples/cs137-10k/comparison.html').exists()
    formal = site/'results/gegi-campaign'
    if (formal/'publication.json').is_file():
        from gegi_campaign_publication import validate_bundle
        validate_bundle(formal)
    write_reader_pages(site)

    learn='''<div class="reader-page"><header class="reader-intro"><h1>Learn the detector signal chain</h1><p>Start with one saved event, then connect the signal to the detector, readout and original research.</p></header>
<div class="grid"><article class="card"><h2>From deposits to readout</h2><p>Six saved Cs-137 events from the 10K study. Follow deposited energy, induced charge, current, preamplifier, shaper and peak ADC one stage at a time.</p><p><a href="signals/index.html">Start with one signal →</a></p></article>
<article class="card"><h2>Methods and physical meaning</h2><p>Radiation transport, carrier drift, induction, analog and digitized readout, Compton candidates and counting rules.</p><p><a href="../methods/index.html">Read the methods →</a></p></article>
<article class="card"><h2>Detector geometry</h2><p>Compare electrode shapes, electric fields and weighting potentials across the 17 recorded model definitions.</p><p><a href="../detectors/index.html">Explore the models →</a></p></article>
<article class="card"><h2>Try your own simulation</h2><p>Install the student runtime, choose a compatible setup and inspect original event identities and saved files.</p><p><a href="../guide.html">Download, run and analyze →</a></p></article></div>
<p>The six teaching examples retain their original study, model variant, primary and group IDs. <a href="../results/cs137-10k/index.html">Return to the full 10K study</a>.</p></div>'''
    write_page(site/'learn/index.html','Learn · GeSignal',learn,1,extra_style=READER_STYLE)

    geometry_options=''.join('<option>'+escape(kind)+'</option>' for kind in sorted(set(detector_pages.TYPE_LABELS.values())))
    filters='''<section class="panel" aria-labelledby="filter-title"><h2 id="filter-title">Find a model</h2><div class="catalog-filters">
<label>Geometry<select id="filter-geometry"><option value="">All geometries</option>'''+geometry_options+'''</select></label>
<label>Assembly<select id="filter-assembly"><option value="">All compatibility</option><option value="lbnl">LBNL compatible</option><option value="gegi">GeGI only</option><option value="larger">Larger cryostat needed</option></select></label>
<label>Model status<select id="filter-status"><option value="">All statuses</option><option value="recorded model">Recorded model</option><option value="reference">Reference</option><option value="candidate">Candidate</option><option value="scenario">Scenario</option></select></label>
<button type="button" id="reset-filters">Show all models</button></div><span id="other-models"></span><p id="model-filter-count" role="status" aria-live="polite">17 models shown.</p></section>'''
    det=('''<section class="hero"><p class="muted">Detector library</p><h1>Explore detector models</h1>
<p>17 browsable model definitions. Each has an overview, geometry, fields and signals, and parameters with original files.</p></section><span id="current-ring-10k"></span>'''+filters+
        '<div class="grid" id="model-catalog">'+detector_cards(catalog)+'</div>'+
        detector_pages.catalog_introduction(capabilities,control_ids,dedicated_ids)+'''
<script>(function(){const keys=['geometry','assembly','status'],fields=keys.map(k=>document.getElementById('filter-'+k)),cards=Array.from(document.querySelectorAll('#model-catalog [data-model]'));
function filter(){let count=0;cards.forEach(card=>{card.hidden=!keys.every((key,i)=>!fields[i].value||card.dataset[key]===fields[i].value);if(!card.hidden)count++;});document.getElementById('model-filter-count').textContent=count+' of '+cards.length+' models shown.';}
fields.forEach(field=>field.addEventListener('change',filter));document.getElementById('reset-filters').addEventListener('click',()=>{fields.forEach(field=>field.value='');filter();});filter();})();</script>''')
    write_page(site/'detectors/index.html','Detectors · GeSignal',det,1,extra_style='''.catalog-filters{display:flex;align-items:end;gap:16px;flex-wrap:wrap}.catalog-filters label{display:grid;gap:6px}.catalog-filters select,.catalog-filters button{font:inherit;padding:8px;border:1px solid #9caeb9;border-radius:6px;background:white;color:#173047}#model-catalog [hidden]{display:none}#model-catalog h2{font-size:23px}#model-catalog code{overflow-wrap:anywhere}''')
    assemblies=('''<section class="hero"><p class="muted">Cryostat assemblies</p><h1>Choose a compatible assembly</h1>
<p>LBNL and GeGI are separate cryostats. Detector selection never changes the assembly automatically. All 17 detector models remain browsable; six oversized models currently have no supported assembly.</p></section>
<div class="grid"><article class="card"><h2>LBNL modular cryostat</h2><p>'''+str(control_count)+''' compatible detector configurations with nominal source placement. Original upstream geometry provenance and model-specific limits remain explicit.</p><p><a href="lbnl/index.html">Assembly and compatibility →</a></p><p><a href="../viewers/events.html?model=AK02&amp;view=positive">Open LBNL assembly and saved events →</a></p></article>
<article class="card"><h2>GeGI cryostat</h2><p>Exact GeGI_3D only. Measured front layers and nominal side/rear enclosure; no other detector can be inserted.</p><p><a href="gegi/index.html">Rotate the GeGI assembly and inspect dimensions →</a></p><p><a href="../detectors/GeGI_3D/index.html">GeGI detector and workflow →</a></p></article></div>
<p><a href="../detectors/index.html">Browse detectors</a> · <a href="../guide.html#local-control">Configure and run locally</a> · <a href="../results/index.html">Read saved results</a></p>''')
    write_page(site/'assemblies/index.html','Assemblies · GeSignal',assemblies,1)
    if has_1m:
        s=response_summary
        a=s['models']['AK02']; b=s['models']['SAP22']
        body=f'''<section class="hero"><p class="muted">Separate completed campaign</p><h1>Cs137 · one million initial decays per detector</h1>
<p>Nominal uncollimated LBNL cryostat geometry. Radiation transport, SSD charge response and synthetic peak ADC are saved; no measured-spectrum fit or calibrated CCE is claimed.</p>
<p><a class="button" href="spectra/response.html">Response spectra · AK02 &amp; SAP22 →</a> · <a class="button" href="spectra/deposition.html">Deposition spectra · AK02 &amp; SAP22 →</a></p></section>
<div class="grid"><article class="card"><h2>AK02</h2><p>{a["positive_ge_decays"]:,} positive-Ge decays; {a["response"]["accepted"]:,} accepted ADC groups.</p></article>
<article class="card"><h2>SAP22</h2><p>{b["positive_ge_decays"]:,} positive-Ge decays; {b["response"]["accepted"]:,} accepted ADC groups.</p></article></div>
<section class="panel" id="data-files"><h2>Data & settings</h2>
<p><a href="../../examples/cs137-1m-response/groups.csv.gz">Complete saved response group records (CSV gzip)</a> · <a href="../../examples/cs137-1m-response/summary.json">Response settings and counts (JSON)</a> · <a href="../../examples/cs137-1m/summary.json">Transport summary (JSON)</a></p>
<details><summary>Original saved reports</summary><p><a data-original-report href="../../examples/cs137-1m/report.html">Original deposition-truth report</a> · <a data-original-report href="../../examples/cs137-1m-response/report.html">Original response report</a></p></details>
<p>Public scalar records do not contain every full waveform, private field cache or original LH5 file.</p></section>
<section class="panel"><h2>Counting rules and view coverage</h2><p>This study provides deposition and response spectra and scalar group records. No 3D events from these million-decay runs are published. <a href="../cs137-10k/events.html">View 3D events from the separate 10K study</a>.</p><p>One million refers to initial Cs137 decays <strong>per detector</strong>. Positive deposits are grouped in isolated 100 µs reset windows; this is not an activity/live-time/pileup acquisition model. Native failures remain unknown responses and electronics rejection remains a separate outcome.</p></section>'''
        body+='<p>Two independent runs; 1,000,000 initial decays per detector. Full plots are in the spectrum views above. AK02 and SAP22 have different geometries.</p>'
        write_page(site/'results/cs137-1m/index.html','Cs137 1M results · GeSignal',body,2)

    else:
        body='''<section class="hero"><p class="muted">Campaign overview unavailable in this snapshot</p><h1>Cs137 · one million initial decays per detector</h1><p>The generated overview is retained at this stable URL, but this site snapshot does not include both checked truth and response summaries. Use the Results page for currently available campaigns.</p></section>'''
        write_page(site/'results/cs137-1m/index.html','Cs137 1M results unavailable · GeSignal',body,2)

    if has_10k:
        event_cards='''<article class="card"><h2>GeSignal event viewer</h2><p>Choose one primary and pulse group to inspect assembly, recorded deposits and Ge-positive evidence together. All 10,000 initial IDs per detector remain available, including zeros.</p><a href="events.html">Open the event viewer →</a></article>'''
        if not (site/'viewers/events.html').is_file():
            event_cards='''<article class="card"><h2>Geometry and events</h2><a href="../../examples/cs137-10k-geometry/geometry.html">Rotate cryostat geometry and inspect events →</a></article>
<article class="card"><h2>Ge-hit overlay</h2><a href="../../examples/cs137-10k-hits/hit_event_view.html">Open saved Ge-hit examples →</a></article>'''
        body='''<section class="hero"><p class="muted">Earlier engineering campaign</p><h1>Cs137 · 10k initial decays per detector</h1><p>This smaller run established the event-complete Geant4 → SSD → electronics workflow before the million-decay campaign.</p></section>
<div class="grid"><article class="card"><h2>Response comparison</h2><a href="../../examples/cs137-10k/comparison.html">Open 10k response report →</a></article>
'''+event_cards+'''</div>
<p><a href="../../assemblies/lbnl/index.html">Nominal scenario context</a></p>'''
        write_page(site/'results/cs137-10k/index.html','Cs137 10k results · GeSignal',body,2)
    else:
        body='''<section class="hero"><p class="muted">Campaign overview unavailable in this snapshot</p><h1>Cs137 · 10k initial decays per detector</h1><p>This stable overview URL is retained, but the checked 10k comparison is not included in this site snapshot. Use the Results page for currently available campaigns.</p></section>'''
        write_page(site/'results/cs137-10k/index.html','Cs137 10k results unavailable · GeSignal',body,2)
    from saved_archive_display import assemble as assemble_archive_display, upgrade_lithium_display
    if (site/'examples/native-li/comparison.html').is_file():
        assemble_archive_display(site)
    upgrade_lithium_display(site)

    scenario='''<section class="hero"><p class="muted">Geometry and source assumptions</p><h1>Nominal LBNL cryostat</h1>
<p>The saved Cs137 campaigns use a nominal uncollimated source above the curved aluminum wall. The placement is an engineering assumption, not an as-built survey.</p></section>
<section class="panel"><h2>Detector cases are distinct physical models</h2>
<p id="ak02"><strong>AK02:</strong> primary Li-contact case; native response records the explicit 77 K override and canonical bias.</p>
<p id="sap22"><strong>SAP22:</strong> different-geometry non-Li cross-check, not a matched experimental control.</p>
<p>GeRC02 Li50min is a separate operating variant; the library keeps its original 30-minute model. KM remains a candidate with −370 V bias and separately recorded fixed −1 electronics wiring.</p></section>
<section class="panel"><h2>Source and material assumptions</h2><p>Radiation transport records deposits, positions, creation times and identities. SSD then calculates drift and induced charge; deposition time is not drift time. Source selection does not justify changing material, gain, event census or detector parameters.</p>
<p>The supported local source definitions are Cs137, Am241, Ba133 and Co60. Co60 admission reuses its completed 500-decay trial, including one verified below-threshold rejection retained with null reconstructed energy. Thresholds, calibration and original science remain unchanged. The separate fixed 662 keV gamma beam uses 20 primaries for AK02/SAP22. It is not an isotope-decay campaign.</p>
<details><summary>Original geometry provenance</summary><p>The pinned LBNL source files are not redistributed because no explicit license was found in the pinned upstream tree. The <a href="https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/transport/cryostat-source.json">upstream manifest</a> identifies the exact inputs. The maintained <a href="../../guide.html">local guide</a> explains preparation and use.</p></details></section>'''
    def assembly_support(model):
        if model in control_ids:return 'Available in the LBNL cryostat'
        if model in dedicated_ids:
            return 'LBNL incompatible; available only in the <a href="../../assemblies/gegi/index.html">dedicated GeGI cryostat</a>'
        return 'Needs larger cryostat: '+escape(catalog_control[model]['reason'])
    caprows=''.join('<tr><td><a href="../../detectors/'+escape(m['id'])+'/index.html">'+escape(m['id'])+'</a></td><td>'+str(len(m.get('contacts',[])))+'</td><td>'+('Implemented' if m['id'] in execution_ids else 'Not integrated')+'</td><td>'+assembly_support(m['id'])+'</td></tr>' for m in catalog['detectors'])
    scenario+='<section class="panel"><h2>Physical compatibility</h2><p>Control offers '+str(control_count)+' separate detector configurations in the LBNL cryostat; its shared catalog and ring routes are distinct from the legacy <code>Run.cmd</code> adapter. The exact GeGI_3D has its own <a href="../../assemblies/gegi/index.html">dedicated GeGI cryostat</a> and is incompatible with LBNL. GeRC02 Li50min uses the separate operating variant, while the library retains the original 30-minute model. KM retains its candidate qualification, −370 V bias and fixed −1 electronics wiring.</p><p><a href="../../viewers/events.html?model=AK02&amp;view=positive">LBNL assembly and saved events</a> · <a href="../../assemblies/index.html">Compare cryostat assemblies</a></p><details><summary>All model capabilities and legacy commands</summary><p>The older generic adapter selects AK02, SAP22 or both; both means separate serial cases. See the <a href="../../guide.html#choose">legacy commands</a>. All 17 catalog models can be viewed; '+str(blocked_count)+' require a future larger cryostat because of the recorded dimensions. Complete canonical inputs and original settings are retained. Runtime Check plan independently verifies actual setup, geometry, source and readout before Run.</p><table><thead><tr><th>Model</th><th>Contacts</th><th>Legacy Run.cmd</th><th>Control assembly</th></tr></thead><tbody>'+caprows+'</tbody></table></details></section>'
    write_page(site/'scenarios/lbnl-cs137/index.html','Nominal LBNL cryostat · GeSignal',scenario,2)

    from ssd_geometry_publication import refresh_viewers
    refresh_viewers(site)
    apply_detector_pages(site,write_page)
    refresh_gegi_reading_order(site)
    return {'status':'applied','detectors':len(catalog['detectors']),
            'response_present':response.exists(),'truth_present':truth.exists()}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('site',type=Path);a=p.parse_args()
    print(json.dumps(apply(a.site),indent=2))
