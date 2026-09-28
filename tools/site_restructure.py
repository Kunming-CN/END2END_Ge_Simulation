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
from site_previews import add_previews

PRIMARY = ("Start here", "Explore detectors", "Results")
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

def write_page(path,title,body,depth=0):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    up='../'*depth
    nav=(f'<a href="{up}learn/index.html">Start here</a>'
         f'<a href="{up}detectors/index.html">Explore detectors</a>'
         f'<a href="{up}results/index.html">Results</a>')
    footer=(f'<footer><a href="{up}guide.html">Guide</a> · '
            f'<a href="{up}methods/index.html">Methods & limitations</a> · '
            f'<a href="{up}downloads/all-models.zip">Download all models</a> · '
            '<a href="https://github.com/Kunming-CN/END2END_Ge_Simulation">Code</a></footer>')
    html=(f'<!doctype html><html lang="en"><meta charset="utf-8">'
          f'<meta name="viewport" content="width=device-width,initial-scale=1">'
          f'<title>{escape(title)}</title><style>{STYLE}</style><body><main class="wrap">'
          f'<header class="top"><a href="{up}index.html"><strong>END2END Ge Simulation</strong></a>'
          f'<nav aria-label="Primary">{nav}</nav></header>{body}{footer}</main></body></html>')
    path.write_text(html,encoding='utf-8',newline='\n')

def detector_cards(catalog):
    featured={'AK02':'Primary Li-contact case','SAP22':'Non-Li cross-check'}
    rows=[]
    for item in catalog['detectors']:
        ident=item['id']; require(re.fullmatch(r'[A-Za-z0-9_-]+',ident) is not None,'Unsafe detector ID')
        desc=featured.get(ident,item.get('status','Detector model'))
        rows.append(f'<article class="card"><h2><a href="{escape(ident)}/index.html">{escape(ident)}</a></h2>'
                    f'<p>{escape(desc)}</p><span class="tag">{len(item.get("contacts",[]))} contacts</span>'
                    f'<span class="tag">{escape(item.get("coordinate_system",""))}</span></article>')
    return ''.join(rows)
def apply(site):
    site=Path(site)
    require((site/'index.html').is_file(),'Site snapshot missing index')
    catalog=read(site/'models/catalog.json')
    capabilities=detector_pages.execution_capabilities()
    execution_ids={key for key,row in capabilities.items() if row['lbnl_execution_implemented']}
    require(len(catalog.get('detectors',[]))>=2,'Detector catalog missing')

    response=site/'examples/cs137-1m-response/summary.json'
    truth=site/'examples/cs137-1m/summary.json'
    response_summary=read(response) if response.exists() else None
    has_1m=response.exists() and truth.exists()
    has_10k=(site/'examples/cs137-10k/comparison.html').exists()
    has_hit_view=(site/'examples/cs137-10k-hits/hit_event_view.html').exists()

    home=('''<section class="hero"><p class="muted">Precomputed HPGe detector simulations</p>
<h1>From radiation to an energy measurement.</h1>
<p>Explore detector geometry and follow radiation deposits through charge collection and electronics.</p></section>
<section class="cards">
<article class="card"><h2>Start here</h2><p>Follow the chain from an energy deposit through charge collection and electronics.</p><a href="learn/index.html">Learn the pipeline →</a></article>
<article class="card"><h2>Explore detectors</h2><p>Browse the model library and inspect detector contacts and saved field/response views.</p><a href="detectors/index.html">Open detector library →</a></article>
<article class="card"><h2>Results</h2><p>Compare deposited and reconstructed energy in completed campaigns.</p><a href="results/index.html">Open results →</a></article></section>'''
          +'''
<section class="panel"><h2>Run it locally</h2><p>The <code>Run.cmd</code> workflow implements __EXECUTION_CASES__ selection. Prepare the pinned dependencies and cryostat inputs first. Positive uninstrumented launcher runs and fresh-machine reproduction remain unvalidated.</p><a class="button" href="guide.html#setup">Start the Windows setup checklist →</a> · <a href="scenarios/lbnl-cs137/index.html">Scenario details</a></section>
<p><a href="downloads/all-models.zip">Download all detector models</a></p>''')
    home=home.replace('Download all detector models',f'Download all {len(catalog["detectors"])} detector models')
    home=home.replace('__EXECUTION_CASES__',' / '.join(sorted(execution_ids)))
    home=add_previews(site,home)
    write_page(site/'index.html','END2END Ge Simulation',home,0)

    learn=('''<section class="hero"><p class="muted">Start here</p><h1>Radiation → charge → electronics</h1>
<p>Geant4/remage records where radiation deposits energy. SolidStateDetectors.jl transports electron/hole charge and calculates electrode signals. The electronics stage applies preamplifier, shaping and peak-ADC response.</p></section>
<div class="grid"><article class="card"><h2>Explore a saved event</h2><p>Walk through deposits, charge, preamplifier, shaper and ADC in a compact example.</p><a href="../examples/pipeline.html">Open the engineering example →</a></article>
<article class="card"><h2>Run the reviewed LBNL scenario</h2><p>The Windows <code>Run.cmd</code> launcher checks the pinned environment, lets you choose AK02/SAP22/both and a 20/500/10k preset, preserves completed stages, and opens local results.</p><a href="../scenarios/lbnl-cs137/index.html">Open scenario & launcher guide →</a></article></div>
<section class="panel"><h2>Important separation</h2><p>Geant4 deposition time is not carrier drift time. Deposited energy, induced charge, analog voltage, ADC code and reconstructed energy are retained as separate quantities.</p></section>''')
    write_page(site/'learn/index.html','Start here · END2END Ge Simulation',learn,1)

    featured_items=[x for x in catalog['detectors'] if x['id'] in execution_ids]
    other_items=[x for x in catalog['detectors'] if x['id'] not in execution_ids]
    det=('''<section class="hero"><p class="muted">Detector library</p><h1>Explore detector models</h1>
<p>Models with implemented LBNL selections are shown first. All models retain their geometry, saved galleries and original downloads; viewing does not establish execution support.</p></section>
<h2>Implemented LBNL selections</h2><div class="grid">'''+detector_cards({'detectors':featured_items})+'''</div>
<h2>Full model library</h2><div class="grid">'''+detector_cards({'detectors':other_items})+'''</div>''')
    write_page(site/'detectors/index.html','Detectors · END2END Ge Simulation',det,1)
    result_cards=[]
    if has_1m:
        result_cards.append('''<article class="card"><h2>Cs137 · 1M per detector</h2><p>Completed nominal LBNL cryostat campaign: Geant4 truth → native SSD → synthetic peak ADC.</p><a href="cs137-1m/index.html">Open campaign overview →</a></article>''')
    if has_10k:
        result_cards.append('''<article class="card"><h2>Earlier Cs137 · 10k</h2><p>Engineering response, response ledgers and interactive recorded-event geometry.</p><a href="cs137-10k/index.html">Open earlier campaign →</a></article>''')
    result_cards.append('''<article class="card"><h2>Small engineering example</h2><p>A compact event-by-event demonstration of the complete signal chain.</p><a href="../examples/pipeline.html">Open example →</a></article>''')
    results=('''<section class="hero"><p class="muted">Completed simulations</p><h1>Results</h1>
<p>Campaign pages keep initial-decay denominators, zero-deposit events, unavailable native responses and electronics rejection separate.</p></section><div class="grid">'''+''.join(result_cards)+'''</div>''')
    write_page(site/'results/index.html','Results · END2END Ge Simulation',results,1)

    if has_1m:
        s=response_summary
        a=s['models']['AK02']; b=s['models']['SAP22']
        body=f'''<section class="hero"><p class="muted">Completed campaign</p><h1>Cs137 · one million initial decays per detector</h1>
<p>Nominal uncollimated LBNL cryostat geometry. Radiation transport, SSD charge response and synthetic peak ADC are saved; no measured-spectrum fit or calibrated CCE is claimed.</p></section>
<div class="grid"><article class="card"><h2>AK02</h2><p>{a["positive_ge_decays"]:,} positive-Ge decays; {a["response"]["accepted"]:,} accepted ADC groups.</p></article>
<article class="card"><h2>SAP22</h2><p>{b["positive_ge_decays"]:,} positive-Ge decays; {b["response"]["accepted"]:,} accepted ADC groups.</p></article></div>
<section class="panel"><h2>Open the saved reports</h2>
<p><a href="../../examples/cs137-1m/report.html">Geant4 deposition truth</a> · <a href="../../examples/cs137-1m-response/report.html">Native SSD and peak-ADC comparison</a></p>
<p><a href="../../scenarios/lbnl-cs137/index.html">Scenario and geometry assumptions</a></p></section>
<section class="panel"><h2>Counting rules</h2><p>One million refers to initial Cs137 decays <strong>per detector</strong>. Positive deposits are grouped in isolated 100 µs reset windows; this is not an activity/live-time/pileup acquisition model. Native failures remain unknown responses and electronics rejection remains a separate outcome.</p></section>'''
        write_page(site/'results/cs137-1m/index.html','Cs137 1M results · END2END Ge Simulation',body,2)

    else:
        body='''<section class="hero"><p class="muted">Campaign overview unavailable in this snapshot</p><h1>Cs137 · one million initial decays per detector</h1><p>The generated overview is retained at this stable URL, but this site snapshot does not include both checked truth and response summaries. Use the Results page for currently available campaigns.</p></section>'''
        write_page(site/'results/cs137-1m/index.html','Cs137 1M results unavailable · END2END Ge Simulation',body,2)

    if has_10k:
        body='''<section class="hero"><p class="muted">Earlier engineering campaign</p><h1>Cs137 · 10k initial decays per detector</h1><p>This smaller run established the event-complete Geant4 → SSD → electronics workflow before the million-decay campaign.</p></section>
<div class="grid"><article class="card"><h2>Response comparison</h2><a href="../../examples/cs137-10k/comparison.html">Open 10k response report →</a></article>
<article class="card"><h2>Geometry and events</h2><a href="../../examples/cs137-10k-geometry/geometry.html">Rotate cryostat geometry and inspect events →</a></article>
<article class="card"><h2>Ge-hit overlay</h2><a href="../../examples/cs137-10k-hits/hit_event_view.html">Open saved Ge-hit examples →</a></article></div>
<p><a href="../../scenarios/lbnl-cs137/index.html">Nominal scenario context</a></p>'''
        write_page(site/'results/cs137-10k/index.html','Cs137 10k results · END2END Ge Simulation',body,2)
    else:
        body='''<section class="hero"><p class="muted">Campaign overview unavailable in this snapshot</p><h1>Cs137 · 10k initial decays per detector</h1><p>This stable overview URL is retained, but the checked 10k comparison is not included in this site snapshot. Use the Results page for currently available campaigns.</p></section>'''
        write_page(site/'results/cs137-10k/index.html','Cs137 10k results unavailable · END2END Ge Simulation',body,2)
    methods='''<section class="hero"><p class="muted">Technical depth</p><h1>Methods & limitations</h1>
<p>Detailed diagnostics remain available without occupying the first-time visitor path.</p></section>
<div class="grid"><article class="card"><h2>Li-region diagnostics</h2><p>Native diffusion, endpoints and grid sensitivity.</p><a href="../lithium/lithium.html">Open diagnostics →</a></article>
<article class="card"><h2>Native Li through electronics</h2><p>Selected-event provisional native response.</p><a href="../examples/native-li/comparison.html">Open selected study →</a></article>
<article class="card"><h2>Model distribution</h2><p>Original YAML configurations, includes and provenance.</p><a href="../models/README.md">Model guide →</a></article>
<article class="card"><h2>Reproduction guide</h2><p>Current local CPU and transport setup.</p><a href="../guide.html">Open guide →</a></article></div>'''
    write_page(site/'methods/index.html','Methods · END2END Ge Simulation',methods,1)

    saved=[]
    if has_1m: saved.append('<a href="../../results/cs137-1m/index.html">1M-per-detector campaign</a>')
    if has_10k: saved.append('<a href="../../results/cs137-10k/index.html">earlier 10k campaign</a>')
    saved_html=('<section class="panel"><h2>Saved campaigns</h2><p>'+ ' · '.join(saved)+'</p></section>') if saved else ''
    scenario='''<section class="hero"><p class="muted">Nominal engineering scenario</p><h1>LBNL cryostat + Cs137</h1>
<p>A Cs137 source above the curved aluminum cryostat wall, with AK02 or SAP22 simulated as separate detector cases. The geometry/source pose is nominal, not an as-built survey.</p></section>
<div class="grid"><article class="card" id="ak02"><h2>AK02 case</h2><p>Primary Li-contact detector case; native response uses explicit 77 K override and the canonical model bias.</p><a href="../../detectors/AK02/index.html">AK02 detector page →</a></article>
<article class="card" id="sap22"><h2>SAP22 case</h2><p>Different-geometry non-Li cross-check; it is not a matched control detector.</p><a href="../../detectors/SAP22/index.html">SAP22 detector page →</a></article></div>'''+saved_html+'''
<section class="panel"><h2>Run a supported local case</h2><p>Prepare the Windows setup checklist first. Positive uninstrumented launcher runs and fresh-machine reproduction remain unvalidated.</p><p>After preparation, double-click <code>Run.cmd</code>, or use <code>.\\Run.cmd check</code>, <code>.\\Run.cmd run -Preset demo -Detector both</code>, <code>.\\Run.cmd resume -Name RUN_NAME</code>, and <code>.\\Run.cmd open -Name RUN_NAME</code>. The default demo is 500 initial decays per selected detector; smoke is 20 and may produce no Ge pulse; 10k requires a verified 500-event pilot. Setup never silently substitutes geometry or installs unreviewed physics.</p><p>The pinned LBNL source files are not redistributed because no explicit license was found in the pinned upstream tree; the launcher verifies exact originals under <code>.local/transport/LBNL</code>. See the <a href="../../guide.html">detailed setup guide</a> and <a href="https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/transport/cryostat-source.json">upstream manifest</a>.</p></section>'''
    caprows=''.join('<tr><td><a href="../../detectors/'+escape(m['id'])+'/index.html">'+escape(m['id'])+'</a></td><td>'+str(len(m.get('contacts',[])))+'</td><td>'+('Implemented' if m['id'] in execution_ids else 'Not yet integrated')+'</td></tr>' for m in catalog['detectors'])
    scenario+='<section class="panel"><h2>Choose a detector locally</h2><p>Run <code>.\\Run.cmd detectors</code> to inspect the local capability list. Select <code>-Detector AK02</code>, <code>-Detector SAP22</code>, or <code>-Detector both</code>; both means separate serial cases through the same end-to-end chain, not two crystals in one assembly.</p><p>All catalog models can be viewed in 3D. Additional LBNL models require geometry/placement and readout integration; they are not enabled merely by appearing in this table. Positive uninstrumented launcher and fresh-machine reproduction remain unvalidated.</p><table><thead><tr><th>Model</th><th>Contacts</th><th>LBNL execution adapter</th></tr></thead><tbody>'+caprows+'</tbody></table></section>'
    write_page(site/'scenarios/lbnl-cs137/index.html','LBNL Cs137 scenario · END2END Ge Simulation',scenario,2)

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
