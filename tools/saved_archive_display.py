"""Readable layout of one pinned earlier study; original scientific HTML stays exact."""
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL='examples/native-li/comparison.html'
ORIGINAL_SHA='8fcbe7c037f2246dc4d3e7a6e2830988bd02220e8bc25a0b452eda04c250c6b4'
PAGE='methods/native-li.html'
MANIFEST='methods/native-li-display.json'
SOURCES=('tools/saved_archive_display.py','tools/site_restructure.py','tools/site_routes.py')
LOADED={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}
PREVIOUS_RECEIPTS=frozenset({
    # Exact accepted 5c21a3e display before the teaching-route update.
    'c694ac4c70d01bcc6c57692d78911d24ae93146c96e8bb50695064f99e0ed833','d3a1b4b03629ed01ac9fb6967197aaf41c088ad16bae5d8ed09a282b998402ec',
    # Authenticated first local build 76a8596f; never published.
    '3cf2560a5ffeb398227377daed4e36bcc272379422ddb5c2b12543b363e1b723'})
LITHIUM_PAGE='lithium/lithium.html'
LITHIUM_MANIFEST='methods/lithium-display.json'
LITHIUM_ORIGINAL_SHA='ea19caf13d0bc1dc90c2dd5e676f6a0c5ed83043c5c53c14da1a975546a78742'
LITHIUM_SUMMARY_SHA='c5e1b2c85406f077cb692ac6e99dd1c9affe7cb6632a3098f96a86708e0d022c'
LITHIUM_SOURCES=SOURCES+('tools/lithium_report.py','tools/pipeline_demo.py')
LITHIUM_LOADED={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in LITHIUM_SOURCES}
PREVIOUS_LITHIUM_RECEIPTS=frozenset({
    # Exact accepted 5c21a3e display; original science remains pinned.
    'c7b03c3132201a94c7811bb813e217bcbbe911f299bded28f74e972a5cd5a301',
    # Authenticated first local build 76a8596f; never published.
    'c9ce86c38f85bf5bc2353e5c725531ac7936c733df3fd4a760c605bc6b81050c'})

def require(ok,message):
    if not ok: raise ValueError(message)

def scientific_components(text):
    """Keep original plot internals, tables, scripts and numerical settings verbatim."""
    return {tag:[hashlib.sha256(m.encode('utf-8')).hexdigest()
                 for m in re.findall(r'<'+tag+r'\b[^>]*>.*?</'+tag+r'>',text,re.S)]
            for tag in ('svg','table','script','pre')}

def expected(site):
    from site_routes import page_navigation
    current={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}
    require(current==LOADED,'Archive display source changed after import')
    raw=(Path(site)/ORIGINAL).read_bytes()
    require(hashlib.sha256(raw).hexdigest()==ORIGINAL_SHA,'Original native Li archive changed')
    text=raw.decode('utf-8');original_components=scientific_components(text)
    require(len(original_components['svg'])==56,'Original native Li plot census changed')
    old='grid-template-columns:repeat(auto-fit,minmax(270px,1fr))'
    require(text.count(old)==1 and text.count('</style>')==1,'Original archive layout anchor changed')
    text=text.replace(old,'grid-template-columns:repeat(auto-fit,minmax(min(100%,600px),1fr))',1)
    text=text.replace('</style>',
        '.plots>figure{min-width:0;overflow-x:auto}.plots svg{min-width:600px}</style>',1)
    for name in ('report.json','summary.csv','signals.csv'):
        pattern=r'href=([\"\x27])'+re.escape(name)+r'\1'
        text,n=re.subn(pattern,lambda m:'href='+m[1]+'../examples/native-li/'+name+m[1],text)
        require(n==1,'Original archive data link changed: '+name)
    title='<title>Native lithium to readout</title>'
    require(text.count(title)==1,'Original archive title changed')
    text=text.replace(title,'<title>Earlier native Li study · readable plots</title>',1)
    context=(page_navigation(PAGE)+'<section class="notice" aria-label="Earlier study context">'
        '<p><strong>Earlier selected-event native Li study · provisional response.</strong> '
        'These are the original saved curves in a wider layout. This is a separate earlier study, '
        'not the teaching gamma or Cs137 campaign dataset.</p>'
        '<p><a href="../'+ORIGINAL+'">Original archived layout</a>. '
        'On narrow screens, scroll an individual chart horizontally to read its axes. '
        'All samples, signs, time windows, tables and numerical settings are unchanged.</p></section>')
    text=text.replace('</style>','</style>'+context,1)
    require(scientific_components(text)==original_components,'Original archive scientific components changed')
    output=text.encode('utf-8')
    receipt={'kind':'saved_archive_display_v1','science_calls':0,
        'original':{ORIGINAL:ORIGINAL_SHA},'sources':current,
        'components':original_components,
        'output':{PAGE:{'bytes':len(output),'sha256':hashlib.sha256(output).hexdigest()}}}
    return output,receipt

def previous_receipt(site):
    """Verify pinned published or authenticated local archives and their outputs."""
    site=Path(site);previous=(site/MANIFEST).read_bytes()
    if hashlib.sha256(previous).hexdigest() not in PREVIOUS_RECEIPTS:return None
    old=json.loads(previous);raw=(site/PAGE).read_bytes();original=(site/ORIGINAL).read_bytes()
    require(hashlib.sha256(original).hexdigest()==ORIGINAL_SHA,'Original native Li archive changed')
    require(old['kind']=='saved_archive_display_v1' and old['science_calls']==0
            and old['original']=={ORIGINAL:ORIGINAL_SHA},'Unknown earlier archive receipt')
    require(old['output']=={PAGE:{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}},
            'Earlier readable archive HTML differs')
    components=scientific_components(original.decode('utf-8'))
    require(old['components']==components==scientific_components(raw.decode('utf-8')),
            'Earlier archive scientific components changed')
    return old

def validate(site):
    site=Path(site)
    previous=previous_receipt(site)
    if previous is not None:return previous
    output,receipt=expected(site)
    require((site/PAGE).read_bytes()==output,'Readable archive HTML differs')
    require(json.loads((site/MANIFEST).read_bytes())==receipt,'Readable archive receipt differs')
    return receipt

def assemble(site):
    site=Path(site);output,receipt=expected(site)
    if (site/PAGE).exists() or (site/MANIFEST).exists():
        require((site/PAGE).is_file() and (site/MANIFEST).is_file(),'Partial readable archive display')
        if previous_receipt(site) is None:
            return validate(site)
    (site/PAGE).parent.mkdir(parents=True,exist_ok=True)
    (site/PAGE).write_bytes(output)
    (site/MANIFEST).write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
    return validate(site)

def lithium_expected(site):
    """Validate the frozen producer through an ephemeral original HTML view."""
    from site_routes import page_navigation
    import lithium_report as producer
    site=Path(site);directory=producer.common.no_links(site/'lithium')
    current={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in LITHIUM_SOURCES}
    require(current==LITHIUM_LOADED,'Lithium display source changed after import')
    summary=(directory/'summary.json').read_bytes()
    require(hashlib.sha256(summary).hexdigest()==LITHIUM_SUMMARY_SHA,'Original lithium summary changed')
    original=producer.render(json.loads(summary)).encode('utf-8')
    require(hashlib.sha256(original).hexdigest()==LITHIUM_ORIGINAL_SHA,'Original lithium rendering changed')
    files={path.name:{'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
           for path in directory.iterdir() if path.name!='lithium.html'}
    # The producer requires exact HTML and its original file census. The
    # display receipt lives outside that bundle; no producer or local science
    # files are edited. Copy only this bounded published bundle for its check.
    with tempfile.TemporaryDirectory(prefix='lithium-display-check-',dir=ROOT/'.local') as temp:
        checked=Path(temp)
        for path in directory.iterdir():
            producer.common.relative_file(directory,path.name)
            if path.name!='lithium.html':shutil.copyfile(path,checked/path.name)
        (checked/'lithium.html').write_bytes(original)
        producer.validate_bundle(checked)
    text=original.decode('utf-8');anchor='<body>'
    require(text.count(anchor)==1,'Original lithium body anchor changed')
    output=text.replace(anchor,anchor+page_navigation(LITHIUM_PAGE),1).encode('utf-8')
    components=scientific_components(text)
    require(scientific_components(output.decode('utf-8'))==components,'Lithium scientific components changed')
    require(files=={path.name:{'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                   for path in directory.iterdir() if path.name!='lithium.html'},
            'Lithium scientific files changed during validation')
    receipt={'kind':'saved_lithium_navigation_v1','science_calls':0,
        'original_html_sha256':LITHIUM_ORIGINAL_SHA,'original_files':files,
        'sources':current,'components':components,
        'output':{LITHIUM_PAGE:{'bytes':len(output),'sha256':hashlib.sha256(output).hexdigest()}}}
    require(current=={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in LITHIUM_SOURCES},
            'Lithium display source changed during validation')
    return output,receipt

def previous_lithium_receipt(site):
    """Verify the exact authenticated intermediate display, never resealed edits."""
    import lithium_report as producer
    site=Path(site);raw=(site/LITHIUM_MANIFEST).read_bytes()
    if hashlib.sha256(raw).hexdigest() not in PREVIOUS_LITHIUM_RECEIPTS:return None
    receipt=json.loads(raw);directory=producer.common.no_links(site/'lithium')
    require(receipt['kind']=='saved_lithium_navigation_v1' and receipt['science_calls']==0
            and receipt['original_html_sha256']==LITHIUM_ORIGINAL_SHA,'Unknown earlier lithium receipt')
    files=receipt['original_files']
    require(set(path.name for path in directory.iterdir())==set(files)|{'lithium.html'},
            'Earlier lithium file census changed')
    for name,stamp in files.items():
        data=producer.common.relative_file(directory,name).read_bytes()
        require(stamp=={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()},
                'Earlier lithium scientific file changed')
    summary=producer.common.relative_file(directory,'summary.json').read_bytes()
    require(hashlib.sha256(summary).hexdigest()==LITHIUM_SUMMARY_SHA,'Original lithium summary changed')
    original=producer.render(json.loads(summary)).encode('utf-8')
    require(hashlib.sha256(original).hexdigest()==LITHIUM_ORIGINAL_SHA,'Original lithium rendering changed')
    output=producer.common.relative_file(directory,'lithium.html').read_bytes()
    require(receipt['output']=={LITHIUM_PAGE:{'bytes':len(output),'sha256':hashlib.sha256(output).hexdigest()}},
            'Earlier lithium display HTML differs')
    require(receipt['components']==scientific_components(original.decode('utf-8'))
            ==scientific_components(output.decode('utf-8')),'Earlier lithium scientific components changed')
    return receipt

def validate_lithium_display(site):
    site=Path(site);previous=previous_lithium_receipt(site)
    if previous is not None:return previous
    output,receipt=lithium_expected(site)
    require((site/LITHIUM_PAGE).read_bytes()==output,'Lithium display HTML differs')
    require(json.loads((site/LITHIUM_MANIFEST).read_bytes())==receipt,'Lithium display receipt differs')
    return receipt

def upgrade_lithium_display(site):
    """Add shared navigation to the published frozen report without new science."""
    site=Path(site)
    if not (site/LITHIUM_PAGE).is_file():return False
    output,receipt=lithium_expected(site);raw=(site/LITHIUM_PAGE).read_bytes()
    if (site/LITHIUM_MANIFEST).exists():
        if previous_lithium_receipt(site) is None:
            require(raw==output,'Lithium display HTML differs')
            require(json.loads((site/LITHIUM_MANIFEST).read_bytes())==receipt,'Lithium display receipt differs')
            return receipt
    else:require(hashlib.sha256(raw).hexdigest()==LITHIUM_ORIGINAL_SHA,'Unknown original lithium HTML')
    (site/LITHIUM_PAGE).write_bytes(output)
    (site/LITHIUM_MANIFEST).parent.mkdir(parents=True,exist_ok=True)
    (site/LITHIUM_MANIFEST).write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
    return receipt
