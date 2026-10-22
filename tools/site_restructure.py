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

def write_page(path,title,body,depth=0,*,fold_footer=False,page_path=None,dataset=None,model=None,model_label=None,nav_html=None):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    up='../'*depth
    page_path=page_path or '/'.join(path.parts[-(depth+1):])
    nav=nav_html if nav_html is not None else page_navigation(page_path,dataset,model,model_label)
    footer=display_footer(page_path)
    if fold_footer:
        footer=footer.replace('<footer>','<footer><details><summary>More project resources</summary><p>',1).replace('</footer>','</p></details></footer>',1)
    html=(f'<!doctype html><html lang="en"><meta charset="utf-8">'
          f'<meta name="viewport" content="width=device-width,initial-scale=1">'
          f'<title>{escape(title)}</title><style>{STYLE}</style><body><main class="wrap">'
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

def teaching_preview(site):
    """A small preview of actual saved samples; the teaching page owns details."""
    source=Path(site)/'spectra/teaching-examples.json'
    if not source.is_file():
        return ''
    case=read(source)['cases'][0]
    trace=case['saved_trace']['trace']
    def curve(times,values,label,unit):
        pairs=[(float(t),float(v)) for t,v in zip(times,values) if 0<=t<=5000]
        require(len(pairs)>1,'Teaching preview needs retained original samples')
        lo=min(0.,min(v for _,v in pairs));hi=max(0.,max(v for _,v in pairs));span=hi-lo or 1.
        points=' '.join(f'{40+270*t/5000:.5g},{135-105*(v-lo)/span:.5g}' for t,v in pairs)
        return (f'<figure><svg viewBox="0 0 330 180" role="img" aria-label="{label}, {unit}; first 5 microseconds of saved samples">'
                f'<text x="14" y="19">{label} ({unit})</text><path d="M40 30V135H310" fill="none" stroke="#9aaebb"/>'
                f'<polyline points="{points}" fill="none" stroke="#087f91" stroke-width="2"/>'
                '<text x="40" y="160">0</text><text x="250" y="160">5 µs</text></svg></figure>')
    plots=curve(trace['time_ns'],trace['induced_charge_fC'],'Induced charge','fC')+curve(trace['time_ns'],trace['shaped_V'],'Shaped signal','V')
    edep=case['pulse']['deposited_energy_keV'];erec=case['pulse']['readout']['reconstructed_energy_keV']
    return ('<section class="panel" id="pipeline-example"><h2>One saved event, from deposits to energy</h2>'
        f'<p>Cs137 10K · {escape(case["model"])}'+(' Li50min' if case['model']=='GeRC02' else '')+f' · primary {case["event_id"]} · pulse group {case["group_id"]}. '
        f'Deposited energy {edep:.3f} keV → reconstructed energy {erec:.3f} keV.</p>'
        '<div class="grid">'+plots+'</div><p>Original signed samples in the first 5 µs. '
        'Synthetic electronics and retained native cap flags; this example does not establish calibrated charge collection.</p></section>')

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
    gamma=site/'examples/gamma-native'
    has_gamma=gamma.exists()
    if has_gamma:
        from gamma_publication import validate_bundle as validate_gamma_showcase, completed as gamma_completed
        validate_gamma_showcase(gamma)
    completed_gamma=has_gamma and gamma_completed(gamma)
    has_formal_gegi=(site/'results/gegi-campaign/publication.json').is_file()
    has_gegi=has_formal_gegi or (site/'examples/gegi/publication.json').is_file()
    gegi_route='results/gegi-campaign/index.html' if has_formal_gegi else 'examples/gegi/index.html'
    gegi_description='GeGI dedicated cryostat · configurable gamma transport, 34-electrode charge/readout and signal-derived Compton cones and directional maps.'
    if has_formal_gegi:
        from gegi_campaign_publication import validate_bundle as validate_formal_gegi
        validate_formal_gegi(site/'results/gegi-campaign')
        saved=read(site/'results/gegi-campaign/summary.json')
        if saved.get('kind')=='gegi_saved_publication_v3':
            counts=saved['counts']
            gegi_description=(f'Completed {saved["initial_records"]:,} initial records across four acquisitions at two positions. '
                f'{counts["conditional_candidate_groups"]:,} conditional signal groups; '
                f'{saved["selected_conditional_imaging_groups"]:,} selected for the joint map; '
                f'{counts["native_failed_groups"]:,} retained native failures. '
                'Same-energy source separation remains unresolved; conditional candidates are not validated recoveries. '
                'Explore the joint map, energy layers and signal-to-cone explanation. Photon/decay denominators remain separate.')
        else:
            accepted=sum(g['counts']['imaging_accepted_groups'] for g in saved['groups'].values())
            failed=sum(g['counts']['native_failed_groups'] for g in saved['groups'].values())
            gegi_description+=(f' Completed {saved["processed_initial_records"]:,} initial records across four acquisitions; '
                               f'{accepted:,} imaging-accepted pulse groups and {failed:,} retained native failures. '
                               'Photon and isotope-decay denominators remain separate. Follow a real signal through candidate cones to the final map.')
    elif has_gegi:
        from gegi_publication import validate_bundle as validate_gegi_showcase
        validate_gegi_showcase(site/'examples/gegi')
        saved=read(site/'examples/gegi/summary.json')
        image=saved['imaging']
        gegi_description+=(f' Saved denominator: {saved["counts"]["initial_primaries"]:,} initial emitted gammas; '
                           f'{image["accepted_events"]:,} imaging-accepted events, {image["ambiguous_events"]:,} ambiguous.')
        if (saved.get('kind')=='gegi_saved_source_comparison_v1' and
                saved['counts']['initial_primaries']==10000 and
                image['accepted_events']==5 and image['ambiguous_events']==4):
            gegi_description+=' This earlier two-position sample is inconclusive for reliable source separation.'

    home=f'''<section class="hero"><p class="muted">HPGe radiation-to-readout simulation</p><h1>GeSignal</h1>
<p>Explore how radiation deposits become charge signals and an energy measurement: Geant4/remage → SolidStateDetectors.jl → preamplifier → shaping → peak ADC.</p>
<p>The public website contains saved engineering results. Run new simulations locally with Control.</p></section>
<p><a class="button" href="spectra/pipeline.html">Follow one signal →</a> · <a href="results/index.html">Browse all results</a> · <a href="guide.html">Run locally</a></p>
<span id="native-cs137-10k"></span><span id="current-ring-10k"></span>'''
    home+=teaching_preview(site) or '<section id="pipeline-example"><h2>Follow a saved signal</h2><p>The teaching page retains each example’s study and event identity.</p></section>'
    home+='<section class="cards" aria-label="Representative studies">'
    if has_10k:
        home+='<article class="card"><h2>Compare detector responses</h2><p>Four independent Cs137 10K cases: deposits, signed charge, electronics and spectra. Different geometries; no matched Li-only experimental control.</p><a href="results/cs137-10k/index.html">Choose a detector case →</a></article>'
    if has_1m:
        home+='<article class="card"><h2>Study larger-sample spectra</h2><p>AK02 and SAP22: 1,000,000 initial decays per detector in two independent runs. Ensemble spectra and scalar records; full waveforms are not available for every event.</p><a href="results/cs137-1m/index.html">Open the 1M study →</a></article>'
    if has_gegi:
        home+='<article class="card"><h2>GeGI Compton imaging</h2><p>'+gegi_description+'</p><a href="'+gegi_route+'">Open saved GeGI signals and imaging →</a></article>'
    home+='</section>'
    write_page(site/'index.html','GeSignal',home,0,fold_footer=True)

    curated_teaching=(site/'spectra/teaching-examples.json').is_file()
    learn_example='''<section class="panel"><h2>Main teaching example</h2><p>Follow one saved bare-detector gamma event through deposits, charge, preamplifier, shaper and peak ADC.</p><a class="button" href="../spectra/pipeline.html">Open the teaching example →</a></section>'''
    if curated_teaching:
        learn_example=learn_example.replace('Follow one saved bare-detector gamma event through deposits, charge, preamplifier, shaper and peak ADC.','Compare six representative signals selected from the completed Cs137 10K cryostat cases. Each retains its source event, charge, electronics settings and limitations.')
    if has_gamma:
        gamma_caption='Follow all 40 original primaries: 29 known zero inputs and 11 positive primaries. Native failures keep unknown charge and readout null. Collection-edge and full-window views preserve signed signals and original caps; independent synthetic injection calibration and unresolved collection limits remain explicit.' if completed_gamma else 'Follow 40 truth events and six selected responses: four positive responses and two selected true zeros. The other 34 responses stay unknown/unprocessed. Small engineering sample with unresolved collection limits and independent synthetic injection calibration.'
    learn='''<meta http-equiv="refresh" content="0;url=../spectra/pipeline.html"><section class="hero"><h1>Signal walkthrough</h1><p>The explanation and six saved signals now share one teaching page.</p><p><a href="../spectra/pipeline.html">Continue to the six signal examples →</a></p></section>'''
    write_page(site/'learn/index.html','Pipeline explanation · GeSignal',learn,1)

    featured_items=[x for x in catalog['detectors'] if x['id'] in control_ids]
    dedicated_items=[x for x in catalog['detectors'] if x['id'] in dedicated_ids]
    other_items=[x for x in catalog['detectors'] if x['id'] not in control_ids|dedicated_ids]
    det=('''<section class="hero"><p class="muted">Detector library</p><h1>Explore detector models</h1>
<p>Choose a detector to inspect its geometry, saved fields and signals. All 17 model definitions retain their original settings and provenance.</p></section>
<p id="current-ring-10k">Model definitions and saved studies are distinct; each model page identifies its available studies.</p>
<h2>LBNL cryostat · Control configurations</h2><p>'''+str(control_count)+''' supported local configurations in the <a href="../scenarios/lbnl-cs137/index.html">LBNL modular cryostat</a>. GeRC02 uses a separate Li50min operating variant; its library geometry is the original 30-minute model.</p><div class="grid">'''+detector_cards({'detectors':featured_items})+'''</div>
<h2>GeGI dedicated cryostat</h2><p>The <a href="../assemblies/gegi/index.html">GeGI cryostat</a> supports only the exact GeGI_3D model. It is a separate assembly at the same level as LBNL, with 34-electrode readout and Compton imaging.</p><div class="grid">'''+detector_cards({'detectors':dedicated_items})+'''</div>
<h2>More detector models</h2><p>These '''+str(blocked_count)+''' models need a future larger cryostat. Their pages show the actual dimension limits; all remain available for browsing.</p><div class="grid">'''+detector_cards({'detectors':other_items})+'''</div>''')
    write_page(site/'detectors/index.html','Detectors · GeSignal',det,1)
    assemblies=('''<section class="hero"><p class="muted">Cryostat assemblies</p><h1>Choose a compatible assembly</h1>
<p>LBNL and GeGI are separate cryostats. Detector selection never changes the assembly automatically. All 17 detector models remain browsable; six oversized models currently have no supported assembly.</p></section>
<div class="grid"><article class="card"><h2>LBNL modular cryostat</h2><p>'''+str(control_count)+''' compatible detector configurations with nominal source placement. Original upstream geometry provenance and model-specific limits remain explicit.</p><p><a href="../scenarios/lbnl-cs137/index.html">Assembly and compatibility →</a></p><p><a href="../viewers/events.html?model=AK02&amp;view=geometry">Rotate the saved LBNL assembly →</a></p></article>
<article class="card"><h2>GeGI cryostat</h2><p>Exact GeGI_3D only. Measured front layers and nominal side/rear enclosure; no other detector can be inserted.</p><p><a href="gegi/index.html">Rotate the GeGI assembly and inspect dimensions →</a></p><p><a href="../detectors/GeGI_3D/index.html">GeGI detector and workflow →</a></p></article></div>
<p><a href="../detectors/index.html">Browse detectors</a> · <a href="../guide.html#local-control">Configure and run locally</a> · <a href="../results/index.html">Read saved results</a></p>''')
    write_page(site/'assemblies/index.html','Assemblies · GeSignal',assemblies,1)
    def result_panel(ident,title,description,links,available=True,extra=''):
        actions=(' · '.join(f'<a href="{url}">{label}</a>' for url,label in links)
                 if available else 'This dataset is unavailable in this snapshot.')
        return (f'<section id="{ident}" class="panel" data-dataset="{ident}" style="margin:16px 0">'
                f'<h2>{title}</h2><p>{description}</p><p>{actions}</p>'+extra+'</section>')
    results='''<section class="hero"><p class="muted">Choose the dataset first</p><h1>Saved results</h1>
<p>Start with selected teaching signals or open a full saved study. Every primary ID belongs to its source detector case; complete studies retain zeros and unavailable responses.</p></section>'''
    teaching_present=(site/'examples/data.json').is_file()
    results+=result_panel('teaching','Start here · six representative Cs137 signals' if curated_teaching else 'Main teaching example · 200 gamma primaries',
        'A selected view of the completed four-case Cs137 10K study: near-line, low-energy, partial-deposition, separated-position, capped and fixed-wiring signals. The six examples are illustrative, not a statistical sample.' if curated_teaching else 'AK02 and SAP22 · 100 side-on primaries per detector · bare geometry. Start here to follow one event from radiation deposits to an energy measurement.',
        (('../spectra/pipeline.html','Open teaching example →'),),teaching_present)
    tenk_description=('AK02, SAP22, GeRC02 Li50min and KMRC01 candidate · 10,000 initial Cs137 decays in each of four separate cases. Charge/readout, stage spectra, radiation events and complete scalar ledgers.' if has_rings else
                      'AK02 and SAP22 · 10,000 initial Cs137 decays per detector in two separate cases.')
    results+=result_panel('tenk','Cs137 10K · '+('four detector cases' if has_rings else 'two detector cases'),tenk_description,
        (('cs137-10k/index.html','Choose a detector case →'),),has_10k,
        '<span id="current-ring-10k"></span>')
    results+=result_panel('million','Cs137 1M · two detector cases',
        'AK02 and SAP22 · one million initial decays per detector · nominal cryostat. Available views are ensemble truth/response spectra and complete scalar group records.',
        (('cs137-1m/index.html','Open 1M campaign →'),),has_1m)
    results+=result_panel('gegi','GeGI · multichannel Compton imaging',gegi_description,
        (('../'+gegi_route,'Open saved GeGI signals and imaging →'),),has_gegi,
        '<p>Conditional reconstruction on an imposed plane; same-energy separation remains unresolved and validated recoveries remain zero.</p>')
    results+='<h2>Other teaching studies</h2>'
    results+=result_panel('gamma','Cryostat gamma · 40 primaries',
        'AK02 and SAP22 · 20 primaries per detector · nominal cryostat. A separate monoenergetic source and event namespace.',
        (('../examples/gamma-native/gamma.html','Open cryostat gamma example →'),),has_gamma,
        '<details><summary>Processing and collection scope</summary><p>'+gamma_caption+'</p></details>' if has_gamma else '')
    results+='<details><summary>Historical teaching archive</summary><p><a data-original-report href="../examples/pipeline.html">Earlier bare-detector study · 200 initial gamma primaries</a>. Its records have a separate event namespace.</p><p><a href="../examples/gegi/index.html">Earlier GeGI two-position study · historical identity and original settings</a></p></details>'
    results+='<p><a href="../guide.html#saved-analysis">Help with settings, event identities and data files</a>. Saved engineering results do not establish experimental spectrum agreement or calibrated charge-collection efficiency.</p>'
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
<p>The radiation, semiconductor and electronics stages retain distinct quantities and identities. These saved engineering examples do not establish experimental agreement or calibrated charge-collection efficiency.</p></section>
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
    scenario+='<section class="panel"><h2>Physical compatibility</h2><p>Control offers '+str(control_count)+' separate detector configurations in the LBNL cryostat; its shared catalog and ring routes are distinct from the legacy <code>Run.cmd</code> adapter. The exact GeGI_3D has its own <a href="../../assemblies/gegi/index.html">dedicated GeGI cryostat</a> and is incompatible with LBNL. GeRC02 Li50min uses the separate operating variant, while the library retains the original 30-minute model. KM retains its candidate qualification, −370 V bias and fixed −1 electronics wiring.</p><p><a href="../../viewers/events.html?model=AK02&amp;view=geometry">Rotate saved LBNL assembly</a> · <a href="../../assemblies/index.html">Compare cryostat assemblies</a></p><details><summary>All model capabilities and legacy commands</summary><p>The older generic adapter selects AK02, SAP22 or both; both means separate serial cases. See the <a href="../../guide.html#choose">legacy commands</a>. All 17 catalog models can be viewed; '+str(blocked_count)+' require a future larger cryostat because of the recorded dimensions. Complete canonical inputs and original settings are retained. Runtime Check plan independently verifies actual setup, geometry, source and readout before Run.</p><table><thead><tr><th>Model</th><th>Contacts</th><th>Legacy Run.cmd</th><th>Control assembly</th></tr></thead><tbody>'+caprows+'</tbody></table></details></section>'
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
