"""Pure saved-bin spectrum rendering: true log/linear axes, no physics or fitting."""
from __future__ import annotations
import html
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def require(ok, message):
    if not ok:
        raise ValueError(message)

def validate_spec(spec):
    edges = spec['edges']; n = len(edges) - 1
    require(n > 0 and all(type(x) in (int, float) and math.isfinite(x) for x in edges), 'Invalid spectrum edges')
    require(all(a < b for a, b in zip(edges, edges[1:])), 'Unordered spectrum edges')
    lo, hi = spec['view']
    require(edges[0] <= lo < hi <= edges[-1], 'View outside saved histogram')
    require(lo in edges and hi in edges, 'View must use exact saved bin edges')
    require(spec['series'], 'No spectrum series')
    for series in spec['series']:
        counts = series['counts']
        require(len(counts) == n and all(type(v) is int and v >= 0 for v in counts), 'Invalid raw bin counts')
        for key in ('underflow', 'overflow', 'exact_zero', 'total'):
            require(type(series[key]) is int and series[key] >= 0, 'Invalid spectrum accounting')
        require(sum(counts) + series['underflow'] + series['overflow'] + series['exact_zero'] == series['total'], 'Spectrum census mismatch')
    return spec

def geometry(spec, scale='log'):
    validate_spec(spec)
    require(scale in ('linear', 'log'), 'Unknown spectrum scale')
    edges = spec['edges']; lo, hi = spec['view']
    selected = [i for i in range(len(edges)-1) if lo <= edges[i] and edges[i+1] <= hi]
    peak = max([s['counts'][i] for s in spec['series'] for i in selected] + [1])
    low = 0.5 if scale == 'log' else 0.0
    high = max(10, 10 ** math.ceil(math.log10(peak))) if scale == 'log' else max(1, peak * 1.1)
    x = lambda value: 70 + 660 * (value-lo)/(hi-lo)
    if scale == 'log':
        y = lambda value: 242 - 204 * (math.log10(value)-math.log10(low))/(math.log10(high)-math.log10(low))
        ticks = sorted({float(a * 10**e) for e in range(0, int(math.log10(high))+1) for a in ((1,2,5) if high <= 10 else (1,)) if a*10**e <= high})
    else:
        y = lambda value: 242 - 204 * value/high
        ticks = [peak * i/4 for i in range(5)]
    paths=[]
    for series in spec['series']:
        commands=[]; last=None
        for i in selected:
            count=series['counts'][i]
            if scale=='log' and count==0:
                last=None
                continue
            commands.append(('L' if last==i-1 else 'M') + f'{x(edges[i]):.3f},{y(count):.3f}')
            commands.append(f'L{x(edges[i+1]):.3f},{y(count):.3f}')
            last=i
        paths.append(' '.join(commands))
    return {'selected':selected,'paths':paths,'ticks':ticks,'x':x,'y':y,'low':low,'high':high}

def svg(spec, scale='log'):
    g=geometry(spec,scale); esc=html.escape; x=g['x']; y=g['y']; lo,hi=spec['view']
    out=[f'<svg class="spectrum-chart" viewBox="0 0 760 292" role="img" aria-label="{esc(spec["title"])}; {scale} count axis">',
         f'<title>{esc(spec["title"])}: exact saved bins, {scale} count scale</title>']
    for tick in g['ticks']:
        out.append(f'<path d="M70 {y(tick):.3f}H730" stroke="#dce3e8" fill="none"/><text x="62" y="{y(tick)+4:.3f}" text-anchor="end">{tick:g}</text>')
    for i in range(6):
        value=lo+(hi-lo)*i/5
        out.append(f'<text x="{x(value):.3f}" y="262" text-anchor="middle">{value:.5g}</text>')
    out.append('<path d="M70 38V242H730" stroke="#677988" fill="none"/>')
    for i,(series,path) in enumerate(zip(spec['series'],g['paths'])):
        dash=' stroke-dasharray="6 3"' if i else ''
        out.append(f'<path class="spectrum-step" d="{path}" fill="none" stroke="{esc(series["color"],quote=True)}" stroke-width="1.4"{dash} vector-effect="non-scaling-stroke"><title>{esc(series["label"])}</title></path>')
    if not any(g['paths']):
        out.append('<text x="400" y="140" text-anchor="middle">No positive-count bins in this view</text>')
    label='Counts / bin (log10 scale)' if scale=='log' else 'Counts / bin (linear scale)'
    out.append(f'<text x="70" y="21">{label}</text><text x="400" y="285" text-anchor="middle">{esc(spec["xlabel"])}</text></svg>')
    return ''.join(out)

def accounting(spec):
    g=geometry(spec); result=[]
    for s in spec['series']:
        shown=sum(s['counts'][i] for i in g['selected']); outside=sum(s['counts'])-shown
        text=f'{s["label"]}: {shown:,} in view; {outside:,} outside view; under/overflow {s["underflow"]:,}/{s["overflow"]:,}'
        if s['exact_zero']: text+=f'; {s["exact_zero"]:,} exact-zero events listed separately'
        result.append(text+f'; population {s["total"]:,}.')
    return result

STYLE='''
.spectrum-panel{margin:16px 0;padding:14px;background:#fff;border:1px solid #d9e2e8;border-radius:10px;min-width:0;color:#173047}
.spectrum-panel>figcaption{font:600 15px/1.4 system-ui;margin-bottom:9px}.spectrum-controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.spectrum-controls button{font:inherit;min-width:74px;min-height:44px;padding:8px 13px;border:1px solid #97aaba;border-radius:7px;background:white;color:inherit;cursor:pointer}
.spectrum-controls button[aria-pressed=true]{background:#173047;color:white}.spectrum-controls button:focus-visible{outline:3px solid #b47716;outline-offset:2px}
.spectrum-panel .spectrum-chart{display:block;width:100%;height:auto;margin:8px 0;font:13px system-ui;overflow:visible;background:white}
.spectrum-legend{display:flex;gap:14px;flex-wrap:wrap;font:13px/1.4 system-ui}.spectrum-key{display:inline-block;width:20px;border-top:3px solid;vertical-align:middle;margin-right:6px}
.spectrum-note,.spectrum-account{font:12px/1.5 system-ui;margin:8px 0;overflow-wrap:anywhere}.spectrum-panel details{font:13px/1.4 system-ui;margin-top:9px}
.spectrum-table{max-height:260px;overflow:auto}.spectrum-table table{width:100%;border-collapse:collapse}.spectrum-table th,.spectrum-table td{padding:5px;text-align:right;border-bottom:1px solid #ddd}
@media(max-width:600px){.spectrum-panel .spectrum-chart{font-size:20px}.spectrum-panel{padding:9px}.spectrum-controls button{flex:0 1 auto}.spectrum-legend{gap:7px}}
'''

def panel(spec,compact=False):
    validate_spec(spec); esc=html.escape
    payload=json.dumps(spec,ensure_ascii=True,separators=(',',':'),allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    legend=''.join(f'<span><i class="spectrum-key" style="border-color:{esc(s["color"],quote=True)};border-top-style:{"dashed" if i else "solid"}"></i>{esc(s["label"])}</span>' for i,s in enumerate(spec['series']))
    notes=' '.join(accounting(spec))
    account=f'<p class="spectrum-account">{esc(notes)}</p>'
    qualifier='Saved engineering simulation; not experimental calibration.'
    note=qualifier if compact else spec['note']+' Zero-count bins are gaps on log axes; no pseudocounts, smoothing or normalization.'
    detail=('<details hidden><summary>Exact counts and accounting</summary>'+(account if compact else '')+
            '<div class="spectrum-table"></div></details>')
    return (f'<figure class="spectrum-panel" data-spectrum-key="{esc(spec["key"])}" data-scale="log">'
            f'<figcaption>{esc(spec["title"])}</figcaption><div class="spectrum-controls" role="group" aria-label="Vertical count scale">'
            '<span>Y scale</span><button type="button" data-scale="log" aria-pressed="true" disabled>Log</button><button type="button" data-scale="linear" aria-pressed="false" disabled>Linear</button></div>'
            f'<div class="spectrum-legend">{legend}</div>{svg(spec)}'
            f'<p class="spectrum-note">{esc(note)}</p>'+(account if not compact else '')+detail+
            '<noscript><p class="spectrum-note">Static logarithmic spectrum. JavaScript enables the scale controls and exact-bin table; saved numerical downloads remain linked in the full reports.</p></noscript>'
            f'<script type="application/json" class="spectrum-data">{payload}</script></figure>')

def assets():
    script=(ROOT/'tools/spectrum_controls.js').read_text(encoding='utf-8')
    return '<style id="spectrum-style">'+STYLE+'</style><script id="spectrum-controls-script">'+script+'</script>'
