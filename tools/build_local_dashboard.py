"""Build a local-only project index without moving data or starting calculations."""
from __future__ import annotations
import argparse
import json
import os
import tempfile
from local_paths import safe_path, require_safe
from html import escape
from pathlib import Path
from urllib.parse import quote
ROOT=Path(__file__).resolve().parents[1]
SCIENCE={'cs137-1m','cs137-1m-native','peak-native-delivery','million-analysis',
         'native-final-analysis-v3','native-final-report-v2','native-li-example'}
ACTIVE={'runs','autonomy'}
REFERENCES={'reference-docs'}
LABELS={'cs137-1m': 'Permanent radiation truth and checkpoints', 'cs137-1m-native': 'Permanent native charge and readout checkpoints', 'million-analysis': 'Deposition analysis and preservation audit', 'native-final-analysis-v3': 'Current final response integrity audit', 'native-final-report-v2': 'Current final response report', 'peak-native-delivery': 'Earlier baselines and diagnostic failures', 'native-li-example': 'Selected native-response example', 'runs': 'Local launcher runs', 'autonomy': 'Coordination records, not live process status'}

def group(name):
    if name in SCIENCE:
        return 'Permanent science and completed results'
    if name in ACTIVE:
        return 'Run directories and coordination'
    if name in REFERENCES:
        return 'Reference documents'
    return 'Preserved development, review and diagnostic evidence'

def atomic_text(path, text, root):
    require_safe(path,root)
    if path.exists() and path.read_text(encoding='utf-8')==text:
        return
    fd,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.partial',dir=path.parent)
    temp=Path(name)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        require_safe(path,root)
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)

def build(root=ROOT):
    root=Path(root).resolve()
    local=root/'.local'
    out=local/'workspace'
    for p in (local,out,out/'index.html',out/'inventory.json'):
        require_safe(p,root)
    out.mkdir(parents=True,exist_ok=True)
    def link(path,label,allow_html=False):
        if not safe_path(path,root):
            return escape(label)+' (linked path; not opened)'
        documents={'.md','.txt','.json','.csv','.pdf','.pptx','.docx','.png','.jpg','.jpeg','.svg','.yaml','.toml','.log'}
        if not path.is_dir() and path.suffix.lower() not in documents and not (allow_html and path.suffix.lower()=='.html'):
            return escape(label)+' (non-actionable file)'
        relative=os.path.relpath(path,out).replace('\\','/')
        return '<a href="'+quote(relative,safe='/.:')+'">'+escape(label)+'</a>'
    entries=[]
    for path in sorted(local.iterdir(),key=lambda p:p.name.casefold()):
        if path.name=='workspace':
            continue
        entry={'name':path.name,'path':path.relative_to(root).as_posix(),
               'group':group(path.name),'type':('linked path; not opened' if not safe_path(path,root) else ('directory' if path.is_dir() else 'file')),
               'retention':'preserve; classification never authorizes deletion'}
        receipts=[]
        if safe_path(path,root) and path.is_dir():
            for name in ('COMPLETE.json','run.json','progress.json','state.json'):
                candidate=path/name
                if safe_path(candidate,root) and candidate.is_file():
                    receipts.append(candidate.relative_to(root).as_posix())
        entry['receipt_links']=receipts
        entries.append(entry)
    sections=[]
    for category in ('Permanent science and completed results','Run directories and coordination',
                     'Reference documents','Preserved development, review and diagnostic evidence'):
        if category=='Reference documents':
            continue
        rows=[]
        for entry in entries:
            if entry['group']!=category:
                continue
            receipts=' · '.join(link(root/p,Path(p).name) for p in entry['receipt_links'])
            rows.append('<tr><td>'+link(root/entry['path'],LABELS.get(entry['name'],entry['name']))+'</td><td>'+
                        escape(entry['type'])+'</td><td>'+receipts+'</td></tr>')
        sections.append('<details'+(' open' if category=='Permanent science and completed results' else '')+'><summary>'+category+'</summary><div class="scroll">'
                        '<table><thead><tr><th>Location</th><th>Type</th><th>Saved receipts/status files</th>'
                        '</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></details>')
    report_links=[]
    for relative,label in [('docs/examples/cs137-1m-response/report.html','Final SSD / electronics / ADC comparison'),
                           ('docs/examples/cs137-1m/report.html','Final Geant4 deposited-energy results')]:
        path=root/relative
        report_links.append('<p>'+link(path,label,allow_html=True)+'</p>' if safe_path(path,root) and path.is_file()
                            else '<p>'+escape(label)+' — not included in this checkout.</p>')
    final_reports='<section><h2>Open final results</h2>'+''.join(report_links)+'<p>Saved 1M-per-detector engineering results; these links do not run computations.</p></section>'
    primary=[]
    for rel,label in [('docs/index.html','Browse saved website'),('docs/guide.html','Setup and run guide'),
                      ('README.md','Project quick introduction'),('tools/LOCAL_WORKSPACE.md','Directory and retention guide'),
                      ('.local/reference-docs','Reference documents')]:
        if (root/rel).exists():
            primary.append(link(root/rel,label,allow_html=True))
    source_links=' · '.join(link(root/p,p) for p in ('models','scenarios','simulation','transport','tools',
                       'Additional_Simulations','2D_GeGI detector Simulation') if (root/p).exists())
    references=[]
    reference_root=local/'reference-docs'
    if safe_path(reference_root,root) and reference_root.is_dir():
        for base,dirs,files in os.walk(reference_root,followlinks=False):
            dirs[:]=sorted(d for d in dirs if safe_path(Path(base,d),root))
            for name in sorted(files):
                path=Path(base,name)
                references.append('<p>'+link(path,path.relative_to(reference_root).as_posix())+'</p>')
    html='''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>END2END local workspace</title>
<style>*{box-sizing:border-box}body{overflow-wrap:anywhere;font:16px/1.55 system-ui;max-width:1140px;margin:auto;padding:24px;background:#f5f7fa;color:#183047}
a{color:#075e9b}nav{display:flex;flex-wrap:wrap;gap:16px}section,details{background:white;padding:20px;margin:18px 0;border:1px solid #d7e0e7;border-radius:10px}
summary{font-size:1.2rem;font-weight:bold;cursor:pointer}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:10px;border-bottom:1px solid #ddd;overflow-wrap:anywhere}.scroll{overflow:auto}code{background:#edf2f6;padding:3px 5px}</style>
<h1>END2END local workspace</h1><p>Local-only navigation. Opening or refreshing this index does not run or resume any simulation.</p>
<nav>'''+ ' · '.join(primary)+'''</nav>'''+final_reports+'''
<section><h2>Run, check or inspect status</h2><p>Use the root <code>Run.cmd</code> menu, or run <code>.\\Run.cmd check</code>, <code>.\\Run.cmd detectors</code> and <code>.\\Run.cmd status</code>.</p>
<p><code>.\\Run.cmd run -Detector AK02 -Preset demo</code> or <code>-Detector SAP22</code> selects a separate LBNL case. <code>both</code> runs two separate cases, not two crystals in one assembly.</p>
<p>These commands are shown as text, not automatic actions. Completed campaigns must not be restarted just to view results.</p></section>
<section><h2>Code, canonical models and original workspaces</h2>'''+source_links+'''<p>Existing source and science paths are retained. These manually maintained navigation categories do not indicate live process status. <a href="../../PROGRESS.md">Maintainer progress and full roadmap</a>.</p></section>
<section><h2>Reference documents</h2>'''+''.join(references)+'''</section>
<details><summary>Retention and interpreting saved status</summary><p>Receipt links show recorded status; progress/state files can be stale. Recovery requires terminal receipts and verified process ownership. This page is not a live worker monitor. Unclassified evidence is retained for inspection. No scientific files were relocated by the index generator.</p>
<p>Saved geometry pages use JSON fetches. For drag rotation use GitHub Pages or serve <code>docs/</code> through local HTTP; direct file opening retains the static fallback.</p></details>'''+''.join(sections)+'''<p>Refresh through Open_Workspace.cmd. Inventory: <a href="inventory.json">inventory.json</a>.</p></html>'''
    inventory={'schema_version':1,'kind':'local_workspace_index','entries':entries,
               'recursive_science_scan':False,'simulations_started':0,'files_moved':0,'files_deleted':0}
    atomic_text(out/'index.html',html,root)
    atomic_text(out/'inventory.json',json.dumps(inventory,indent=2)+'\n',root)
    return inventory

if __name__=='__main__':
    result=build()
    print('Local workspace indexed:',len(result['entries']),'retained entries; no calculations or cleanup.')
