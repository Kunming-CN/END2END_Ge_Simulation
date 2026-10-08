"""Readable layout of one pinned earlier study; original scientific HTML stays exact."""
import hashlib
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL='examples/native-li/comparison.html'
ORIGINAL_SHA='8fcbe7c037f2246dc4d3e7a6e2830988bd02220e8bc25a0b452eda04c250c6b4'
PAGE='methods/native-li.html'
MANIFEST='methods/native-li-display.json'
SOURCES=('tools/saved_archive_display.py','tools/site_restructure.py')
LOADED={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}

def require(ok,message):
    if not ok: raise ValueError(message)

def scientific_components(text):
    """Keep original plot internals, tables, scripts and numerical settings verbatim."""
    return {tag:[hashlib.sha256(m.encode('utf-8')).hexdigest()
                 for m in re.findall(r'<'+tag+r'\b[^>]*>.*?</'+tag+r'>',text,re.S)]
            for tag in ('svg','table','script','pre')}

def expected(site):
    from site_restructure import navigation
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
    context=(navigation('../')+'<section class="notice" aria-label="Earlier study context">'
        '<p><strong>Earlier selected-event native Li study · provisional response.</strong> '
        'These are the original saved curves in a wider layout. This is a separate earlier study, '
        'not the teaching gamma or Cs137 campaign dataset.</p>'
        '<p><a href="index.html">Methods and limitations</a> · '
        '<a href="../'+ORIGINAL+'">Original archived layout</a>. '
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

def validate(site):
    site=Path(site);output,receipt=expected(site)
    require((site/PAGE).read_bytes()==output,'Readable archive HTML differs')
    require(json.loads((site/MANIFEST).read_bytes())==receipt,'Readable archive receipt differs')
    return receipt

def assemble(site):
    site=Path(site);output,receipt=expected(site)
    if (site/PAGE).exists() or (site/MANIFEST).exists():
        require((site/PAGE).is_file() and (site/MANIFEST).is_file(),'Partial readable archive display')
        return validate(site)
    (site/PAGE).parent.mkdir(parents=True,exist_ok=True)
    (site/PAGE).write_bytes(output)
    (site/MANIFEST).write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
    return validate(site)
