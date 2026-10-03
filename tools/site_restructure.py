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

PRIMARY = ("Browse", "Setup", "Use")
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

def write_page(path,title,body,depth=0,*,fold_footer=False):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    up='../'*depth
    nav=(f'<a href="{up}results/index.html">Browse</a>'
         f'<a href="{up}detectors/index.html">Detectors</a>'
         f'<a href="{up}guide.html#setup">Setup</a>'
         f'<a href="{up}guide.html#local-control">Use</a>')
    footer=(f'<footer><a href="{up}learn/index.html">Learn the pipeline</a> · '
            f'<a href="{up}guide.html">Setup & run guide</a> · '
            f'<a href="{up}methods/index.html">Methods & limitations</a> · '
            f'<a href="{up}downloads/all-models.zip">Download all models</a> · '
            '<a href="https://github.com/Kunming-CN/END2END_Ge_Simulation">Code</a></footer>')
    if fold_footer:
        footer=footer.replace('<footer>','<footer><details><summary>More project resources</summary><p>',1).replace('</footer>','</p></details></footer>',1)
    html=(f'<!doctype html><html lang="en"><meta charset="utf-8">'
          f'<meta name="viewport" content="width=device-width,initial-scale=1">'
          f'<title>{escape(title)}</title><style>{STYLE}</style><body><main class="wrap">'
          f'<header class="top"><a href="{up}index.html"><strong>GeSignal</strong></a>'
          f'<nav aria-label="Primary">{nav}</nav></header>{body}{footer}</main></body></html>')
    path.write_text(html,encoding='utf-8',newline='\n')

def detector_cards(catalog):
    rows=[]
    for item in catalog['detectors']:
        ident=item['id']; require(re.fullmatch(r'[A-Za-z0-9_-]+',ident) is not None,'Unsafe detector ID')
        kind=detector_pages.TYPE_LABELS[ident];poster=f'{ident}/runs/{detector_pages.RUN}/01_geometry.png'
        rows.append(f'<article class="card"><a href="{escape(poster)}" aria-label="Open full-size {escape(ident)} geometry">'
                    f'<img loading="lazy" style="width:100%;height:220px;object-fit:contain" src="{escape(poster)}" '
                    f'alt="{escape(ident)} {escape(kind)}, saved geometry"></a>'
                    f'<h2><a href="{escape(ident)}/index.html">{escape(ident)}</a></h2><p>{escape(kind)}</p></article>')
    return ''.join(rows)
def apply(site):
    site=Path(site)
    require((site/'index.html').is_file(),'Site snapshot missing index')
    catalog=read(site/'models/catalog.json')
    capabilities=detector_pages.execution_capabilities()
    execution_ids={key for key,row in capabilities.items() if row['lbnl_execution_implemented']}
    control_ids=detector_pages.control_capabilities(capabilities)
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

    home=('''<section class="hero"><p class="muted">Saved HPGe simulations and local software</p>
<h1>From radiation to an energy measurement.</h1>
<p>Explore saved detector results, or set up GeSignal to run a supported calculation on your computer.</p></section>
<section class="cards">
<article class="card"><h2>Browse</h2><p><a href="results/index.html">Open saved results →</a></p><p>No installation needed. Inspect events, signals and spectra.</p><a href="detectors/index.html">Explore 17 detector models →</a></article>
<article class="card"><h2>Setup</h2><p><a href="guide.html#setup">Set up Windows →</a></p><p>Prepare the pinned environment, source files and exporter.</p></article>
<article class="card"><h2>Use</h2><p><a href="guide.html#local-control">Use Control →</a></p><p>On a prepared computer, choose AK02, SAP22 or either ring case and run the pipeline.</p></article></section>
<details class="panel"><summary>Pipeline, methods and earlier examples</summary><p><a href="learn/index.html">Learn the signal chain</a> · <a href="methods/index.html">Methods and limitations</a></p><p id="pipeline-example"><a href="examples/pipeline.html">Compact teaching example</a></p><p id="native-cs137-10k"><a href="results/cs137-10k/index.html">Cs137 10K results</a></p><p>Saved results are engineering simulations. Fresh-machine setup remains unvalidated.</p></details>''')
    from spectrum_display import homepage_preview
    preview=homepage_preview(site)
    if preview is not None:
        home+='<details class="panel"><summary>Separate 1M campaign spectrum preview</summary>'+preview+'</details>'
    write_page(site/'index.html','GeSignal',home,0,fold_footer=True)

    learn_example='''<article class="card"><h2>Compact teaching example</h2><p>Walk through deposits, charge, preamplifier, shaper and ADC in a compact example.</p><a href="../examples/pipeline.html">Open the compact teaching example →</a></article>'''
    if has_gamma:
        gamma_caption='Follow all 40 original primaries: 29 known zero inputs and 11 positive primaries. Native failures keep unknown charge and readout null. Collection-edge and full-window views preserve signed signals and original caps; independent synthetic injection calibration and unresolved collection limits remain explicit.' if completed_gamma else 'Follow 40 truth events and six selected responses: four positive responses and two selected true zeros. The other 34 responses stay unknown/unprocessed. Small engineering sample with unresolved collection limits and independent synthetic injection calibration.'
        learn_example='<article class="card"><h2>Explore saved gamma events</h2><p>'+gamma_caption+'</p><a href="../examples/gamma-native/gamma.html">Open the saved engineering example →</a><p><a href="../examples/pipeline.html">Compact teaching example →</a></p></article>'
    learn=('''<section class="hero"><p class="muted">Start here</p><h1>Radiation → charge → electronics</h1>
<p>Geant4/remage records where radiation deposits energy. SolidStateDetectors.jl transports electron/hole charge and calculates electrode signals. The electronics stage applies preamplifier, shaping and peak-ADC response.</p></section>
<div class="grid">'''+learn_example+'''
<article class="card"><h2>Run with Control</h2><p>Use the guide to set up Windows and choose one of four supported detector configurations. The <a href="../scenarios/lbnl-cs137/index.html">scenario page</a> records geometry and detector assumptions.</p><a href="../guide.html#local-control">Open Control instructions →</a></article></div>
<section class="panel"><h2>Important separation</h2><p>Geant4 deposition time is not carrier drift time. Deposited energy, induced charge, analog voltage, ADC code and reconstructed energy are retained as separate quantities.</p></section>''')
    write_page(site/'learn/index.html','Start here · GeSignal',learn,1)

    featured_items=[x for x in catalog['detectors'] if x['id'] in control_ids]
    other_items=[x for x in catalog['detectors'] if x['id'] not in control_ids]
    det=('''<section class="hero"><p class="muted">Detector library</p><h1>Explore detector models</h1>
<p>Choose a detector to inspect its geometry, saved fields and signals. All 17 model definitions retain their original settings and provenance.</p></section>
<h2>Control configurations</h2><p>Four supported local cases. GeRC02 uses a separate Li50min operating variant; its library geometry is the original 30-minute model.</p><div class="grid">'''+detector_cards({'detectors':featured_items})+'''</div>
<h2>More detector models</h2><p>These saved models are available for browsing; viewing does not enable a new Control calculation.</p><div class="grid">'''+detector_cards({'detectors':other_items})+'''</div>''')
    write_page(site/'detectors/index.html','Detectors · GeSignal',det,1)
    earlier_cards=[]
    example_cards=[]
    current='''<section class="panel"><h2>Current campaign unavailable in this snapshot</h2><p><a href="cs137-1m/index.html">View the stable 1M campaign overview</a> for availability details.</p></section>'''
    if has_1m:
        current='''<section class="panel"><h2>Separate Cs137 · 1M campaign</h2><p>AK02 and SAP22: saved Geant4 deposition truth, native SSD charge and synthetic peak ADC in the nominal LBNL cryostat.</p><a class="button" href="cs137-1m/index.html">Open 1M campaign →</a></section>'''
    if has_10k and not has_rings:
        earlier_cards.append('''<article class="card"><h2>Earlier Cs137 · 10k</h2><p>Engineering response, response ledgers and interactive recorded-event geometry.</p><a href="cs137-10k/index.html">Open earlier campaign →</a></article>''')
    if has_gamma:
        example_cards.append('<article class="card"><h2>Small gamma → native SSD → peak ADC example</h2><p>'+gamma_caption+'</p><a href="../examples/gamma-native/gamma.html">Inspect saved native charge and readout →</a></article>')
    example_cards.append('''<article class="card"><h2>Compact teaching example</h2><p>A selected event-by-event engineering demonstration of the signal chain.</p><a href="../examples/pipeline.html">Open example →</a></article>''')
    results=('''<section class="hero"><p class="muted">Saved simulations and campaign status</p><h1>Results</h1>
<p>Choose a saved campaign or a small example. Each retains its initial-decay census, zero events and unavailable responses.</p></section>'''+current+'''<h2>Small engineering examples</h2><div class="grid">'''+''.join(example_cards)+'''</div>''')
    if earlier_cards:
        results+='<h2>Earlier campaign</h2><div class="grid">'+''.join(earlier_cards)+'</div>'
    write_page(site/'results/index.html','Results · GeSignal',results,1)

    if has_1m:
        s=response_summary
        a=s['models']['AK02']; b=s['models']['SAP22']
        body=f'''<section class="hero"><p class="muted">Current completed campaign</p><h1>Cs137 · one million initial decays per detector</h1>
<p>Nominal uncollimated LBNL cryostat geometry. Radiation transport, SSD charge response and synthetic peak ADC are saved; no measured-spectrum fit or calibrated CCE is claimed.</p></section>
<div class="grid"><article class="card"><h2>AK02</h2><p>{a["positive_ge_decays"]:,} positive-Ge decays; {a["response"]["accepted"]:,} accepted ADC groups.</p></article>
<article class="card"><h2>SAP22</h2><p>{b["positive_ge_decays"]:,} positive-Ge decays; {b["response"]["accepted"]:,} accepted ADC groups.</p></article></div>
<section class="panel"><h2>Open the saved reports</h2>
<div style="display:grid;gap:12px;margin:16px 0">
<a class="button" style="display:flex;align-items:center;min-height:48px" href="../../examples/cs137-1m/report.html">Geant4 deposition truth</a>
<a class="button" style="display:flex;align-items:center;min-height:48px" href="../../examples/cs137-1m-response/report.html">Native SSD and peak-ADC comparison</a></div>
<p><a href="../../scenarios/lbnl-cs137/index.html">Scenario and geometry assumptions</a></p></section>
<section class="panel"><h2>Counting rules</h2><p>One million refers to initial Cs137 decays <strong>per detector</strong>. Positive deposits are grouped in isolated 100 µs reset windows; this is not an activity/live-time/pileup acquisition model. Native failures remain unknown responses and electronics rejection remains a separate outcome.</p></section>'''
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
    methods='''<section class="hero"><p class="muted">Technical depth</p><h1>Methods & limitations</h1>
<p>Detailed diagnostics remain available without occupying the first-time visitor path.</p></section>
<h2>Earlier diagnostic studies</h2><div class="grid"><article class="card"><h2>Li-region diagnostics</h2><p>Saved native diffusion, endpoint and grid-sensitivity studies; unresolved physical limits remain explicit.</p><a href="../lithium/lithium.html">Open diagnostics →</a></article>
<article class="card"><h2>Native Li through electronics</h2><p>Earlier selected-event provisional native response.</p><a href="../examples/native-li/comparison.html">Open selected study →</a></article></div>
<h2>Models and local workflow</h2><div class="grid">
<article class="card"><h2>Model distribution</h2><p>Original YAML configurations, includes and provenance.</p><a href="../models/README.md">Model guide →</a></article>
<article class="card"><h2>Setup & run guide</h2><p>Windows prerequisites and distinct new-run, replay and native-readout routes.</p><a href="../guide.html">Open guide →</a></article></div>'''
    write_page(site/'methods/index.html','Methods · GeSignal',methods,1)

    saved=[]
    if has_1m: saved.append('<a href="../../results/cs137-1m/index.html">1M-per-detector campaign</a>')
    if has_10k: saved.insert(0,'<a href="../../results/cs137-10k/index.html">Cs137 10K results</a>')
    saved_html=('<section class="panel"><h2>Saved campaigns</h2><p>'+ ' · '.join(saved)+'</p></section>') if saved else ''
    scenario='''<section class="hero"><p class="muted">Nominal engineering scenario</p><h1>LBNL cryostat + Cs137</h1>
<p>A Cs137 source above the curved aluminum cryostat wall. Control offers four separate detector configurations: AK02, SAP22, GeRC02 Li50min and KMRC01 candidate. The geometry/source pose is nominal, not an as-built survey.</p></section>
<div class="grid"><article class="card" id="ak02"><h2>AK02 case</h2><p>Primary Li-contact detector case; native response uses explicit 77 K override and the canonical model bias.</p><a href="../../detectors/AK02/index.html">AK02 detector page →</a></article>
<article class="card" id="sap22"><h2>SAP22 case</h2><p>Different-geometry non-Li cross-check; it is not a matched control detector.</p><a href="../../detectors/SAP22/index.html">SAP22 detector page →</a></article></div>'''+saved_html+'''
<section class="panel"><h2>Use a supported local case</h2><p>Follow <a href="../../guide.html#setup">Windows setup</a>, then <a href="../../guide.html#local-control">Use Control</a>. Cs137 supports 20 or 500 initial decays per case; the fixed 662 keV gamma beam supports 20 primaries for AK02/SAP22. A small sample may contain no Ge pulse. Fresh-machine reproduction remains unvalidated.</p><details><summary>Original source and advanced routes</summary><p>The pinned LBNL source files are not redistributed because no explicit license was found in the pinned upstream tree. The <a href="../../guide.html#setup">setup recipe</a> obtains and verifies exact originals under <code>.local/transport/LBNL</code>. See the <a href="https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/transport/cryostat-source.json">upstream manifest</a>.</p><p>Compatible saved-charge replay and earlier native-readout have separate private-input requirements in the <a href="../../guide.html#local-routes">guide</a>.</p></details></section>'''
    caprows=''.join('<tr><td><a href="../../detectors/'+escape(m['id'])+'/index.html">'+escape(m['id'])+'</a></td><td>'+str(len(m.get('contacts',[])))+'</td><td>'+('Implemented' if m['id'] in execution_ids else 'Not integrated')+'</td><td>'+('Supported' if m['id'] in control_ids else 'Browse only')+'</td></tr>' for m in catalog['detectors'])
    scenario+='<section class="panel"><h2>Execution support</h2><p>Control supports four cases; its ring adapters are distinct from the legacy <code>Run.cmd</code> adapter. GeRC02 Control uses the separate Li50min variant, while the library retains the original 30-minute model. KM retains its candidate qualification, −370 V bias and fixed −1 electronics wiring.</p><details><summary>All model capabilities and legacy commands</summary><p>The older generic adapter selects AK02, SAP22 or both; both means separate serial cases. See the <a href="../../guide.html#choose">legacy commands</a>. All 17 catalog models can be viewed, but additional execution requires checked geometry, placement and readout integration.</p><table><thead><tr><th>Model</th><th>Contacts</th><th>Legacy Run.cmd</th><th>Control</th></tr></thead><tbody>'+caprows+'</tbody></table></details></section>'
    write_page(site/'scenarios/lbnl-cs137/index.html','LBNL Cs137 scenario · GeSignal',scenario,2)

    (site/'guide.html').write_text((Path(__file__).resolve().parent/'site_guide.html').read_text(encoding='utf-8'),encoding='utf-8',newline='\n')
    from ssd_geometry_publication import refresh_viewers
    refresh_viewers(site)
    apply_detector_pages(site,write_page)
    return {'status':'applied','detectors':len(catalog['detectors']),
            'response_present':response.exists(),'truth_present':truth.exists()}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('site',type=Path);a=p.parse_args()
    print(json.dumps(apply(a.site),indent=2))
