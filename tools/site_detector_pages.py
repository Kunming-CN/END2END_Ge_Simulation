"""Generate detector overview/gallery/technical levels from saved website assets."""
import hashlib
import json
import re
from html import escape
from pathlib import Path
from site_fragments import remove_sections, ids

RUN='20260922_suite_v3'
MANAGED={'featured-detector-navigation','ssd-interactive-geometry','saved-gallery-intro'}
SIGNAL_AXIS_NOTE='Horizontal signal axis: physical time (ns). Open the image or Signal CSV for original signed values.'
CAMERA_CLOSE_MODELS={'Bipolar_reference_3D','KL01_3D','ICPC_48A_reference'}
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

def navigation_block(path, *, context=''):
    """A replaceable display fragment, separate from the saved scientific body."""
    from site_routes import page_navigation
    return ('<!-- detector-page-navigation -->'+page_navigation(path)+context+
            '<!-- /detector-page-navigation -->')

def strip_navigation_block(text):
    return re.sub(r'<!-- detector-page-navigation -->.*?<!-- /detector-page-navigation -->',
                  '',text,flags=re.S)

def archive_notebook(html):
    """Correct only the public execution invitation; retain saved outputs/anchors."""
    html=html.replace('Back to GeGI results','Back to GeGI overview')
    html=html.replace('Dimensions and model inputs are listed in <code>README.md</code>.',
        'Dimensions and model inputs belong to the earlier study’s private <code>README.md</code>, which is not included in this archive.')
    html=html.replace('Supplementary saved notebook; not a live simulation. Original code inputs are omitted. Parameters belong to this earlier study.',
        'Archived executed notebook. Recorded outputs and parameters belong to this earlier study; code inputs and private README are omitted. Use the setup guide for supported new calculations.')
    html=re.sub(r'<p>Kernel: <strong>Julia 1\.13 — GeGI</strong>\. Run all cells in order\.</p>',
        '<p>Recorded notebook kernel: <strong>Julia 1.13 — GeGI</strong>. This archive displays saved outputs; it does not execute cells.</p>',html)
    if '<!-- detector-page-navigation -->' in html:
        html=strip_navigation_block(html)
        anchor=re.search(r'<body\b[^>]*>',html)
        if anchor is None:raise ValueError('Unexpected supplementary study body')
        start,end=anchor.end(),anchor.end()
    else:
        banner=re.search(r'<nav\b[^>]*>[^<]*(?:<a\b[^>]*>.*?</a>)?.*?Archived executed notebook\..*?</nav>',html,re.S)
        if banner is None:raise ValueError('Unexpected supplementary study navigation')
        if re.search(r'<(?:img|svg|video|table|script)\b',banner.group(0),re.I):
            raise ValueError('Scientific content appeared in supplementary study navigation')
        start,end=banner.span()
    context=('<p id="supplement-study-context">Archived executed notebook. Recorded outputs and parameters '
             'belong to this earlier study; code inputs and private README are omitted. '
             '<a href="gallery.html">Return to GeGI saved fields &amp; signals</a>. '
             'Use the <a href="../../guide.html">local guide</a> for supported new calculations.</p>')
    return html[:start]+navigation_block('detectors/GeGI_3D/supplement.html',context=context)+html[end:]

def gallery_header(text,model):
    """Replace the old header's navigation while retaining its saved title/settings."""
    text=strip_navigation_block(text)
    header=re.search(r'<header\b[^>]*>(.*?)<h1\b',text,re.S)
    block=navigation_block('detectors/'+model+'/gallery.html')
    if header:
        prefix=header.group(1)
        if re.search(r'<(?:img|svg|video|table|script)\b',prefix,re.I):
            raise ValueError('Scientific content appeared before gallery title')
        return text[:header.start(1)]+block+text[header.end(1):]
    # Structural fixtures have only a main element; public saved galleries have headers.
    main=re.search(r'<main\b[^>]*>',text)
    if main is None:raise ValueError('Unexpected saved gallery header: '+model)
    return text[:main.end()]+block+text[main.end():]

def gallery_navigation(text,model):
    """Retain study settings/plots while retiring competing invitation cards."""
    def adapt(match):
        block=match.group(0)
        heading=re.search(r'<h2>(.*?)</h2>',block,re.S)
        if not heading:return block
        title=heading.group(1)
        if title=='Start here':
            body=block[block.index('</h2>')+5:block.rindex('</section>')]
            return '<details class="panel"><summary>Saved study settings and files</summary>'+body+'</details>'
        if title in ('Cs137: 10,000 initial decays per detector','Radiation-to-readout example','Charge collection diagnostics'):
            # These are generated invitations to other studies, not gallery plots.
            if re.search(r'<(?:img|svg|video|table|script)\b',block,re.I):
                raise ValueError('Scientific content appeared in a gallery invitation')
            return ''.join(f'<span id="{escape(i,quote=True)}"></span>' for i in ids(block))
        return block
    text=re.sub(r'<section\b[^>]*>.*?</section>',adapt,text,flags=re.S)
    anchor='<h2>Saved event examples</h2>'
    if anchor in text and 'id="saved-signal-axis-note"' not in text:
        note='<p id="saved-signal-axis-note">'+SIGNAL_AXIS_NOTE+'</p>'
        if model in CAMERA_CLOSE_MODELS:
            note+='<p>Event camera is a close view; use full geometry for detector boundaries.</p>'
        text=text.replace(anchor,anchor+note,1)
    return text

def strip_navigation(text):
    """Repair the retained GeGI specialist reader without changing its payload."""
    text=strip_navigation_block(text)
    header=re.search(r'<header\b[^>]*>(.*?)<h1\b',text,re.S)
    if header is None:raise ValueError('Unexpected GeGI strip study header')
    if re.search(r'<(?:img|svg|video|table|script)\b',header.group(1),re.I):
        raise ValueError('Scientific content appeared in strip study navigation')
    context='<p id="strip-study-context">Earlier saved 34-channel strip study. <a href="gallery.html">Return to GeGI saved fields &amp; signals</a>.</p>'
    return text[:header.start(1)]+navigation_block('detectors/GeGI_3D/strip_explorer.html',context=context)+text[header.end(1):]

def gegi_channel_captions(text,site):
    """Expose each preview's exact original selected channels beside its PNG."""
    from saved_plot_repairs import channel_data, selected_channels
    def caption(match):
        block=match.group(0)
        preview=re.search(r'src="runs/'+RUN+r'/events/([A-Za-z0-9_-]+)/preview\.png"',block)
        if not preview:return block
        event=preview.group(1)
        _,channels=channel_data(site,event)
        names=selected_channels(channels)
        block=re.sub(r'<p class="saved-channel-caption">.*?</p>','',block,flags=re.S)
        note='<p class="saved-channel-caption">Saved preview channels: '+escape(', '.join(names) if names else 'none selected')+f'. Original signed values and times are in <a href="runs/{RUN}/events/{event}/channels.csv">channels.csv</a>.</p>'
        return block.replace('</article>',note+'</article>',1)
    return re.sub(r'<article class="card">.*?</article>',caption,text,flags=re.S)

def apply(site, write_page):
    site=Path(site)
    catalog=json.loads((site/'models/catalog.json').read_text(encoding='utf-8'))
    capabilities=execution_capabilities()
    control_ids=control_capabilities(capabilities)
    catalog_control=catalog_control_capabilities(capabilities)
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
        cleaned=gallery_navigation(remove_sections(original,MANAGED),model)
        if model=='GeGI_3D':cleaned=gegi_channel_captions(cleaned,site)
        cleaned=gallery_header(cleaned,model)
        banner=(f'<section id="saved-gallery-intro"><h2>{escape(model)} earlier saved gallery</h2>'
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
        supported=model in control_ids
        run_note=(f'<p>Control supports {escape(model)} in the nominal LBNL modular cryostat. '
                  'Use the <a href="../../guide.html#local-control">Control instructions</a> '
                  'after <a href="../../guide.html#setup">setup</a>. '
                  'Fresh-machine reproduction remains unvalidated.</p>' if supported else
                  '<p>This model is available for browsing and needs a future larger cryostat.</p><p>'+escape(catalog_control[model]['reason'])+'</p>')
        special=('<p><a href="strip_explorer.html">Saved 34-channel strip study</a> · '
                 '<a href="supplement.html">Earlier supplementary study</a></p>' if model=='GeGI_3D' else '')
        legacy_ids=set(ids(strip_navigation_block(cleaned)))-MANAGED-{'contact-legend','native-cs137-10k','saved-signal-axis-note'}
        aliases=('<details class="panel"><summary>Earlier saved gallery sections</summary>'+''.join(
            f'<p id="{escape(i,quote=True)}"><a href="gallery.html#{escape(i,quote=True)}">Open saved gallery detail</a></p>'
            for i in sorted(legacy_ids))+'</details>' if legacy_ids else '')
        past=('<p id="native-cs137-10k"><a href="../../results/cs137-1m/index.html">Separate Cs137 1M campaign · '+escape(model)+'</a></p>' if model in campaign_models else '')
        variant_note=('<p>Catalog model: original 30-minute GeRC02. Cs137 10K uses a separate Li50min operating variant.</p>' if model=='GeRC02' else '')
        header=(f'<section class="hero"><h1>{escape(model)}</h1><p>{escape(TYPE_LABELS[model])}</p>'
                '<p>Recorded model status: '+escape(item.get('status','Saved model'))+'</p>'+variant_note+'</section>')
        image=(f'<figure class="panel"><a href="runs/{RUN}/01_geometry.png">'
               f'<img loading="lazy" style="width:100%;height:300px;object-fit:contain" src="runs/{RUN}/01_geometry.png" '
               f'alt="{escape(model)} {escape(TYPE_LABELS[model])}, saved geometry"></a>'
               '<figcaption>Saved geometry · <a href="runs/'+RUN+'/01_geometry.png">Open full-size image</a>. '
               'Colors identify contact IDs; they do not show doping or Li thickness.</figcaption></figure>')
        nav=('<section id="featured-detector-navigation" class="panel"><h2>View this detector</h2><div class="grid">'
             '<article id="ssd-interactive-geometry"><h3><a href="geometry.html">Geometry</a></h3><p>Rotate the saved physical meshes and inspect contact IDs.</p></article>'
             '<article id="contact-legend"><h3><a href="technical.html">Model &amp; files</a></h3><p>Original settings, contacts, signed bias and model downloads.</p></article></div></section>')
        studies=('<section id="saved-studies" class="panel"><h2>Saved studies</h2>'
                 '<p><a href="gallery.html">Saved fields &amp; signals</a> · earlier synthetic SSD study: field plots, movies and event signals.</p>'
                 +special+past+'</section>')
        overview=(header+image+nav+'<section class="panel"><h2>Local calculation support</h2>'+run_note+'</section>'+studies+aliases)
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
        technical=(header+facts+'<section class="panel"><h2>Original model and provenance</h2><p>'+downloads+
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
    strips=site/'detectors/GeGI_3D/strip_explorer.html'
    if strips.is_file():strips.write_text(strip_navigation(strips.read_text(encoding='utf-8')),encoding='utf-8',newline='\n')
    return delivered

def control_capabilities(capabilities=None):
    """Read reviewed Control adapters separately from the legacy CLI flags."""
    capabilities=execution_capabilities() if capabilities is None else capabilities
    root=Path(__file__).resolve().parents[1]
    adapters=json.loads((root/'scenarios/detector-capabilities.json').read_text())['control_adapters']
    for model,row in adapters.items():
        if model not in capabilities or row['adapter'] not in {'fresh_ring_control_v1','sap18_control_v1'} or row['sources']!=['cs137_point_decay_v1'] or row['counts']!=[20,500]:
            raise ValueError('Unreviewed Control capability')
    catalog=catalog_control_capabilities(capabilities,root)
    return {model for model,row in capabilities.items() if row['lbnl_execution_implemented']}|set(adapters)|{model for model,row in catalog.items() if row['available']}


def catalog_control_capabilities(capabilities,root=None):
    """Validate the reviewed display snapshot; backend admission is independent."""
    root=Path(root or Path(__file__).resolve().parents[1])
    data=json.loads((root/'scenarios/catalog-presentation.json').read_text(encoding='utf-8'))
    expected={'models/catalog.json','transport/cryostat_nominal.json','scenarios/detector-capabilities.json'}
    if (data.get('kind')!='catalog_presentation_v1' or data.get('schema_version')!=1 or
            data.get('scope')!='presentation_only' or set(data.get('authority_sha256',{}))!=expected):
        raise ValueError('Unreviewed catalog presentation authority')
    for ref,digest in data['authority_sha256'].items():
        if hashlib.sha256((root/ref).read_bytes()).hexdigest()!=digest:
            raise ValueError('Catalog presentation authority bytes changed: '+ref)
    registry=json.loads((root/'scenarios/detector-capabilities.json').read_text(encoding='utf-8'))
    if data.get('catalog_adapter')!=registry.get('catalog_adapter'):
        raise ValueError('Catalog presentation source/model policy changed')
    rows=data.get('models',[])
    if len(rows)!=len(capabilities) or {r.get('model_id') for r in rows}!=set(capabilities):
        raise ValueError('Catalog presentation model inventory changed')
    for row in rows:
        if (row.get('model_sha256')!=capabilities[row['model_id']]['model_sha256'] or
                type(row.get('available')) is not bool or
                (row['available'] and (row.get('block_code') is not None or row.get('reason') is not None)) or
                (not row['available'] and (row.get('block_code')!='cryostat_size' or not isinstance(row.get('reason'),str) or not row['reason']))):
            raise ValueError('Unreviewed catalog presentation model binding or size reason')
    return {row['model_id']:row for row in rows}

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
