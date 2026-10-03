"""Presentation-only teaching derivative from the already completed saved data."""
import argparse
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
    data=S.decode(raw);S.require((directory/'pipeline.html').read_bytes()==render(data),'Exact focused teaching template/data')
    S.require(manifest['template_sha256']==S.sha((ROOT/TEMPLATE).read_bytes()) and manifest['javascript_sha256']==S.sha((ROOT/JS).read_bytes()),'Frozen presentation sources')
    return data

def assemble(target):
    source=ROOT/BASE
    if not source.exists():return False
    validate(source);target=Path(target)
    S.require((target/'data.json').read_bytes()==(source/'data.json').read_bytes(),'Staged teaching numerical data differs')
    for n in FILES:shutil.copyfile(source/n,target/n)
    validate(target);return True

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=('export','validate'));p.add_argument('directory',nargs='?',type=Path);a=p.parse_args()
    print(json.dumps(export() if a.mode=='export' else (validate(a.directory) and {'status':'verified_saved_teaching_focus','science_calls':0}),sort_keys=True))
