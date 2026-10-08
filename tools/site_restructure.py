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

PRIMARY = ("Run", "Saved results", "Detectors", "Help")
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

def navigation(up=''):
    """Task routes; selecting a saved view belongs to its dataset context."""
    links=(('guide.html#local-control','Run'),('results/index.html','Saved results'),
           ('detectors/index.html','Detectors'),('guide.html#saved-analysis','Help'))
    return '<nav aria-label="Primary" style="display:flex;gap:8px;flex-wrap:wrap">'+''.join(
        f'<a href="{up}{path}" style="padding:8px 10px">{label}</a>' for path,label in links)+'</nav>'

def dataset_navigation(dataset,up=''):
    """Name one saved dataset and link only to its existing views."""
    contexts={
        'teaching':('Teaching gamma · 200 primaries total (100 per detector) · bare geometry',
                    (('spectra/pipeline.html','Waveforms and spectrum'),('learn/index.html','Pipeline explanation'))),
        'gamma':('Cryostat gamma · 40 primaries total (20 per detector) · nominal cryostat',
                 (('examples/gamma-native/gamma.html','Waveforms and event ledger'),)),
        'tenk':('Cs137 10K · 10,000 initial decays per detector · four separate cryostat cases',
                (('results/cs137-10k/index.html','Detector cases'),('spectra/cs137-10k.html','Stage spectra'),('viewers/events.html','3D radiation events'))),
        'million':('Cs137 1M · 1,000,000 initial decays per detector · two separate cryostat cases',
                   (('results/cs137-1m/index.html','Campaign summary'),('spectra/million-truth.html','Deposition spectra'),('spectra/million-response.html','Response spectra'))),
    }
    require(dataset in contexts,'Unknown saved dataset')
    description,links=contexts[dataset]
    return ('<section class="dataset-context" aria-label="Saved dataset" style="padding:12px 0">'
            '<p><strong>'+escape(description)+'</strong> · '
            f'<a href="{up}results/index.html#{dataset}">Saved results</a></p>'
            '<nav aria-label="Dataset views" style="display:flex;gap:12px;flex-wrap:wrap">'+
            ''.join(f'<a href="{up}{path}">{label}</a>' for path,label in links)+'</nav></section>')

def write_page(path,title,body,depth=0,*,fold_footer=False):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    up='../'*depth
    nav=navigation(up)
    footer=(f'<footer><a href="{up}learn/index.html">Learn the pipeline</a> · '
            f'<a href="{up}guide.html">Setup & run guide</a> · '
            f'<a href="{up}methods/index.html">Methods & limitations</a> · '
            f'<a href="{up}downloads/all-models.zip">Download all models</a> · '
            '<a href="https://github.com/Kunming-CN/END2END_Ge_Simulation">Code</a> · '
            f'<a href="{up}LICENSE">MIT software license</a> · '
            '<a href="https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/THIRD_PARTY_NOTICES.md">Third-party and data rights</a></footer>')
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

    home=('''<section class="hero"><p class="muted">Saved HPGe simulations and local software</p>
<h1>From radiation to an energy measurement.</h1>
<p>Choose a task. The saved website works without installation; new calculations run through Control on your own computer.</p></section>
<section class="grid">
<article class="card"><h2>Run</h2><p><a href="guide.html#local-control">Use Control →</a></p><p>Check a setup and run one of '''+str(control_count)+''' configurations available in the current cryostat.</p><a href="guide.html#setup">First-time Windows setup</a></article>
<article class="card"><h2>Saved results</h2><p><a href="results/index.html">Choose a saved dataset →</a></p><p>Start with the teaching example, or choose a gamma or Cs137 campaign. Each dataset names its available waveforms, spectra, radiation views and files.</p></article>
<article class="card"><h2>Detectors</h2><p><a href="detectors/index.html">Explore 17 detector models →</a></p><p>Inspect geometry, saved fields and signals, or original model settings.</p></article>
<article class="card"><h2>Help</h2><p><a href="guide.html#saved-analysis">Understand a saved run →</a></p><p>Find event identities, settings, data files, and instructions for viewing a saved result.</p></article></section>
<details class="panel"><summary>Methods and retained links</summary><p><a href="learn/index.html">Pipeline explanation</a> · <a href="methods/index.html">Methods and limitations</a></p><p id="pipeline-example"><a href="results/index.html#teaching">Main teaching dataset</a></p><p id="native-cs137-10k"><a href="results/index.html#tenk">Cs137 10K dataset</a></p><p id="current-ring-10k"><a href="results/cs137-10k/index.html">Four-detector Cs137 10K</a></p><p>Saved results are engineering simulations. Fresh-machine setup remains unvalidated.</p></details>''')
    from spectrum_display import homepage_preview
    preview=homepage_preview(site)
    if preview is not None:
        home+='<details class="panel"><summary>Separate 1M campaign spectrum preview</summary>'+preview+'</details>'
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
<p id="current-ring-10k"><a href="../results/index.html#tenk">Saved Cs137 10K source-campaign cases</a></p>
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
        (('../spectra/pipeline.html','Waveforms, spectrum and event ledger'),('../examples/data.json','Exact saved data (JSON)')),teaching_present)
    results+=result_panel('gamma','Cryostat gamma · 40 primaries',
        'AK02 and SAP22 · 20 primaries per detector · nominal cryostat. Different geometry and event IDs from the teaching example.',
        (('../examples/gamma-native/gamma.html','Waveforms and event ledger'),('../examples/gamma-native/data.json','Exact saved data (JSON)')),has_gamma,
        '<details><summary>Processing and collection scope</summary><p>'+gamma_caption+'</p></details>' if has_gamma else '')
    tenk_description=('AK02, SAP22, GeRC02 Li50min and KMRC01 candidate · 10,000 initial Cs137 decays in each of four separate cases.' if has_rings else
                      'AK02 and SAP22 · 10,000 initial Cs137 decays per detector in two separate cases.')
    results+=result_panel('tenk','Cs137 10K · '+('four detector cases' if has_rings else 'two detector cases'),tenk_description,
        (('cs137-10k/index.html','Choose a detector for charge/readout and complete data'),('../spectra/cs137-10k.html','Stage spectra'),('../viewers/events.html','3D radiation events')),has_10k,
        '<span id="current-ring-10k"></span>')
    results+=result_panel('million','Cs137 1M · two detector cases',
        'AK02 and SAP22 · one million initial decays per detector · nominal cryostat. Available views are ensemble truth/response spectra and complete scalar group records.',
        (('cs137-1m/index.html','Campaign summary'),('../spectra/million-truth.html','Deposition spectra'),('../spectra/million-response.html','Response spectra'),('../examples/cs137-1m-response/groups.csv.gz','All saved group records')),has_1m)
    results+='<p><a href="../guide.html#saved-analysis">Help with settings, event identities and data files</a>. Saved engineering results do not establish experimental spectrum agreement or calibrated charge-collection efficiency.</p>'
    write_page(site/'results/index.html','Results · GeSignal',results,1)

    if has_1m:
        s=response_summary
        a=s['models']['AK02']; b=s['models']['SAP22']
        body=dataset_navigation('million','../../')+f'''<section class="hero"><p class="muted">Separate completed campaign</p><h1>Cs137 · one million initial decays per detector</h1>
<p>Nominal uncollimated LBNL cryostat geometry. Radiation transport, SSD charge response and synthetic peak ADC are saved; no measured-spectrum fit or calibrated CCE is claimed.</p></section>
<div class="grid"><article class="card"><h2>AK02</h2><p>{a["positive_ge_decays"]:,} positive-Ge decays; {a["response"]["accepted"]:,} accepted ADC groups.</p></article>
<article class="card"><h2>SAP22</h2><p>{b["positive_ge_decays"]:,} positive-Ge decays; {b["response"]["accepted"]:,} accepted ADC groups.</p></article></div>
<section class="panel"><h2>Open the saved reports</h2>
<div style="display:grid;gap:12px;margin:16px 0">
<a class="button" style="display:flex;align-items:center;min-height:48px" href="../../spectra/million-truth.html">Geant4 deposition truth</a>
<a class="button" style="display:flex;align-items:center;min-height:48px" href="../../spectra/million-response.html">Native SSD and peak-ADC comparison</a></div>
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
    if (site/'examples/native-li/comparison.html').is_file():
        from saved_archive_display import assemble as assemble_archive_display
        assemble_archive_display(site)
        methods=methods.replace('href="../examples/native-li/comparison.html">Open selected study →',
                                'href="native-li.html">Open readable saved plots →',1)
    write_page(site/'methods/index.html','Methods · GeSignal',methods,1)

    saved=[]
    if has_1m: saved.append('<a href="../../results/cs137-1m/index.html">1M-per-detector campaign</a>')
    if has_10k: saved.insert(0,'<a href="../../results/cs137-10k/index.html">Cs137 10K results</a>')
    saved_html=('<section class="panel"><h2>Saved campaigns</h2><p>'+ ' · '.join(saved)+'</p></section>') if saved else ''
    scenario='''<section class="hero"><p class="muted">Geometry and source assumptions</p><h1>Nominal LBNL cryostat</h1>
<p>A Cs137 source above the curved aluminum cryostat wall. Control offers '''+str(control_count)+''' separate detector configurations: '''+control_choices+'''. The geometry/source pose is nominal, not an as-built survey.</p></section>
<div class="grid"><article class="card" id="ak02"><h2>AK02 case</h2><p>Primary Li-contact detector case; native response uses explicit 77 K override and the canonical model bias.</p><a href="../../detectors/AK02/index.html">AK02 detector page →</a></article>
<article class="card" id="sap22"><h2>SAP22 case</h2><p>Different-geometry non-Li cross-check; it is not a matched control detector.</p><a href="../../detectors/SAP22/index.html">SAP22 detector page →</a></article></div>'''+saved_html+'''
<section class="panel"><h2>Use a supported local case</h2><p>Follow <a href="../../guide.html#setup">Windows setup</a>, then <a href="../../guide.html#local-control">Use Control</a>. Cs137, Am241 and Ba133 accept an exact positive initial-nucleus count through the shared checked workflow, with serial batches of at most 10,000 nuclei. Stop and Resume preserve verified completed boundaries. Use the <a href="../../guide.html#saved-analysis">saved-result guide</a> to inspect batch files and event identities. Co60 remains unavailable under its unchanged source gate. The fixed 662 keV gamma beam supports 20 primaries for AK02/SAP22. A small sample may contain no Ge pulse. Fresh-machine reproduction remains unvalidated.</p><details><summary>Original source and advanced routes</summary><p>The pinned LBNL source files are not redistributed because no explicit license was found in the pinned upstream tree. The <a href="../../guide.html#setup">setup recipe</a> obtains and verifies exact originals under <code>.local/transport/LBNL</code>. See the <a href="https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/transport/cryostat-source.json">upstream manifest</a>.</p><p>Compatible saved-charge replay and earlier native-readout have separate private-input requirements in the <a href="../../guide.html#local-routes">guide</a>.</p></details></section>'''
    caprows=''.join('<tr><td><a href="../../detectors/'+escape(m['id'])+'/index.html">'+escape(m['id'])+'</a></td><td>'+str(len(m.get('contacts',[])))+'</td><td>'+('Implemented' if m['id'] in execution_ids else 'Not integrated')+'</td><td>'+('Available in current cryostat' if m['id'] in control_ids else 'Needs larger cryostat: '+escape(catalog_control[m['id']]['reason']))+'</td></tr>' for m in catalog['detectors'])
    scenario+='<section class="panel"><h2>Execution support</h2><p>Control supports '+str(control_count)+' configurations in the current cryostat; its shared catalog and ring routes are distinct from the legacy <code>Run.cmd</code> adapter. GeRC02 Li50min uses the separate operating variant, while the library retains the original 30-minute model. KM retains its candidate qualification, −370 V bias and fixed −1 electronics wiring.</p><details><summary>All model capabilities and legacy commands</summary><p>The older generic adapter selects AK02, SAP22 or both; both means separate serial cases. See the <a href="../../guide.html#choose">legacy commands</a>. All 17 catalog models can be viewed; '+str(blocked_count)+' require a future larger cryostat because of the recorded dimensions. Complete canonical inputs and original settings are retained. Runtime Check plan independently verifies actual setup, geometry, source and readout before Run.</p><table><thead><tr><th>Model</th><th>Contacts</th><th>Legacy Run.cmd</th><th>Control</th></tr></thead><tbody>'+caprows+'</tbody></table></details></section>'
    write_page(site/'scenarios/lbnl-cs137/index.html','Nominal LBNL cryostat · GeSignal',scenario,2)

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
