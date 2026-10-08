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
        rows.append(f'<article class="card"><a href="{escape(ident)}/index.html" aria-label="{escape(ident)} detector overview">'
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
    catalog_control=detector_pages.catalog_control_capabilities(capabilities)
    control_count=len(control_ids)
    control_choices=', '.join(escape(item['id']) for item in catalog['detectors'] if item['id'] in control_ids)
    blocked_count=sum(not row['available'] for row in catalog_control.values())
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

    home=f'''<section class="hero"><p class="muted">HPGe radiation-to-readout simulation</p><h1>GeSignal</h1>
<p>Explore how radiation deposits become charge signals and an energy measurement: Geant4/remage → SolidStateDetectors.jl → preamplifier → shaping → peak ADC.</p>
<p>The public website contains saved engineering results. Run new simulations locally with Control.</p></section>
<section class="grid"><article class="card"><h2>Results</h2><p><a href="results/index.html">Choose a saved dataset →</a></p><p>Read saved waveforms, spectra, events and traceable data.</p></article>
<article class="card"><h2>Detectors</h2><p><a href="detectors/index.html">Explore 17 detector models →</a></p><p>Inspect geometry, saved fields and signals, or original model settings.</p></article>
<article class="card"><h2>Run locally</h2><p><a href="guide.html">Prepare your computer and use Control →</a></p><p>Choose one of {control_count} configurations available in the current cryostat.</p></article>
<article class="card"><h2>Methods</h2><p><a href="methods/index.html">Understand the pipeline and its limits →</a></p><p>Read the physical assumptions and saved diagnostic studies.</p></article></section>
<section class="panel" id="pipeline-example"><span id="native-cs137-10k"></span><span id="current-ring-10k"></span><p>Saved results are engineering simulations. Fresh-machine setup remains unvalidated.</p></section>'''
    write_page(site/'index.html','GeSignal',home,0,fold_footer=True)

    learn_example='''<section class="panel"><h2>Main teaching example</h2><p>Follow one saved bare-detector gamma event through deposits, charge, preamplifier, shaper and peak ADC.</p><a class="button" href="../spectra/pipeline.html">Open the teaching example →</a></section>'''
    if has_gamma:
        gamma_caption='Follow all 40 original primaries: 29 known zero inputs and 11 positive primaries. Native failures keep unknown charge and readout null. Collection-edge and full-window views preserve signed signals and original caps; independent synthetic injection calibration and unresolved collection limits remain explicit.' if completed_gamma else 'Follow 40 truth events and six selected responses: four positive responses and two selected true zeros. The other 34 responses stay unknown/unprocessed. Small engineering sample with unresolved collection limits and independent synthetic injection calibration.'
    learn=('''<section class="hero"><p class="muted">Pipeline explanation</p><h1>Radiation → charge → electronics</h1>
<p>Geant4/remage records where radiation deposits energy. SolidStateDetectors.jl transports electron/hole charge and calculates electrode signals. The electronics stage applies preamplifier, shaping and peak-ADC response.</p></section>
'''+learn_example+'''
<section class="panel"><h2>Important separation</h2><p>Geant4 deposition time is not carrier drift time. Deposited energy, induced charge, analog voltage, ADC code and reconstructed energy are retained as separate quantities.</p></section>''')
    write_page(site/'learn/index.html','Pipeline explanation · GeSignal',learn,1)

    featured_items=[x for x in catalog['detectors'] if x['id'] in control_ids]
    other_items=[x for x in catalog['detectors'] if x['id'] not in control_ids]
    det=('''<section class="hero"><p class="muted">Detector library</p><h1>Explore detector models</h1>
<p>Choose a detector to inspect its geometry, saved fields and signals. All 17 model definitions retain their original settings and provenance.</p></section>
<p id="current-ring-10k">Model definitions and saved studies are distinct; each model page identifies its available studies.</p>
<h2>Control configurations</h2><p>'''+str(control_count)+''' supported local configurations. GeRC02 uses a separate Li50min operating variant; its library geometry is the original 30-minute model.</p><div class="grid">'''+detector_cards({'detectors':featured_items})+'''</div>
<h2>More detector models</h2><p>These '''+str(blocked_count)+''' models need a future larger cryostat. Their pages show the actual dimension limits; all remain available for browsing.</p><div class="grid">'''+detector_cards({'detectors':other_items})+'''</div>''')
    write_page(site/'detectors/index.html','Detectors · GeSignal',det,1)
    def result_panel(ident,title,description,links,available=True,extra=''):
        actions=(' · '.join(f'<a href="{url}">{label}</a>' for url,label in links)
                 if available else 'This dataset is unavailable in this snapshot.')
        return (f'<section id="{ident}" class="panel" data-dataset="{ident}" style="margin:16px 0">'
                f'<h2>{title}</h2><p>{description}</p><p>{actions}</p>'+extra+'</section>')
    results='''<section class="hero"><p class="muted">Choose the dataset first</p><h1>Saved results</h1>
<p>These are different saved studies. Open a dataset, then select its detector and view. Primary IDs belong to their own dataset; counts include zero-deposit events and unavailable responses.</p></section>'''
    teaching_present=(site/'examples/data.json').is_file()
    results+=result_panel('teaching','Main teaching example · 200 gamma primaries',
        'AK02 and SAP22 · 100 side-on primaries per detector · bare geometry. Start here to follow one event from radiation deposits to an energy measurement.',
        (('../spectra/pipeline.html','Open teaching example →'),),teaching_present)
    results+=result_panel('gamma','Cryostat gamma · 40 primaries',
        'AK02 and SAP22 · 20 primaries per detector · nominal cryostat. Saved waveforms and event ledger. Different geometry and event IDs from the teaching example.',
        (('../examples/gamma-native/gamma.html','Open cryostat gamma example →'),),has_gamma,
        '<details><summary>Processing and collection scope</summary><p>'+gamma_caption+'</p></details>' if has_gamma else '')
    tenk_description=('AK02, SAP22, GeRC02 Li50min and KMRC01 candidate · 10,000 initial Cs137 decays in each of four separate cases. Charge/readout, stage spectra, radiation events and complete scalar ledgers.' if has_rings else
                      'AK02 and SAP22 · 10,000 initial Cs137 decays per detector in two separate cases.')
    results+=result_panel('tenk','Cs137 10K · '+('four detector cases' if has_rings else 'two detector cases'),tenk_description,
        (('cs137-10k/index.html','Choose a detector case →'),),has_10k,
        '<span id="current-ring-10k"></span>')
    results+=result_panel('million','Cs137 1M · two detector cases',
        'AK02 and SAP22 · one million initial decays per detector · nominal cryostat. Available views are ensemble truth/response spectra and complete scalar group records.',
        (('cs137-1m/index.html','Open 1M campaign →'),),has_1m)
    results+='<p><a href="../guide.html#saved-analysis">Help with settings, event identities and data files</a>. Saved engineering results do not establish experimental spectrum agreement or calibrated charge-collection efficiency.</p>'
    write_page(site/'results/index.html','Results · GeSignal',results,1)

    if has_1m:
        s=response_summary
        a=s['models']['AK02']; b=s['models']['SAP22']
        body=f'''<section class="hero"><p class="muted">Separate completed campaign</p><h1>Cs137 · one million initial decays per detector</h1>
<p>Nominal uncollimated LBNL cryostat geometry. Radiation transport, SSD charge response and synthetic peak ADC are saved; no measured-spectrum fit or calibrated CCE is claimed.</p></section>
<div class="grid"><article class="card"><h2>AK02</h2><p>{a["positive_ge_decays"]:,} positive-Ge decays; {a["response"]["accepted"]:,} accepted ADC groups.</p></article>
<article class="card"><h2>SAP22</h2><p>{b["positive_ge_decays"]:,} positive-Ge decays; {b["response"]["accepted"]:,} accepted ADC groups.</p></article></div>
<section class="panel" id="data-files"><h2>Data & settings</h2>
<p><a href="../../examples/cs137-1m-response/groups.csv.gz">Complete saved response group records (CSV gzip)</a> · <a href="../../examples/cs137-1m-response/summary.json">Response settings and counts (JSON)</a> · <a href="../../examples/cs137-1m/summary.json">Transport summary (JSON)</a></p>
<details><summary>Original saved reports</summary><p><a data-original-report href="../../examples/cs137-1m/report.html">Original deposition-truth report</a> · <a data-original-report href="../../examples/cs137-1m-response/report.html">Original response report</a></p></details>
<p>Public scalar records do not contain every full waveform, private field cache or original LH5 file.</p></section>
<section class="panel"><h2>Counting rules</h2><p>One million refers to initial Cs137 decays <strong>per detector</strong>. Positive deposits are grouped in isolated 100 µs reset windows; this is not an activity/live-time/pileup acquisition model. Native failures remain unknown responses and electronics rejection remains a separate outcome.</p></section>'''
        from spectrum_display import homepage_preview
        preview=homepage_preview(site)
        if preview is not None:
            body+='<section class="panel"><h2>Campaign spectrum preview</h2>'+preview+'</section>'
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
<div class="grid"><article class="card"><h2>Radiation to readout</h2><p>Deposits, charge, preamplifier, shaping and peak ADC.</p><a href="../learn/index.html">Read pipeline explanation →</a></article>
<article class="card"><h2>Nominal cryostat and source</h2><p>Geometry, compatibility, source placement and physical assumptions.</p><a href="../scenarios/lbnl-cs137/index.html">Read scenario assumptions →</a></article>
<article class="card"><h2>Li-region diagnostics</h2><p>Native diffusion, endpoints and grid sensitivity; unresolved limits remain explicit.</p><a href="../lithium/lithium.html">Open saved diagnostics →</a></article>
<article class="card"><h2>Native Li through electronics</h2><p>Earlier selected-event provisional response, preserved independently of other studies.</p><a href="../examples/native-li/comparison.html">Open selected study →</a></article></div>'''
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
<p>The supported local source definitions are Cs137, Am241 and Ba133; Co60 remains unavailable under its unchanged admission gate. The separate fixed 662 keV gamma beam uses 20 primaries for AK02/SAP22. It is not an isotope-decay campaign.</p>
<details><summary>Original geometry provenance</summary><p>The pinned LBNL source files are not redistributed because no explicit license was found in the pinned upstream tree. The <a href="https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/transport/cryostat-source.json">upstream manifest</a> identifies the exact inputs. The maintained <a href="../../guide.html">local guide</a> explains preparation and use.</p></details></section>'''
    caprows=''.join('<tr><td><a href="../../detectors/'+escape(m['id'])+'/index.html">'+escape(m['id'])+'</a></td><td>'+str(len(m.get('contacts',[])))+'</td><td>'+('Implemented' if m['id'] in execution_ids else 'Not integrated')+'</td><td>'+('Available in current cryostat' if m['id'] in control_ids else 'Needs larger cryostat: '+escape(catalog_control[m['id']]['reason']))+'</td></tr>' for m in catalog['detectors'])
    scenario+='<section class="panel"><h2>Physical compatibility</h2><p>Control offers '+str(control_count)+' separate detector configurations in the current cryostat; its shared catalog and ring routes are distinct from the legacy <code>Run.cmd</code> adapter. GeRC02 Li50min uses the separate operating variant, while the library retains the original 30-minute model. KM retains its candidate qualification, −370 V bias and fixed −1 electronics wiring.</p><details><summary>All model capabilities and legacy commands</summary><p>The older generic adapter selects AK02, SAP22 or both; both means separate serial cases. See the <a href="../../guide.html#choose">legacy commands</a>. All 17 catalog models can be viewed; '+str(blocked_count)+' require a future larger cryostat because of the recorded dimensions. Complete canonical inputs and original settings are retained. Runtime Check plan independently verifies actual setup, geometry, source and readout before Run.</p><table><thead><tr><th>Model</th><th>Contacts</th><th>Legacy Run.cmd</th><th>Control</th></tr></thead><tbody>'+caprows+'</tbody></table></details></section>'
    write_page(site/'scenarios/lbnl-cs137/index.html','Nominal LBNL cryostat · GeSignal',scenario,2)

    (site/'guide.html').write_text((Path(__file__).resolve().parent/'site_guide.html').read_text(encoding='utf-8').replace('__PAGE_NAVIGATION__',page_navigation('guide.html')),encoding='utf-8',newline='\n')
    from ssd_geometry_publication import refresh_viewers
    refresh_viewers(site)
    apply_detector_pages(site,write_page)
    return {'status':'applied','detectors':len(catalog['detectors']),
            'response_present':response.exists(),'truth_present':truth.exists()}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('site',type=Path);a=p.parse_args()
    print(json.dumps(apply(a.site),indent=2))
