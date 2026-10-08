"""Presentation-only teaching derivative from the already completed saved data."""
import argparse
import copy
import json
from pathlib import Path
import shutil

import gamma_showcase as S
import pipeline_demo as P

ROOT=P.ROOT
BASE='.local/product-delivery-v1/teaching-display'
TEMPLATE='tools/pipeline_focus.html'
JS='tools/focused_plots.js'
FILES=('data.json','pipeline.html','pipeline-display.json')

# Exact accepted receipts, not self-declared hashes, authorize the old displays.
# New presentation derivatives reconstruct these receipts and preserve every
# numerical download. Their original exporter/source pins remain historical.
DISPLAY_BASES={
    'gamma':{'receipt':'1efdd33521d27d8b9a413a1df64592018349af2e81d1b0d69cc612d72c76c166',
             'html':'gamma.html','stamp':{'bytes':5464306,'sha256':'1858fd960a395615736c3a91d2806c4f32778ba58950f68c46dadaa660b2b5c9'}},
    'teaching':{'receipt':'3a0a5fdbfde1e00c20c810e197f7e27bbdad854e241759bd8bf42ec438079ae3',
                'html':'pipeline.html','stamp':{'bytes':9805279,'sha256':'6b97584824ef8237fccc44c24255eec44b8233242a3264fffd46f36cd5a7277f'}}}
DISPLAY_SOURCES=(JS,'tools/saved_focus_pages.py','tools/site_restructure.py','tools/site_routes.py',
                 'tools/gamma_complete_showcase.py','tools/gamma_complete_showcase.html',
                 TEMPLATE,'tools/pipeline_demo.py')

# Accepted b2e9d76 and 8ef88bd display receipts. Only these exact prior derivatives may be
# read during the next presentation upgrade; science still reconstructs the
# immutable original receipt above. Rehashed edits are never a historical basis.
PREVIOUS_DISPLAY_RECEIPTS={
    'gamma':frozenset({'725c852d635021b0aef16f9b651c56ebdd16fb9f7e13a7737101ea78fa4b11e7',
                       'b7b90f6e14bd88b903e0e7bb761384c51c2b0e2b863dbe7e29d2ed29b14d0eba',
                       # Authenticated first local build 76a8596f; never published.
                       '0f660aeeaa0954a4c12ea5193d8cbe8bf6fc17e5e050cfc791bcaf7e646c49a4'}),
    'teaching':frozenset({'a96863b38712c40efd87372accd0276bdbdeada68370c5e6b46a983abf526800'})}
PRESERVED_TEACHING_HTML={'bytes':9810837,'sha256':'71d898465740d2ad4eb098cc5cc1d27c494f38c0151e634dfc067bf53f147bf7'}

def display_sources():
    return {n:S.sha((ROOT/n).read_bytes()) for n in DISPLAY_SOURCES}

def historical_display(family,raw):
    return S.sha(raw)==DISPLAY_BASES[family]['receipt']

def validate_display_binding(family,manifest):
    extension=manifest['display_upgrade'];base=DISPLAY_BASES[family]
    current=family!='teaching' and extension==dict(kind='saved_plot_display_v1',science_calls=0,
        original_receipt_sha256=base['receipt'],sources=display_sources())
    previous=S.sha(S.canonical(manifest)) in PREVIOUS_DISPLAY_RECEIPTS[family]
    S.require(current or previous,'Unknown saved display upgrade binding')
    original=copy.deepcopy(manifest);original.pop('display_upgrade')
    original['files'][base['html']]=base['stamp']
    S.require(historical_display(family,S.canonical(original)),'Original scientific/export receipt changed')
    return current

def display_render(family,data):
    from site_routes import page_navigation
    if family=='gamma':
        from gamma_complete_showcase import render as original_render
        body=original_render(data).decode('utf-8')
        call='SavedFocusPlots.gammaPanels(r,m.display_edges[String(activeId)])'
        S.require(body.count(call)==1,'Gamma saved settings anchor')
        body=body.replace(call,'SavedFocusPlots.gammaPanels(r,m.display_edges[String(activeId)],{ionisation_energy_eV:m.report.ionisation_energy_eV,time_step_ns:m.report.calibration.time_step_ns})',1)
        old='<a href="../../results/index.html">← Saved results</a>'
        S.require(body.count(old)==1,'Gamma saved return anchor')
        body=body.replace(old,'',1)
        context='<p style="margin:12px 24px">Additional cryostat example: 20 gamma primaries per detector. Different geometry and event IDs from the 100-primary teaching example.</p>'
    else:
        raise ValueError('Original teaching reader is frozen; upgrade its spectrum derivative')
    anchor='<header>'
    S.require(body.count(anchor)==1,'Saved reader header anchor')
    bar='<div style="padding:12px 24px;background:#fff;color:#173047">'+page_navigation('examples/gamma-native/gamma.html')+'</div>'+context
    return body.replace(anchor,bar+anchor,1).encode('utf-8')

def upgrade_displays(site):
    """Update gamma navigation; preserve the exact teaching source for its derivative."""
    from gamma_publication import validate_bundle as validate_gamma
    site=Path(site);expected=display_sources()
    for family,directory,receipt in (
            ('gamma',site/'examples/gamma-native','publication.json'),
            ('teaching',site/'examples','pipeline-display.json')):
        path=directory/receipt
        if not path.exists():continue
        # The earlier six-response format remains an unchanged saved archive.
        if family=='gamma' and S.decode(path.read_bytes()).get('kind')!='saved_gamma_complete_publication_v1':continue
        data=validate_gamma(directory) if family=='gamma' else validate(directory)
        if family=='teaching':
            # The maintained spectrum reader owns teaching navigation. Its saved
            # source stays exactly at the accepted 8ef88bd display and receipt.
            raw=(directory/'pipeline.html').read_bytes()
            S.require({'bytes':len(raw),'sha256':S.sha(raw)}==PRESERVED_TEACHING_HTML,
                      'Original teaching reader differs from accepted display')
            S.require(S.sha(path.read_bytes()) in PREVIOUS_DISPLAY_RECEIPTS['teaching'],
                      'Unknown preserved teaching display receipt')
            continue
        raw=path.read_bytes();manifest=S.decode(raw)
        if 'display_upgrade' not in manifest:
            S.require(historical_display(family,raw),'Unknown initial saved display receipt')
        html=display_render(family,data);name=DISPLAY_BASES[family]['html']
        manifest['files'][name]={'bytes':len(html),'sha256':S.sha(html)}
        manifest['display_upgrade']=dict(kind='saved_plot_display_v1',science_calls=0,
            original_receipt_sha256=DISPLAY_BASES[family]['receipt'],sources=expected)
        validate_display_binding(family,manifest)
        S.require(display_sources()==expected,'Display writers must exit before export')
        (directory/name).write_bytes(html);path.write_bytes(S.canonical(manifest))
        if family=='gamma':validate_gamma(directory)
        else:validate(directory)

def render(data):
    template=(ROOT/TEMPLATE).read_text(encoding='utf-8')
    S.require(template.count('__FOCUSED_PLOTS_JS__')==1,'Teaching JS placeholder')
    template=template.replace('__FOCUSED_PLOTS_JS__',(ROOT/JS).read_text(encoding='utf-8'))
    return P.render_html(data,template).encode('utf-8')

def export():
    frozen=S.decode((ROOT/'.local/product-delivery-v1/implementation/m14b/SOURCE-FREEZE.json').read_bytes())
    names=(TEMPLATE,JS,'tools/saved_focus_pages.py','tools/pipeline_demo.py','tools/pipeline_explorer.html')
    S.require(frozen['status']=='frozen_after_writer_exit','Freeze required')
    for n in names:S.require(S.sha((ROOT/n).read_bytes())==frozen['files'][n]['sha256'],'Changed frozen teaching source')
    original=ROOT/'.local/pipeline-showcase';data=P.validate_export(original)
    raw=(original/'data.json').read_bytes();html=render(data);target=S.no_links(ROOT/BASE)
    S.require(not target.exists(),'Preserve existing derivative evidence');target.mkdir(parents=True)
    (target/'data.json').write_bytes(raw);(target/'pipeline.html').write_bytes(html)
    manifest=dict(kind='saved_teaching_focus_v1',status='completed',science_calls=0,
        original_data_sha256=S.sha(raw),original_html_sha256=S.sha((original/'pipeline.html').read_bytes()),
        template_sha256=S.sha((ROOT/TEMPLATE).read_bytes()),javascript_sha256=S.sha((ROOT/JS).read_bytes()),
        exporter_sha256=S.sha((ROOT/'tools/saved_focus_pages.py').read_bytes()),
        files={'data.json':{'sha256':S.sha(raw),'bytes':len(raw)},'pipeline.html':{'sha256':S.sha(html),'bytes':len(html)}})
    (target/'pipeline-display.json').write_bytes(S.canonical(manifest));validate(target)
    return {'status':'completed_saved_teaching_display','science_calls':0}

def validate(directory):
    directory=S.no_links(directory);manifest=S.decode((directory/'pipeline-display.json').read_bytes())
    S.require(manifest['kind']=='saved_teaching_focus_v1' and manifest['status']=='completed' and manifest['science_calls']==0,'Completed saved teaching derivative')
    for n,stamp in manifest['files'].items():
        raw=(directory/n).read_bytes();S.require(S.sha(raw)==stamp['sha256'] and len(raw)==stamp['bytes'],'Changed teaching artifact')
    raw=(directory/'data.json').read_bytes();S.require(S.sha(raw)==manifest['original_data_sha256'],'Original teaching numerical bytes')
    data=S.decode(raw)
    if 'display_upgrade' in manifest:
        S.require(S.sha((directory/'pipeline-display.json').read_bytes()) in PREVIOUS_DISPLAY_RECEIPTS['teaching'],
                  'Unknown preserved teaching display receipt')
        validate_display_binding('teaching',manifest)
        S.require(manifest['files']['pipeline.html']==PRESERVED_TEACHING_HTML,
                  'Original teaching reader differs from accepted display')
    elif not historical_display('teaching',(directory/'pipeline-display.json').read_bytes()):
        S.require((directory/'pipeline.html').read_bytes()==render(data),'Exact focused teaching template/data')
        S.require(manifest['template_sha256']==S.sha((ROOT/TEMPLATE).read_bytes()) and manifest['javascript_sha256']==S.sha((ROOT/JS).read_bytes()),'Frozen presentation sources')
    return data

def assemble(target):
    source=ROOT/BASE
    if not source.exists():return False
    validate(source);target=Path(target)
    S.require((target/'data.json').read_bytes()==(source/'data.json').read_bytes(),'Staged teaching numerical data differs')
    if (target/'pipeline-display.json').is_file():
        receipt=(target/'pipeline-display.json').read_bytes()
        if S.sha(receipt) in PREVIOUS_DISPLAY_RECEIPTS['teaching']:
            validate(target);return True
    for n in FILES:shutil.copyfile(source/n,target/n)
    validate(target);return True

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=('export','validate'));p.add_argument('directory',nargs='?',type=Path);a=p.parse_args()
    print(json.dumps(export() if a.mode=='export' else (validate(a.directory) and {'status':'verified_saved_teaching_focus','science_calls':0}),sort_keys=True))
