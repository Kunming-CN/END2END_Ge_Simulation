"""Generate detector overview/gallery/technical levels from saved website assets."""
import json
import re
from html import escape
from pathlib import Path
from site_fragments import remove_sections, ids

RUN='20260922_suite_v3'
MANAGED={'featured-detector-navigation','ssd-interactive-geometry','saved-gallery-intro'}
TYPE_LABELS={
    'AK01':'Inverted coaxial point-contact (ICPC)',
    'AK02':'Inverted coaxial point-contact (ICPC)',
    'BEGe_GD32B_reference':'Broad energy germanium (BEGe)',
    'BEGe_reference':'Broad energy germanium (BEGe)',
    'Bipolar_reference_3D':'Planar detector',
    'COAX_ANG2_reference':'Coaxial detector',
    'GeGI_3D':'Double-sided strip detector',
    'GeRC02':'Ring-contact detector',
    'ICPC_48A_reference':'Inverted coaxial point-contact (ICPC)',
    'ICPC_large_reference':'Inverted coaxial point-contact (ICPC)',
    'KL01_3D':'Planar detector',
    'KMRC01_candidate':'Ring-contact detector',
    'PPC_PONaMa1_reference':'Point-contact detector (PPC)',
    'SAP16':'Inverted coaxial point-contact (ICPC)',
    'SAP17':'Inverted coaxial point-contact (ICPC)',
    'SAP18_ring08_scenario':'Ring-contact detector',
    'SAP22':'Inverted coaxial point-contact (ICPC)',
}

def archive_notebook(html):
    """Correct only the public execution invitation; retain saved outputs/anchors."""
    html=html.replace('Back to GeGI results','Back to GeGI overview')
    html=html.replace('Dimensions and model inputs are listed in <code>README.md</code>.',
        'Dimensions and model inputs belong to the earlier study’s private <code>README.md</code>, which is not included in this archive.')
    html=html.replace('Supplementary saved notebook; not a live simulation. Original code inputs are omitted. Parameters belong to this earlier study.',
        'Archived executed notebook. Recorded outputs and parameters belong to this earlier study; code inputs and private README are omitted. Use the setup guide for supported new calculations.')
    return re.sub(r'<p>Kernel: <strong>Julia 1\.13 — GeGI</strong>\. Run all cells in order\.</p>',
        '<p>Recorded notebook kernel: <strong>Julia 1.13 — GeGI</strong>. This archive displays saved outputs; it does not execute cells.</p>',html)

def apply(site, write_page):
    site=Path(site)
    catalog=json.loads((site/'models/catalog.json').read_text(encoding='utf-8'))
    capabilities=execution_capabilities()
    control_ids=control_capabilities(capabilities)
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
        banner=(f'<section id="saved-gallery-intro"><h2>{escape(model)} earlier saved gallery</h2>'
                '<p><a href="index.html">Detector overview</a> · '
                '<a href="geometry.html">Rotate geometry</a> · '
                '<a href="technical.html">Technical details</a></p>'
                '<p>Original synthetic SSD study from <code>20260922_suite_v3</code>. '
                'For source-campaign results, return to the detector overview. '
                'Original settings and limitations remain below.</p></section>')
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
        supported=model in control_ids
        run_note=(f'<p>Control supports {escape(model)} in the nominal LBNL modular cryostat. '
                  'Use the <a href="../../guide.html#local-control">Control instructions</a> '
                  'after <a href="../../guide.html#setup">setup</a>. '
                  'Fresh-machine reproduction remains unvalidated.</p>' if supported else
                  '<p>This model is available for browsing. New end-to-end execution in Control is not integrated for it.</p>')
        special=('<p><a href="strip_explorer.html">Explore all 34 GeGI signal channels</a> · '
                 '<a href="supplement.html">Earlier supplementary study</a></p>' if model=='GeGI_3D' else '')
        legacy_ids=set(ids(cleaned))-MANAGED-{'contact-legend','native-cs137-10k'}
        aliases=''.join(f'<p id="{escape(i,quote=True)}"><a href="gallery.html#{escape(i,quote=True)}">Open saved gallery detail</a></p>' for i in sorted(legacy_ids))
        past=('<section id="native-cs137-10k" class="panel"><h2>Source-campaign results</h2>'
              '<p><a href="../../results/cs137-10k/index.html">Cs137 10K results</a> · '
              '<a href="../../results/cs137-1m/index.html">Separate 1M campaign overview</a></p>'
              f'<p><a href="../../examples/cs137-10k-hits/hit_event_view.html?model={model}">Explore 10K Ge-positive events</a></p></section>' if model in campaign_models else '')
        header=(f'<section class="hero"><p><a href="../index.html">All detectors</a> / <a href="index.html">{escape(model)}</a></p>'
                f'<h1>{escape(model)}</h1><p>{escape(TYPE_LABELS[model])}</p></section>')
        image=(f'<figure class="panel"><a href="runs/{RUN}/01_geometry.png">'
               f'<img loading="lazy" style="width:100%;height:300px;object-fit:contain" src="runs/{RUN}/01_geometry.png" '
               f'alt="{escape(model)} {escape(TYPE_LABELS[model])}, saved geometry"></a>'
               '<figcaption>Saved geometry · <a href="runs/'+RUN+'/01_geometry.png">Open full-size image</a>. '
               'Colors identify contact IDs; they do not show doping or Li thickness.</figcaption></figure>')
        nav=('<section id="featured-detector-navigation" class="panel"><h2>Explore this detector</h2>'
             '<p><a href="geometry.html">Rotate geometry</a> · <a href="gallery.html">Fields, movies and signals</a> · '
             '<a href="technical.html">Model and technical details</a></p></section>')
        overview=(header+image+nav+past+geometry+'<section class="panel"><h2>Earlier synthetic response gallery</h2>'
                  f'<a href="gallery.html"><img loading="lazy" style="max-width:100%;max-height:280px" src="runs/{RUN}/02_static_fields.png" alt="{escape(model)} saved field and weighting-potential preview"></a>'
                  '<p>Saved synthetic study, separate from source-campaign results. Field lines are not carrier trajectories. Gallery settings and scenario overrides are separate.</p>'+special+'</section>'+
                  '<section id="contact-legend" class="panel"><h2>Contact key and model files</h2>'
                  '<p>Colors identify contacts, not doping or layer thickness. Small contacts retain their actual size. '
                  '<a href="runs/'+RUN+'/01_geometry.png">Full-size saved geometry</a></p>'+
                  '<details><summary>Contact IDs and signed potentials</summary>'+contact_table+'</details><p>'+downloads+'</p></section>'+
                  '<section class="panel"><h2>Run locally</h2>'+run_note+'<p><a href="../../guide.html#validation">Validation limits</a></p></section>'+aliases)
        write_page(page,model+' · Detector overview',overview,2)
        diagnostics=[]
        for name in ('validation.events.json','validation.scenes.json'):
            if (folder/'runs'/RUN/name).is_file():
                diagnostics.append(f'<a href="runs/{RUN}/{name}">{name}</a>')
        b=item.get('bounds_mm',[])
        ranges='; '.join(f'{axis}: [{b[2*i]:g}, {b[2*i+1]:g}] mm' for i,axis in enumerate('xyz')) if len(b)==6 else 'Not recorded'
        assumptions='<ul>'+''.join('<li>'+escape(a)+'</li>' for a in item.get('assumptions',[]))+'</ul>'
        facts=('<section class="panel"><h2>Model at a glance</h2><p><strong>Coordinate bounds:</strong> '+ranges+'</p>'
               '<p><strong>Recorded model status:</strong> '+escape(item.get('status','Saved model'))+'</p>'
               '<p><strong>Contacts and coordinates:</strong> '+str(count)+' contacts · '+escape(item.get('coordinate_system',''))+'</p>'
               '<p>These are coordinate bounds, not active-volume or dead-layer measurements.</p>'
               '<p><strong>Reference readout contact:</strong> '+str(item['readout_contact_id'])+'</p>'
               '<p><strong>Recorded model assumptions:</strong></p>'+assumptions+'</section>')
        sibling_nav=('<nav aria-label="Detector pages"><a href="index.html">Overview</a> · '
                     '<a href="geometry.html">Geometry</a> · <a href="gallery.html">Saved gallery</a> · '
                     '<a href="../index.html">Detector library</a></nav>')
        technical=(header+sibling_nav+facts+'<section class="panel"><h2>Original model and provenance</h2><p>'+downloads+
                   '</p><p><a href="../../models/catalog.json">Canonical model catalog and hashes</a> · '
                   '<a href="../../models/README.md">Model distribution guide</a></p>'
                   '<ul>'+''.join('<li>'+escape(source)+'</li>' for source in item.get('sources',[]))+'</ul>'
                   '<p>Original model settings are preserved. The LBNL AK02/SAP22 campaign uses '
                   'an explicit 77 K override; it does not replace the saved gallery configuration.</p></section>'
                   '<section class="panel"><h2>Contact metadata</h2>'+contact_table+'</section>'
                   '<section class="panel"><h2>Saved numerical diagnostics</h2><p>'+' · '.join(diagnostics)+
                   '</p><p><a href="gallery.html">Full saved gallery</a> · <a href="../../methods/index.html">Methods and limitations</a></p>'
                   '<p>Numerical/functional checks are not experimental calibration. Unknown responses '
                   'and incomplete collection must remain distinct from zero deposition.</p></section>'+run_note)
        write_page(folder/'technical.html',model+' · Technical details',technical,2)
        delivered.append(model)
    notebook=site/'detectors/GeGI_3D/supplement.html'
    if notebook.is_file():notebook.write_text(archive_notebook(notebook.read_text(encoding='utf-8')),encoding='utf-8',newline='\n')
    return delivered

def control_capabilities(capabilities=None):
    """Read reviewed Control adapters separately from the legacy CLI flags."""
    capabilities=execution_capabilities() if capabilities is None else capabilities
    root=Path(__file__).resolve().parents[1]
    adapters=json.loads((root/'scenarios/detector-capabilities.json').read_text())['control_adapters']
    for model,row in adapters.items():
        if model not in capabilities or row['adapter']!='fresh_ring_control_v1' or row['sources']!=['cs137_point_decay_v1'] or row['counts']!=[20,500]:
            raise ValueError('Unreviewed Control capability')
    return {model for model,row in capabilities.items() if row['lbnl_execution_implemented']}|set(adapters)

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
