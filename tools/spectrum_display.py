"""Generate spectrum views from saved histogram files; original reports stay unchanged."""
from __future__ import annotations
import hashlib
import html
import json
import math
import posixpath
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from spectrum_plot import panel, assets, require, validate_spec
ROOT=Path(__file__).resolve().parents[1]
ROUTES={'examples/cs137-1m/report.html':'spectra/million-truth.html',
        'examples/cs137-1m-response/report.html':'spectra/million-response.html',
        'examples/cs137-10k/comparison.html':'spectra/cs137-10k.html',
        'examples/pipeline.html':'spectra/pipeline.html'}
GENERATORS=('tools/spectrum_display.py','tools/spectrum_plot.py','tools/spectrum_controls.js')

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def write_if_changed(path,text):
    data=text.encode('utf-8'); path=Path(path)
    if not path.exists() or path.read_bytes()!=data:
        path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)

def series(hist,label,color):
    return {'label':label,'color':color,'counts':hist['counts'],'total':hist['total'],
            'underflow':hist['underflow'],'overflow':hist['overflow'],'exact_zero':hist.get('exact_zero',0)}

def specification(key,title,edges,rows,view,xlabel='Energy (keV)',note=''):
    return validate_spec({'key':key,'title':title,'edges':edges,'series':rows,'view':view,
                          'xlabel':xlabel,'note':note})

def response_specs(site):
    data=read(site/'examples/cs137-1m-response/histograms.json'); result=[]
    for model in ('AK02','SAP22'):
        h=data[model]['deposited_truth']; n=len(h['counts'])
        other=data[model]['reconstructed_accepted']
        require(all(h[k]==other[k] for k in ('lower_keV','upper_keV','width_keV')) and len(other['counts'])==n,'Overlay histogram edge definitions differ')
        edges=[h['lower_keV']+i*h['width_keV'] for i in range(n+1)]
        rows=[series(h,'Geant4 deposited-energy truth','#406090'),
              series(data[model]['reconstructed_accepted'],'Accepted peak-ADC reconstructed energy','#b05040')]
        for lo,hi in ((0,750),(620,680)):
            result.append(specification(f'response-{model}-{lo}',f'{model}: {lo}-{hi} keV',edges,rows,[lo,hi],
                note='1 keV bins [lower, upper). Raw pulse-group counts from 1,000,000 initial decays/model. Native failures and electronics rejects are not inserted into the accepted spectrum.'))
    return result

def truth_specs(site):
    data=read(site/'examples/cs137-1m/histograms.json'); result=[]
    for model in ('AK02','SAP22'):
        for pop,label in (('per_initial_decay','per initial decay'),('per_isolated_group','per isolated group')):
            h=data[model][pop]
            result.append(specification(f'truth-{model}-{pop}',f'{model}: deposition {label}',h['edges_keV'],
                [series(h,'Geant4 deposition truth','#116a92')],[h['edges_keV'][0],h['edges_keV'][-1]],
                xlabel='Ge deposition truth Edep (keV)',note='1 keV bins [lower, upper); exact-zero energy is a separate category. Counts are not normalized per decay.'))
    return result

STAGES=(('deposited_per_decay','Deposited energy / initial decay (includes zeros)'),
        ('deposited_per_group','Deposited energy / all groups (includes native failures)'),
        ('native_terminal_charge','Native signed terminal charge / successful native group'),
        ('analog_shaped_equivalent','Analog shaped peak / successful native group'),
        ('accepted_peak_ADC','Accepted peak-ADC energy / pulse'))

def sparse_stage(data,stage):
    require(data['width_keV']==5,'Unexpected sparse histogram width')
    edges=list(range(-1000,4001,5)); counts=[0]*1000; under=over=0; occupied=[]; seen=set()
    for row in data['bins']:
        if row['stage']!=stage: continue
        i=row['bin']; require(type(i) is int and i not in seen,'Duplicate or invalid sparse bin'); seen.add(i)
        count=row['count']; require(type(count) is int and count>0,'Invalid sparse count')
        if i==-1:
            require(row['lower_keV'] is None and row['upper_keV']==-1000,'Invalid underflow'); under=count
        elif i==1000:
            require(row['lower_keV']==4000 and row['upper_keV'] is None,'Invalid overflow'); over=count
        else:
            require(0<=i<1000 and row['lower_keV']==edges[i] and row['upper_keV']==edges[i+1],'Sparse edges disagree with bin ID')
            counts[i]=count; occupied.append(i)
    hist={'counts':counts,'underflow':under,'overflow':over,'total':sum(counts)+under+over}
    lo=min([0]+[edges[i] for i in occupied]); hi=max([10]+[edges[i+1] for i in occupied])
    return edges,hist,[lo,hi]

def tenk_specs(site):
    result=[]
    for model in ('AK02','SAP22'):
        data=read(site/f'examples/cs137-10k/{model}/response/histograms.json')
        for stage,label in STAGES:
            edges,hist,view=sparse_stage(data,stage)
            result.append(specification(f'tenk-{model}-{stage}',f'{model}: {label}',edges,
                [series(hist,label,'#17334b')],view,xlabel='Energy / equivalent energy (keV)',
                note='5 keV bins [lower, upper). Raw counts with stage-specific populations; deposited-per-decay includes zero-energy decays. Negative equivalent-energy bins remain negative on x.'))
    return result

def pipeline_specs(site):
    data=read(site/'examples/data.json'); result=[]
    for m in data['models']:
        truth=[e['deposited_energy_keV'] for e in m['events']]
        reco=[e['reconstructed_energy_keV'] for e in m['events'] if e['accepted']]
        require(all(type(v) in (int,float) and math.isfinite(v) and v>=0 for v in truth+reco),'Unsupported saved pipeline energy')
        upper=max([data['settings']['energy_keV']]+truth+reco)*1.04 or 1; n=24
        def counts(values):
            a=[0]*n
            for v in values: a[max(0,min(n-1,math.floor(v/upper*n)))]+=1
            return a
        rows=[]
        for values,label,color in ((truth,'Edep - all primaries','#007e83'),(reco,'Erec - accepted only','#bd6b17')):
            rows.append({'counts':counts(values),'label':label,'color':color,'total':len(values),'underflow':0,'overflow':0,'exact_zero':0})
        s=specification('pipeline-energy',m['model_id']+': deposited vs reconstructed energy',
            [i*upper/n for i in range(n+1)],rows,[0,upper],note='Original 24-bin display rule retained. Truth includes zero-deposit primaries; reconstructed energy contains accepted events only. Low-statistics engineering example, not measured resolution.')
        s['model_id']=m['model_id'];result.append(s)
    return result

def rewrite_links(text,source_page,destination_page):
    def replace(match):
        url=html.unescape(match.group(2)); parts=urlsplit(url)
        if parts.scheme or parts.netloc or not parts.path or parts.path.startswith('/'):
            return match.group(0)
        target=posixpath.normpath(posixpath.join(posixpath.dirname(source_page),parts.path))
        target=ROUTES.get(target,target)
        relative=posixpath.relpath(target,posixpath.dirname(destination_page) or '.')
        value=urlunsplit(('', '',relative,parts.query,parts.fragment))
        return match.group(1)+html.escape(value,quote=True)+match.group(3)
    return re.sub(r'(href=["\'])([^"\']*)(["\'])',replace,text)

def replace_plots(text,specs,figures=False):
    expression=r'<figure>.*?</figure>' if figures else r'<svg\b[^>]*>.*?</svg>'
    matches=list(re.finditer(expression,text,re.S)); require(len(matches)==len(specs),'Unexpected original spectrum plot inventory')
    for match,spec in reversed(list(zip(matches,specs))):
        text=text[:match.start()]+panel(spec)+text[match.end():]
    return text

def add_at_end(text,content):
    index=text.rfind('</body>')
    if index<0: index=text.rfind('</html>')
    return text[:index]+content+text[index:] if index>=0 else text+content

def pipeline_page(text,specs):
    original=r'<svg id="histogram"[^>]*></svg>'
    require(len(re.findall(original,text))==1,'Original pipeline histogram missing')
    data={s['model_id']:s for s in specs}
    payload=json.dumps(data,ensure_ascii=True,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    replacement=panel(specs[0])+'<script id="pipeline-spectrum-specs" type="application/json">'+payload+'</script>'
    text=re.sub(original,lambda _:replacement,text,count=1)
    start=text.index('    const a=bins(truth),b=bins(rec),svg=$("histogram")')
    end=text.index('    put("truth-legend"',start)
    new='''    const a=bins(truth),b=bins(rec);
    const display=JSON.parse($("pipeline-spectrum-specs").textContent)[m.model_id];
    if(max!==display.view[1] || a.some((v,i)=>v!==display.series[0].counts[i]) || b.some((v,i)=>v!==display.series[1].counts[i]))throw Error("Saved pipeline spectrum bins differ");
    window.SpectrumUI.update("pipeline-energy",display);
'''
    text=text[:start]+new+text[end:]
    needle='<script>\n"use strict";'
    require(text.count(needle)==1,'Original pipeline script anchor changed')
    return text.replace(needle,assets()+needle,1)

READERS={'spectra/million-truth.html':truth_specs,'spectra/million-response.html':response_specs,
         'spectra/cs137-10k.html':tenk_specs,'spectra/pipeline.html':pipeline_specs}
DATA_SOURCES=('examples/cs137-1m/histograms.json','examples/cs137-1m-response/histograms.json',
              'examples/cs137-10k/AK02/response/histograms.json','examples/cs137-10k/SAP22/response/histograms.json','examples/data.json')
RECEIPTS=('examples/cs137-1m/publication.json','examples/cs137-1m-response/publication.json','examples/cs137-10k/publication.json')

def render_page(site,original,destination,specs):
    text=(site/original).read_text(encoding='utf-8')
    if destination=='spectra/pipeline.html':
        text=pipeline_page(text,specs)
    else:
        text=replace_plots(text,specs,figures=destination=='spectra/cs137-10k.html')
        if destination=='spectra/million-truth.html':
            old='Y uses log10(1 + count).'
            require(text.count(old)==2,'Original truth caption changed')
            text=text.replace(old,'Default logarithmic count axis; use the Linear / Log buttons.')
        text=text.replace('No SSD, readout or noise has run for this campaign.','This page shows Geant4 deposition truth only. The completed native SSD/readout response is reported separately.')
        text=add_at_end(text,assets())
    text=rewrite_links(text,original,destination)
    archive=posixpath.relpath(original,'spectra')
    note=('<aside class="spectrum-note"><strong>Updated spectrum display.</strong> Exact saved bins; default Log, optional Linear. No simulations rerun. '
          '<a href="../results/index.html">Results</a> · <a href="'+archive+'">Original report (archived presentation)</a> · <a href="manifest.json">Display provenance</a></aside>')
    anchor=text.find('<h1')
    require(anchor>=0,'Report heading missing')
    text=text[:anchor]+note+text[anchor:]
    return text

def component_hashes(text):
    charts=re.findall(r'<svg class="spectrum-chart".*?</svg>',text,re.S)
    scripts=re.findall(r'<script id="spectrum-controls-script">(.*?)</script>',text,re.S)
    styles=re.findall(r'<style id="spectrum-style">(.*?)</style>',text,re.S)
    require(len(scripts)==len(styles)==1,'Expected one shared spectrum asset block')
    return {'charts':[hashlib.sha256(s.encode()).hexdigest() for s in charts],
            'script':hashlib.sha256(scripts[0].encode()).hexdigest(),
            'style':hashlib.sha256(styles[0].encode()).hexdigest()}

def home_component(site):
    text=(Path(site)/'index.html').read_text(encoding='utf-8')
    blocks=re.findall(r'<figure class="spectrum-panel".*?</figure>',text,re.S)
    require(len(blocks)==1,'Homepage must contain one spectrum preview')
    return text,blocks[0]

def validate_home(site,manifest,strict=False):
    text,block=home_component(site); metadata=manifest['homepage']
    require(component_hashes(text)==metadata['render_components'],'Homepage spectrum rendering changed')
    require(embedded_specs(block)==response_specs(Path(site))[:1],'Homepage spectrum data differs')
    require(hashlib.sha256(block.encode()).hexdigest()==metadata['panel_sha256'],'Homepage spectrum panel changed')
    if strict: require(block==panel(response_specs(Path(site))[0],compact=True),'Homepage spectrum differs from current renderer')

def finalize(site):
    site=Path(site);text,block=home_component(site);m=read(site/'spectra/manifest.json')
    m['homepage']={'panel_sha256':hashlib.sha256(block.encode()).hexdigest(),'render_components':component_hashes(text)}
    write_if_changed(site/'spectra/manifest.json',json.dumps(m,indent=2,allow_nan=False)+'\n')
    return validate(site,require_current_generators=True,require_home=True)

def assemble(site):
    site=Path(site)
    if not any((site/p).is_file() for p in ROUTES): return None
    require(all((site/p).is_file() for p in ROUTES),'Partial source spectrum report set')
    sources=tuple(ROUTES)+DATA_SOURCES+RECEIPTS
    origin={rel:sha(site/rel) for rel in sources}; pages={}
    for original,destination in ROUTES.items():
        specs=READERS[destination](site)
        text=render_page(site,original,destination,specs)
        write_if_changed(site/destination,text)
        pages[destination]={'source':original,'source_sha256':origin[original],
            'sha256':sha(site/destination),'specs_sha256':digest(specs),'plot_states':len(specs),
            'render_components':component_hashes(text)}
    require(origin=={rel:sha(site/rel) for rel in sources},'Source reports or numeric data changed')
    manifest={'kind':'saved_spectrum_display_v1','display_revision':2,'default_scale':'log','histogram_style':'step',
              'zero_count_policy':'gaps on true log axes; no pseudocounts',
              'origin_files':origin,'generators':{rel:sha(ROOT/rel) for rel in GENERATORS},
              'pages':pages,'new_simulations':0,'original_reports_modified':False,
              'scope':'Current views derived from saved results. Original reports and complete scientific bundles remain unchanged.'}
    write_if_changed(site/'spectra/manifest.json',json.dumps(manifest,indent=2,allow_nan=False)+'\n')
    return validate(site,require_current_generators=True)

def embedded_specs(text):
    return [json.loads(s) for s in re.findall(r'<script type="application/json" class="spectrum-data">(.*?)</script>',text,re.S)]

def validate(site,require_current_generators=False,require_home=False):
    site=Path(site); folder=site/'spectra'; m=read(folder/'manifest.json')
    require(m['kind']=='saved_spectrum_display_v1' and m['default_scale']=='log','Unsupported spectrum display manifest')
    require(set(m['pages'])==set(ROUTES.values()),'Spectrum page inventory changed')
    require({p.name for p in folder.iterdir()}=={Path(p).name for p in ROUTES.values()}|{'manifest.json'},'Unexpected spectrum directory contents')
    require(set(m['origin_files'])==set(ROUTES)|set(DATA_SOURCES)|set(RECEIPTS),'Incomplete origin binding')
    for rel,h in m['origin_files'].items(): require(sha(site/rel)==h,'Original spectrum source changed: '+rel)
    current={rel:sha(ROOT/rel) for rel in GENERATORS}
    same_generators=m['generators']==current
    if require_current_generators:
        require(same_generators and m.get('display_revision')==2,'Candidate generator binding mismatch')
    for destination,record in m['pages'].items():
        text=(site/destination).read_text(encoding='utf-8'); expected=READERS[destination](site)
        require(sha(site/destination)==record['sha256'],'Display HTML changed')
        if m.get('display_revision')==2:
            require(component_hashes(text)==record['render_components'],'Static chart or controls changed')
        if require_current_generators or (m.get('display_revision')==2 and same_generators):
            require(text==render_page(site,record['source'],destination,expected),'Rendered display differs from deterministic generator')
        require(record['specs_sha256']==digest(expected),'Spectrum reader/data mismatch')
        actual=embedded_specs(text)
        require(actual==(expected[:1] if destination=='spectra/pipeline.html' else expected),'Display bin data or labels changed')
        require(text.count('id="spectrum-controls-script"')==1 and text.count('id="spectrum-style"')==1,'Missing or duplicate spectrum controls')
        if destination=='spectra/pipeline.html':
            states=re.findall(r'<script id="pipeline-spectrum-specs" type="application/json">(.*?)</script>',text,re.S)
            require(len(states)==1 and json.loads(states[0])=={s['model_id']:s for s in expected},'Pipeline model-state data changed')
            def payload(body):
                start=body.index('<script id="pipeline-data" type="application/json">')
                return body[start:body.index('</script>',start)]
            require(payload(text)==payload((site/'examples/pipeline.html').read_text(encoding='utf-8')),'Pipeline event/waveform payload changed')
    if require_home or "homepage" in m:
        validate_home(site,m,require_current_generators or same_generators)
    return m

def route_current_pages(site):
    site=Path(site)
    for p in site.rglob('*.html'):
        rel=p.relative_to(site).as_posix()
        if rel.startswith(('examples/','spectra/','lithium/')): continue
        if rel.startswith('detectors/') and p.name not in ('index.html','gallery.html','technical.html'): continue
        text=p.read_text(encoding='utf-8'); updated=rewrite_links(text,rel,rel)
        if updated!=text: write_if_changed(p,updated)

def homepage_preview(site):
    path=Path(site)/'spectra/million-response.html'
    if not path.is_file(): return None
    spec=response_specs(Path(site))[0]
    return panel(spec,compact=True)+assets()

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('site',type=Path)
    parser.add_argument('--validate',action='store_true');args=parser.parse_args()
    result=validate(args.site) if args.validate else assemble(args.site)
    print(json.dumps({'status':'passed','pages':list(result['pages'])},indent=2))
