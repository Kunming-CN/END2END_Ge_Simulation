"""Generate detector overview/gallery/technical levels from saved website assets."""
import json
from html import escape
from pathlib import Path
from site_fragments import remove_sections, ids

RUN='20260922_suite_v3'
MANAGED={'featured-detector-navigation','ssd-interactive-geometry','saved-gallery-intro'}

def apply(site, write_page):
    site=Path(site)
    catalog=json.loads((site/'models/catalog.json').read_text(encoding='utf-8'))
    capabilities=execution_capabilities()
    report=site/"examples/cs137-1m-response/summary.json"
    campaign_models=set(json.loads(report.read_text())["models"]) if report.is_file() else set()
    delivered=[]
    for item in catalog['detectors']:
        model=item['id']
        folder=site/'detectors'/model
        poster=folder/'runs'/RUN/'01_geometry.png'
        if not poster.is_file():
            continue  # Tiny structural unit-test fixtures have no saved gallery.
        page=folder/'index.html'
        gallery=folder/'gallery.html'
        original=(gallery if gallery.is_file() else page).read_text(encoding='utf-8')
        cleaned=remove_sections(original,MANAGED)
        cleaned=cleaned.replace('href="../../index.html">Detector library','href="../index.html">Detector library')
        banner=(f'<section id="saved-gallery-intro"><h2>{escape(model)} saved gallery</h2>'
                '<p><a href="index.html">Detector overview</a> · '
                '<a href="geometry.html">Rotate geometry</a> · '
                '<a href="technical.html">Technical details</a></p>'
                '<p>Saved SSD gallery and synthetic event examples; not a newly run '
                'LBNL source simulation. Original settings and limitations remain below.</p></section>')
        if cleaned.count('<main>')!=1:
            raise ValueError('Unexpected saved gallery structure: '+model)
        gallery.write_text(cleaned.replace('<main>','<main>'+banner,1),encoding='utf-8',newline='\n')
        count=len(item['contacts'])
        contact_rows=''.join('<tr><td>'+str(c['id'])+'</td><td>'+escape(c['name'])+
            '</td><td>'+str(c['potential_V'])+'</td></tr>' for c in item['contacts'])
        contact_table=('<table><thead><tr><th>ID</th><th>Canonical contact name</th>'
                       '<th>Potential (V)</th></tr></thead><tbody>'+contact_rows+'</tbody></table>')
        downloads=(f'<a href="../../models/{model}.yaml">Original YAML</a> · '
                   f'<a href="../../downloads/{model}.zip">Model ZIP with includes</a>')
        geometry=(f'<section id="ssd-interactive-geometry" class="panel"><h2>Rotate the detector</h2>'
                  '<p><a href="geometry.html">Open full interactive geometry</a>. '
                  'Saved physical meshes; no fields or carrier trajectories are solved here.</p>'
                  f'<iframe title="{escape(model)} interactive detector geometry" src="geometry.html" '
                  'style="width:100%;height:720px;border:0" loading="lazy"></iframe></section>')
        if not (folder/'geometry.html').is_file():
            geometry=f'<section class="panel"><h2>Saved geometry</h2><img style="max-width:100%" src="runs/{RUN}/01_geometry.png" alt="{escape(model)} saved geometry"></section>'
        supported=capabilities[model]['lbnl_execution_implemented']
        run_note=(f'<p>Use the <a href="../../scenarios/lbnl-cs137/index.html">LBNL Cs137 scenario</a>: '
                  f'<code>.\\Run.cmd run -Detector {model} -Preset demo</code>.</p>' if supported else
                  '<p>LBNL end-to-end execution is not yet integrated for this model. '
                  'Geometry viewing is available independently of cryostat placement and readout support.</p>')
        special=('<p><a href="strip_explorer.html">Explore all 34 GeGI signal channels</a> · '
                 '<a href="supplement.html">Earlier supplementary study</a></p>' if model=='GeGI_3D' else '')
        legacy_ids=set(ids(cleaned))-MANAGED-{'contact-legend','native-cs137-10k'}
        aliases=''.join(f'<p id="{escape(i,quote=True)}"><a href="gallery.html#{escape(i,quote=True)}">Open saved gallery detail</a></p>' for i in sorted(legacy_ids))
        past=('<section id="native-cs137-10k" class="panel"><h2>Results using this detector</h2>'
              '<p><a href="../../results/cs137-1m/index.html">1M campaign overview</a> · '
              '<a href="../../results/cs137-10k/index.html">Earlier 10k campaign</a> · '
              f'<a href="../../examples/cs137-10k-hits/hit_event_view.html?model={model}">Explore earlier 10k Ge-positive events</a></p></section>' if model in campaign_models else '')
        header=(f'<section class="hero"><p><a href="../index.html">All detectors</a> / <a href="index.html">{escape(model)}</a></p>'
                f'<h1>{escape(model)}</h1><p>{count} contacts · {escape(item.get("coordinate_system",""))} · '
                f'{escape(item.get("status","Saved model"))}</p></section>')
        nav=('<section id="featured-detector-navigation" class="panel"><h2>Explore this detector</h2>'
             '<p><a href="geometry.html">Rotate geometry</a> · <a href="gallery.html">Fields, movies and signals</a> · '
             '<a href="technical.html">Model and technical details</a></p></section>')
        overview=(header+nav+geometry+'<section class="panel"><h2>Saved response gallery</h2>'
                  f'<a href="gallery.html"><img loading="lazy" style="max-width:100%;max-height:280px" src="runs/{RUN}/02_static_fields.png" alt="{escape(model)} saved field and weighting-potential preview"></a>'
                  '<p>Field lines are not carrier trajectories. Gallery settings and scenario overrides are separate.</p>'+special+'</section>'+past+
                  '<section id="contact-legend" class="panel"><h2>Contact key and model files</h2>'
                  '<p>Colors identify contacts, not doping or layer thickness. Small contacts retain their actual size. '
                  '<a href="runs/'+RUN+'/01_geometry.png">Full-size saved geometry</a></p>'+
                  '<details><summary>Contact IDs and signed potentials</summary>'+contact_table+'</details><p>'+downloads+'</p></section>'+
                  '<section class="panel"><h2>Run locally</h2>'+run_note+'<p><a href="../../guide.html">Setup and validation limits</a></p></section>'+aliases)
        write_page(page,model+' · Detector overview',overview,2)
        diagnostics=[]
        for name in ('validation.events.json','validation.scenes.json'):
            if (folder/'runs'/RUN/name).is_file():
                diagnostics.append(f'<a href="runs/{RUN}/{name}">{name}</a>')
        b=item.get('bounds_mm',[])
        ranges='; '.join(f'{axis}: [{b[2*i]:g}, {b[2*i+1]:g}] mm' for i,axis in enumerate('xyz')) if len(b)==6 else 'Not recorded'
        assumptions='<ul>'+''.join('<li>'+escape(a)+'</li>' for a in item.get('assumptions',[]))+'</ul>'
        facts=('<section class="panel"><h2>Model at a glance</h2><p><strong>Coordinate bounds:</strong> '+ranges+'</p>'
               '<p>These are coordinate bounds, not active-volume or dead-layer measurements.</p>'
               '<p><strong>Reference readout contact:</strong> '+str(item['readout_contact_id'])+'</p>'
               '<p><strong>Recorded model assumptions:</strong></p>'+assumptions+'</section>')
        sibling_nav=('<nav aria-label="Detector pages"><a href="index.html">Overview</a> · '
                     '<a href="geometry.html">Geometry</a> · <a href="gallery.html">Saved gallery</a> · '
                     '<a href="../index.html">Detector library</a></nav>')
        technical=(header+sibling_nav+facts+'<section class="panel"><h2>Original model and provenance</h2><p>'+downloads+
                   '</p><p><a href="../../models/catalog.json">Canonical model catalog and hashes</a> · '
                   '<a href="../../models/README.md">Model distribution guide</a></p>'
                   '<p>Original model settings are preserved. The LBNL AK02/SAP22 campaign uses '
                   'an explicit 77 K override; it does not replace the saved gallery configuration.</p></section>'
                   '<section class="panel"><h2>Contact metadata</h2>'+contact_table+'</section>'
                   '<section class="panel"><h2>Saved numerical diagnostics</h2><p>'+' · '.join(diagnostics)+
                   '</p><p><a href="gallery.html">Full saved gallery</a> · <a href="../../methods/index.html">Methods and limitations</a></p>'
                   '<p>Numerical/functional checks are not experimental calibration. Unknown responses '
                   'and incomplete collection must remain distinct from zero deposition.</p></section>'+run_note)
        write_page(folder/'technical.html',model+' · Technical details',technical,2)
        delivered.append(model)
    return delivered

def execution_capabilities():
    """Presentation authority only; this never enables a backend model."""
    root=Path(__file__).resolve().parents[1]
    data=json.loads((root/'scenarios/detector-capabilities.json').read_text())
    scenario=json.loads((root/'scenarios/lbnl-cs137.json').read_text())
    catalog=json.loads((root/'models/catalog.json').read_text())
    canonical={m['id']:m for m in catalog['detectors']}
    rows=data['detectors']
    if data['schema_version']!=1 or data['scenario_id']!=scenario['id']:
        raise ValueError('Capability scenario mismatch')
    if len(rows)!=len(canonical) or {r['model_id'] for r in rows}!=set(canonical):
        raise ValueError('Capability catalog mismatch')
    for row in rows:
        item=canonical[row['model_id']]
        if type(row['lbnl_execution_implemented']) is not bool:
            raise ValueError('Capability flags must be Boolean')
        if row['model_sha256']!=item['model_sha256'] or row['contact_count']!=len(item['contacts']):
            raise ValueError('Capability model binding changed')
    enabled={r['model_id'] for r in rows if r['lbnl_execution_implemented']}
    if enabled!=set(scenario['detectors']):
        raise ValueError('Capability labels differ from reviewed scenario')
    return {r['model_id']:r for r in rows}
