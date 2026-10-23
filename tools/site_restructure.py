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
    html=(f'<!doctype html><html lang="en"><meta charset="utf-8">'
          f'<meta name="viewport" content="width=device-width,initial-scale=1">'
          f'<title>{escape(title)}</title><style>{STYLE}{extra_style}</style><body><main class="wrap">'
          f'<header class="top"><a href="{up}index.html"><strong>GeSignal</strong></a>'
          f'{nav}</header>{body}{footer}</main></body></html>')
    path.write_text(html,encoding='utf-8',newline='\n')

def detector_cards(catalog):
    rows=[]
    for item in catalog['detectors']:
        ident=item['id']; require(re.fullmatch(r'[A-Za-z0-9_-]+',ident) is not None,'Unsafe detector ID')
        kind=detector_pages.TYPE_LABELS[ident];poster=f'{ident}/runs/{detector_pages.RUN}/01_geometry.png'
        capability=detector_pages.catalog_model_summary(ident)
        rows.append(f'<article class="card"><a href="{escape(ident)}/index.html" aria-label="{escape(ident)} detector overview">'
                    f'<img loading="lazy" style="width:100%;height:220px;object-fit:contain" src="{escape(poster)}" '
                    f'alt="{escape(ident)} {escape(kind)}, saved geometry"></a>'
                    f'<h2><a href="{escape(ident)}/index.html">{escape(ident)}</a></h2><p>{escape(kind)}</p>'
                    f'<p><strong>{escape(capability["label"])}</strong></p><p>{escape(capability["detail"])}</p>'
                    f'<p>Model status: {escape(item.get("status","saved model"))}. Public studies and validation limits are listed on its overview.</p></article>')
    return ''.join(rows)

HOME_STYLE='''
body{background:#f7fafb}.wrap{max-width:1180px}.top{padding-bottom:16px;border-bottom:1px solid #d7e0e7}
.top>a{text-decoration:none;font-size:21px;color:#173047}.top nav a{background:transparent;font-size:14px;padding:8px}
.home-hero{padding:30px 0 20px;max-width:900px}.home-hero .eyebrow{font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:#526575;margin:0 0 12px}
.home-hero h1{font-size:clamp(2rem,4vw,3rem);letter-spacing:-.035em;line-height:1.12;margin:0 0 16px;color:#102d40}
.home-hero .lead{font-size:18px;line-height:1.6;max-width:760px;margin:0;color:#405d6c}
.flow-heading{display:flex;justify-content:space-between;align-items:baseline;gap:12px}.flow-heading h2{font-size:19px;margin:10px 0 14px}.flow-heading small{color:#526575}
.signal-flow{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;list-style:none;padding:0;margin:0}
.signal-flow>li{position:relative;padding:20px;background:#fff;border:1px solid #cfdee3;border-radius:12px;min-width:0}
.signal-flow>li+li:before{content:'→';position:absolute;left:-18px;top:108px;font-size:23px;color:#007e89}
.step-label{color:#00727e;font-size:12px;font-weight:750;letter-spacing:.07em;text-transform:uppercase}.signal-flow h3{font-size:21px;margin:5px 0 0}.engine{font-size:13px;color:#526575;margin:3px 0 8px}
.signal-flow svg{display:block;width:100%;height:82px;color:#395967}.signal-flow svg text{font:15px system-ui}
.signal-flow .explanation{font-size:15px;line-height:1.5;min-height:67px;margin:9px 0 14px}.quantity{font-size:14px;background:#edf6f7;border-radius:6px;padding:8px 10px;margin:0;color:#075663}
.energy-key{margin:14px 0 26px;font-size:14px;color:#405d6c;max-width:920px}.energy-key strong{color:#173047}
.path-heading{font-size:20px;margin:0 0 14px}.reader-paths{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}
.reader-paths article{display:flex;flex-direction:column;align-items:flex-start;border-top:3px solid #9ebcc5;padding:16px 0 2px;min-width:0}
.reader-paths article:first-child{border-color:#008391}.reader-paths h3{font-size:20px;margin:8px 0}.reader-paths p{font-size:15px;color:#405d6c;line-height:1.55;margin:0 0 16px}.reader-paths .audience{font-size:12px;text-transform:uppercase;letter-spacing:.04em;margin:0;color:#526575}
.reader-paths a{margin-top:auto;font-weight:700;text-decoration:none;padding:9px 13px;background:#e5eef2;border-radius:6px}.reader-paths article:first-child a{background:#087b89;color:white}
.home-scope{margin:28px 0 0;font-size:13px;color:#526575}footer{font-size:13px;margin-top:24px}
@media(max-width:760px){.top{gap:10px}.top nav{gap:2px}.top nav a{padding:6px;font-size:13px}.home-hero{padding-top:24px}.home-hero .lead{font-size:16px}.signal-flow,.reader-paths{grid-template-columns:1fr}.signal-flow{gap:14px}.signal-flow>li{display:grid;grid-template-columns:100px minmax(0,1fr);column-gap:14px;padding:16px}.signal-flow .step-label,.signal-flow h3,.signal-flow .engine,.signal-flow .explanation,.signal-flow .quantity{grid-column:2}.signal-flow svg{grid-column:1;grid-row:1/6;align-self:center;height:98px}.signal-flow>li+li:before{display:none}.signal-flow .explanation{min-height:0;margin:7px 0 10px}.signal-flow h3{font-size:19px}.signal-flow .quantity{font-size:13px}.flow-heading small{font-size:11px}.reader-paths{gap:14px}.reader-paths p{margin-bottom:12px}}
'''


def homepage():
    """An explanatory schematic and three tasks; data plots live in their studies."""
    return '''<section class="home-hero"><p class="eyebrow">GeSignal · END2END_Ge_Simulation</p>
<h1>From a gamma ray<br>to a measured energy.</h1>
<p class="lead">Explore how a high-purity germanium (HPGe) detector turns a radiation interaction into an electrical signal — and how that signal becomes an energy measurement.</p></section>
<section id="pipeline-example" aria-labelledby="signal-chain-title"><div class="flow-heading"><h2 id="signal-chain-title">One physical chain. Three simulation stages.</h2><small>Conceptual diagram</small></div>
<ol class="signal-flow">
<li><span class="step-label">01 · Interaction</span><h3>Radiation deposits energy</h3><p class="engine">Geant4 / remage</p>
<svg viewBox="0 0 260 90" aria-hidden="true"><rect x="102" y="10" width="105" height="70" rx="16" fill="#e3eef8" stroke="#83a8bd"/><path d="M15 45H125L158 27L179 61" fill="none" stroke="#087b89" stroke-width="3"/><path d="m117 39 9 6-9 6" fill="none" stroke="#087b89" stroke-width="2"/><circle cx="126" cy="45" r="5" fill="#cd6d43"/><circle cx="158" cy="27" r="5" fill="#cd6d43"/><circle cx="179" cy="61" r="5" fill="#cd6d43"/><text x="35" y="31">γ</text><text x="217" y="50">Ge</text></svg>
<p class="explanation">Track interactions in the crystal and record where, when and how much energy is deposited.</p><p class="quantity">Deposited energy · E<sub>dep</sub> [keV]</p></li>
<li><span class="step-label">02 · Detector signal</span><h3>Charges drift and induce signal</h3><p class="engine">SolidStateDetectors.jl</p>
<svg viewBox="0 0 260 90" aria-hidden="true"><rect x="27" y="12" width="206" height="66" rx="10" fill="#f1edf8" stroke="#b5a3c9"/><path d="M27 13v64M233 13v64" stroke="#795b9e" stroke-width="6"/><path d="M117 45H55m0 0 10-6m-10 6 10 6M143 45h62m0 0-10-6m10 6-10 6" stroke="#087b89" stroke-width="2" fill="none"/><circle cx="121" cy="45" r="13" fill="#dbeef0"/><circle cx="140" cy="45" r="13" fill="#e9dfef"/><text x="110" y="50">e⁻</text><text x="131" y="50">h⁺</text></svg>
<p class="explanation">Transport electrons and holes in the electric field and calculate the charge induced on each electrode.</p><p class="quantity">Electrode charge · Q(t) [fC]</p></li>
<li><span class="step-label">03 · Measurement</span><h3>Electronics reconstruct energy</h3><p class="engine">Preamplifier → shaper → peak ADC</p>
<svg viewBox="0 0 260 90" aria-hidden="true"><g fill="#e5f2ee" stroke="#91b6ab"><rect x="5" y="22" width="70" height="46" rx="7"/><rect x="95" y="22" width="70" height="46" rx="7"/><rect x="185" y="22" width="70" height="46" rx="7"/></g><path d="M75 45h20m70 0h20" stroke="#087b89" stroke-width="2"/><g fill="#285c53" text-anchor="middle"><text x="40" y="51">Preamp</text><text x="130" y="51">Shape</text><text x="220" y="51">ADC</text></g></svg>
<p class="explanation">Amplify and shape the signal. Convert the digitized peak to energy using a fixed calibration.</p><p class="quantity">Reconstructed energy · E<sub>rec</sub> [keV]</p></li>
</ol><p class="energy-key"><strong>E<sub>dep</sub></strong> is energy left in the crystal. <strong>E<sub>rec</sub></strong> is energy inferred from the readout. Following both reveals how charge collection and electronics affect the measurement. ADC means analog-to-digital converter.</p></section>
<section aria-labelledby="reader-paths-title"><h2 class="path-heading" id="reader-paths-title">Where would you like to start?</h2>
<div class="reader-paths"><article><p class="audience">Learn · online · no installation</p><h3>Follow one signal</h3><p>Walk through six saved examples, from energy deposits to electrode signals and the final readout.</p><a href="spectra/pipeline.html">Learn the signal chain →</a></article>
<article><p class="audience">Explore · online · no installation</p><h3>Browse simulation results</h3><p>Compare detector responses, study energy spectra and explore multichannel Compton imaging.</p><a href="results/index.html">Browse saved results →</a></article>
<article><p class="audience">Run · Windows · local setup</p><h3>Run your own simulation</h3><p>Prepare the local environment, choose a compatible detector and source, then run with Control.</p><a href="guide.html">Set up and run locally →</a></article></div></section>
<span id="native-cs137-10k"></span><span id="current-ring-10k"></span>
<p class="home-scope">The online examples are saved simulations. Each study documents its model assumptions and validation limits.</p>'''

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
    nav=re.search(r'<nav class="local">.*?</nav>',text,re.S)
    require(nav is not None,'Saved GeGI local navigation missing')
    ordered=''.join(blocks[ident] for ident in ('new-map','spectra','journey'))+evidence
    text=text[:nav.end()]+ordered+text[nav.end():]
    text=text.replace('<p><strong>Next operation:</strong>', '<p><strong>Historical development note at export:</strong>')
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
    has_rings=(site/'examples/cs137-10k-rings/manifest.json').exists()
    has_hit_view=(site/'examples/cs137-10k-hits/hit_event_view.html').exists()
    has_formal_gegi=(site/'results/gegi-campaign/publication.json').is_file()
    has_gegi=has_formal_gegi
    gegi_route='results/gegi-campaign/index.html'
    gegi_description='GeGI dedicated cryostat · configurable gamma transport, 34-electrode charge/readout and signal-derived Compton cones and directional maps.'
    if has_formal_gegi:
        from gegi_campaign_publication import validate_bundle as validate_formal_gegi
        validate_formal_gegi(site/'results/gegi-campaign')
        saved=read(site/'results/gegi-campaign/summary.json')
        if saved.get('kind')=='gegi_saved_publication_v3':
            counts=saved['counts']
            groups=counts['conditional_candidate_groups']
            selected=saved['selected_conditional_imaging_groups']
            if selected==groups:
                population=f'All {groups:,} conditional signal groups'
                if 'conditional_candidates' in counts:
                    population+=f' · {counts["conditional_candidates"]:,} candidate cones'
                population+=' contribute to the pooled map; energy layers are optional. '
            else:
                population=(f'{groups:,} conditional signal groups; '
                            f'{selected:,} selected for the joint map. ')
            gegi_description=(population+
                f'{saved["initial_records"]:,} initial records across four acquisitions at two positions; '
                f'{counts["native_failed_groups"]:,} retained native failures. '
                'Same-energy source separation remains unresolved; conditional candidates are not validated recoveries. '
                'Photon/decay denominators remain separate.')
        else:
            accepted=sum(g['counts']['imaging_accepted_groups'] for g in saved['groups'].values())
            failed=sum(g['counts']['native_failed_groups'] for g in saved['groups'].values())
            gegi_description+=(f' Completed {saved["processed_initial_records"]:,} initial records across four acquisitions; '
                               f'{accepted:,} imaging-accepted pulse groups and {failed:,} retained native failures. '
                               'Photon and isotope-decay denominators remain separate. Follow a real signal through candidate cones to the final map.')
    write_page(site/'index.html','GeSignal — HPGe Radiation-to-Readout Simulation',homepage(),0,
               fold_footer=True,nav_html=primary_navigation('index.html'),extra_style=HOME_STYLE)

    curated_teaching=(site/'spectra/teaching-examples.json').is_file()
    learn='''<meta http-equiv="refresh" content="0;url=../spectra/pipeline.html"><section class="hero"><h1>Signal walkthrough</h1><p>The explanation and six saved signals now share one teaching page.</p><p><a href="../spectra/pipeline.html">Continue to the six signal examples →</a></p></section>'''
    write_page(site/'learn/index.html','Pipeline explanation · GeSignal',learn,1)

    featured_items=[x for x in catalog['detectors'] if x['id'] in control_ids]
    dedicated_items=[x for x in catalog['detectors'] if x['id'] in dedicated_ids]
    other_items=[x for x in catalog['detectors'] if x['id'] not in control_ids|dedicated_ids]
    det=('''<section class="hero"><p class="muted">Detector library</p><h1>Explore detector models</h1>
<p>Choose a detector to inspect its geometry, saved fields and signals. All 17 model definitions retain their original settings and provenance.</p></section>
<span id="current-ring-10k"></span>'''+detector_pages.catalog_introduction(capabilities, control_ids, dedicated_ids)+'''
<h2>LBNL cryostat · Control configurations</h2><p>'''+str(control_count)+''' supported local configurations in the <a href="../scenarios/lbnl-cs137/index.html">LBNL modular cryostat</a>. GeRC02 uses a separate Li50min operating variant; its library geometry is the original 30-minute model.</p><div class="grid">'''+detector_cards({'detectors':featured_items})+'''</div>
<h2>GeGI dedicated cryostat</h2><p>The <a href="../assemblies/gegi/index.html">GeGI cryostat</a> supports only the exact GeGI_3D model. It is a separate assembly at the same level as LBNL, with 34-electrode readout and Compton imaging.</p><div class="grid">'''+detector_cards({'detectors':dedicated_items})+'''</div>
<details id="other-models" class="panel" style="margin:22px 0"><summary>'''+str(len(other_items))+''' more models · larger cryostat needed</summary><p>These models exceed the supported cryostat dimensions. Open a model to inspect its geometry and exact limits.</p><div class="grid">'''+detector_cards({'detectors':other_items})+'''</div></details>''')
    write_page(site/'detectors/index.html','Detectors · GeSignal',det,1)
    assemblies=('''<section class="hero"><p class="muted">Cryostat assemblies</p><h1>Choose a compatible assembly</h1>
<p>LBNL and GeGI are separate cryostats. Detector selection never changes the assembly automatically. All 17 detector models remain browsable; six oversized models currently have no supported assembly.</p></section>
<div class="grid"><article class="card"><h2>LBNL modular cryostat</h2><p>'''+str(control_count)+''' compatible detector configurations with nominal source placement. Original upstream geometry provenance and model-specific limits remain explicit.</p><p><a href="../scenarios/lbnl-cs137/index.html">Assembly and compatibility →</a></p><p><a href="../viewers/events.html?model=AK02&amp;view=positive">Open LBNL assembly and saved events →</a></p></article>
<article class="card"><h2>GeGI cryostat</h2><p>Exact GeGI_3D only. Measured front layers and nominal side/rear enclosure; no other detector can be inserted.</p><p><a href="gegi/index.html">Rotate the GeGI assembly and inspect dimensions →</a></p><p><a href="../detectors/GeGI_3D/index.html">GeGI detector and workflow →</a></p></article></div>
<p><a href="../detectors/index.html">Browse detectors</a> · <a href="../guide.html#local-control">Configure and run locally</a> · <a href="../results/index.html">Read saved results</a></p>''')
    write_page(site/'assemblies/index.html','Assemblies · GeSignal',assemblies,1)
    def result_panel(ident,title,description,links,available=True,extra=''):
        actions=(' · '.join(f'<a href="{url}">{label}</a>' for url,label in links)
                 if available else 'This dataset is unavailable in this snapshot.')
        return (f'<section id="{ident}" class="panel" data-dataset="{ident}" style="margin:16px 0">'
                f'<h2>{title}</h2><p>{description}</p><p>{actions}</p>'+extra+'</section>')
    results='''<section class="hero"><p class="muted">Saved studies and teaching signals</p><h1>Saved results</h1>
<p>Open the current GeGI image, follow the signal chain, or explore a complete Cs137 campaign. Each study retains its own event identities, settings and denominators.</p></section>'''
    results+=result_panel('gegi','GeGI · current saved Compton image' if has_formal_gegi else 'GeGI · saved Compton imaging',gegi_description,
        (('../'+gegi_route,'Open saved GeGI signals and imaging →'),),has_gegi)
    results+=result_panel('teaching','Learn the chain · six representative Cs137 signals',
        'Six saved signals from the four-case Cs137 10K study, from deposits through charge, shaping and peak ADC. Illustrative examples, not a statistical sample.',
        (('../spectra/pipeline.html','Open teaching example →'),),curated_teaching)
    tenk_description=('AK02, SAP22, GeRC02 Li50min and KMRC01 candidate · 10,000 initial Cs137 decays in each of four separate cases. Charge/readout, stage spectra, radiation events and complete scalar ledgers.' if has_rings else
                      'AK02 and SAP22 · 10,000 initial Cs137 decays per detector in two separate cases.')
    results+=result_panel('tenk','Cs137 10K · '+('four detector cases' if has_rings else 'two detector cases'),tenk_description,
        (('cs137-10k/index.html','Choose a detector case →'),),has_10k,
        '<span id="current-ring-10k"></span>')
    results+=result_panel('million','Cs137 1M · two detector cases',
        'AK02 and SAP22 · one million initial decays per detector · nominal cryostat. Available views are ensemble truth/response spectra and complete scalar group records.',
        (('cs137-1m/index.html','Open 1M campaign →'),),has_1m)
    results+='<details id="historical-studies" class="panel" style="margin:22px 0"><summary>Retired small studies</summary><section id="gamma" data-dataset="gamma"><h2>Earlier gamma and two-position examples</h2><p>The 200-primary bare-detector, 40-primary cryostat gamma and earlier GeGI two-position public bundles have been retired. Their scientific originals remain in the local workspace. Use the current GeGI study or six Cs137 teaching signals above; these are separate datasets.</p></section></details>'
    results+='<p><a href="../guide.html#saved-analysis">Help with settings, event identities and data files</a></p>'
    write_page(site/'results/index.html','Results · GeSignal',results,1)

    if has_1m:
        s=response_summary
        a=s['models']['AK02']; b=s['models']['SAP22']
        body=f'''<section class="hero"><p class="muted">Separate completed campaign</p><h1>Cs137 · one million initial decays per detector</h1>
<p>Nominal uncollimated LBNL cryostat geometry. Radiation transport, SSD charge response and synthetic peak ADC are saved; no measured-spectrum fit or calibrated CCE is claimed.</p>
<p><a class="button" href="../../spectra/million-response.html">Response spectra · AK02 &amp; SAP22 →</a> · <a class="button" href="../../spectra/million-truth.html">Deposition spectra · AK02 &amp; SAP22 →</a></p></section>
<div class="grid"><article class="card"><h2>AK02</h2><p>{a["positive_ge_decays"]:,} positive-Ge decays; {a["response"]["accepted"]:,} accepted ADC groups.</p></article>
<article class="card"><h2>SAP22</h2><p>{b["positive_ge_decays"]:,} positive-Ge decays; {b["response"]["accepted"]:,} accepted ADC groups.</p></article></div>
<section class="panel" id="data-files"><h2>Data & settings</h2>
<p><a href="../../examples/cs137-1m-response/groups.csv.gz">Complete saved response group records (CSV gzip)</a> · <a href="../../examples/cs137-1m-response/summary.json">Response settings and counts (JSON)</a> · <a href="../../examples/cs137-1m/summary.json">Transport summary (JSON)</a></p>
<details><summary>Original saved reports</summary><p><a data-original-report href="../../examples/cs137-1m/report.html">Original deposition-truth report</a> · <a data-original-report href="../../examples/cs137-1m-response/report.html">Original response report</a></p></details>
<p>Public scalar records do not contain every full waveform, private field cache or original LH5 file.</p></section>
<section class="panel"><h2>Counting rules</h2><p>One million refers to initial Cs137 decays <strong>per detector</strong>. Positive deposits are grouped in isolated 100 µs reset windows; this is not an activity/live-time/pileup acquisition model. Native failures remain unknown responses and electronics rejection remains a separate outcome.</p></section>'''
        body+='<p>Two independent runs; 1,000,000 initial decays per detector. Full plots are in the spectrum views above. AK02 and SAP22 have different geometries.</p>'
        write_page(site/'results/cs137-1m/index.html','Cs137 1M results · GeSignal',body,2)

    else:
        body='''<section class="hero"><p class="muted">Campaign overview unavailable in this snapshot</p><h1>Cs137 · one million initial decays per detector</h1><p>The generated overview is retained at this stable URL, but this site snapshot does not include both checked truth and response summaries. Use the Results page for currently available campaigns.</p></section>'''
        write_page(site/'results/cs137-1m/index.html','Cs137 1M results unavailable · GeSignal',body,2)

    if has_10k:
        event_cards='''<article class="card"><h2>GeSignal event viewer</h2><p>Choose one primary and pulse group to inspect assembly, recorded deposits and Ge-positive evidence together. All 10,000 initial IDs per detector remain available, including zeros.</p><a href="../../viewers/events.html">Open the event viewer →</a></article>'''
        if not (site/'viewers/events.html').is_file():
            event_cards='''<article class="card"><h2>Geometry and events</h2><a href="../../examples/cs137-10k-geometry/geometry.html">Rotate cryostat geometry and inspect events →</a></article>
<article class="card"><h2>Ge-hit overlay</h2><a href="../../examples/cs137-10k-hits/hit_event_view.html">Open saved Ge-hit examples →</a></article>'''
        body='''<section class="hero"><p class="muted">Earlier engineering campaign</p><h1>Cs137 · 10k initial decays per detector</h1><p>This smaller run established the event-complete Geant4 → SSD → electronics workflow before the million-decay campaign.</p></section>
<div class="grid"><article class="card"><h2>Response comparison</h2><a href="../../examples/cs137-10k/comparison.html">Open 10k response report →</a></article>
'''+event_cards+'''</div>
<p><a href="../../scenarios/lbnl-cs137/index.html">Nominal scenario context</a></p>'''
        write_page(site/'results/cs137-10k/index.html','Cs137 10k results · GeSignal',body,2)
    else:
        body='''<section class="hero"><p class="muted">Campaign overview unavailable in this snapshot</p><h1>Cs137 · 10k initial decays per detector</h1><p>This stable overview URL is retained, but the checked 10k comparison is not included in this site snapshot. Use the Results page for currently available campaigns.</p></section>'''
        write_page(site/'results/cs137-10k/index.html','Cs137 10k results unavailable · GeSignal',body,2)
    methods='''<section class="hero"><p class="muted">Principles, assumptions and limits</p><h1>Methods & limitations</h1>
<p>Start with the physical chain: radiation deposits energy, moving charges induce electrode signals, and electronics turn those signals into a reconstructed energy.</p></section>
<section class="panel"><h2>Radiation deposits</h2><p>Geant4/remage tracks the radiation and records deposited energy E<sub>dep</sub> in keV, positions in mm, creation/deposition times in ns and original primary/track identities. A primary may miss the crystal, interact more than once or produce delayed daughter deposits. Keep deposits belonging to one primary and pulse group together.</p></section>
<section class="panel"><h2>Semiconductor charge and induction</h2><p>SolidStateDetectors.jl transports the generated electrons and holes in the detector electric field. Electrode weighting potentials determine the signed induced charge through the Shockley–Ramo relation. Charge in fC and current in nA belong to this stage; deposition time is not carrier drift time. Incomplete collection, guards and numerical termination flags remain part of the result.</p></section>
<section class="panel"><h2>Electronics and reconstructed energy</h2><p>A fixed wiring convention passes the signed current to a preamplifier, analog shaper and peak ADC. Voltages are in V. Reconstructed energy E<sub>rec</sub> in keV uses an independent injection calibration shared across events, never an event-by-event match to E<sub>dep</sub>. Threshold, clipping and rejection can make energy unavailable; an unknown response is not zero.</p><p><a href="../spectra/pipeline.html">Follow these stages in six saved signals →</a></p></section>
<section class="panel"><h2>Counts, identity and validation</h2><p>Initial primaries or decays, nonzero primaries, pulse groups and accepted readout groups are distinct populations. Each plot names its denominator and selection. Event numbers only identify a record together with its study, independent run, model/variant and pulse group. Engineering completion, numerical convergence and agreement with measurement are separate claims; these examples are not measured detector calibration.</p><p>Plot display rounding does not change stored values or histogram bins. Each study retains exact settings, seeds, failure/null accounting and downloadable records.</p></section>
<div class="grid">
<article class="card"><h2>Cryostats and sources</h2><p>LBNL and GeGI assembly geometry, compatibility, source placement and physical assumptions.</p><a href="../assemblies/index.html">Read assembly assumptions →</a></article>
<article class="card"><h2>Local configuration and data</h2><p>Choose compatible models and read a saved result using the maintained guide.</p><a href="../guide.html#saved-analysis">Read the saved-data guide →</a></article></div>
<details><summary>Advanced and historical Li studies</summary><p>Native diffusion, endpoints and grid sensitivity retain unresolved numerical limits.</p><p><a href="../lithium/lithium.html">Li-region diagnostics</a> · <a href="../examples/native-li/comparison.html">Open selected study →</a></p></details>'''
    if (site/'examples/native-li/comparison.html').is_file():
        from saved_archive_display import assemble as assemble_archive_display
        assemble_archive_display(site)
        methods=methods.replace('href="../examples/native-li/comparison.html">Open selected study →',
                                'href="native-li.html">Open readable saved plots →',1)
    write_page(site/'methods/index.html','Methods · GeSignal',methods,1)
    from saved_archive_display import upgrade_lithium_display
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

    (site/'guide.html').write_text((Path(__file__).resolve().parent/'site_guide.html').read_text(encoding='utf-8').replace('__PAGE_NAVIGATION__',page_navigation('guide.html')),encoding='utf-8',newline='\n')
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
