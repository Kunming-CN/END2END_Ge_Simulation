"""Homepage previews copied from saved artifacts, without numerical regeneration."""
import re
from pathlib import Path

def add_previews(site, home):
    site=Path(site)
    choices=(('Start here','detectors/AK02/runs/20260922_suite_v3/comparisons/04_electronics.png',
              'Saved SSD gallery electronics example; separate from the source campaign'),
             ('Explore detectors','detectors/AK02/runs/20260922_suite_v3/01_geometry.png',
              'Saved detector geometry; all 17 models have individual pages'))
    for title,relative,caption in choices:
        if (site/relative).is_file():
            preview=f'<figure class="preview"><img loading="lazy" src="{relative}" alt="{caption}"><figcaption>{caption}</figcaption></figure>'
            token='<h2>'+title+'</h2>'
            home=home.replace(token,token+preview,1)
    report=site/'examples/cs137-1m-response/report.html'
    from spectrum_display import homepage_preview
    current=homepage_preview(site)
    if current is not None:
        home=home.replace('<h2>Results</h2>','<h2>Results</h2><div class="preview">'+current+'</div>',1)
    elif report.is_file():
        saved=report.read_text(encoding='utf-8')
        charts=re.findall(r'<svg\b[^>]*>.*?</svg>',saved,flags=re.S)
        if charts and not re.search(r'<script|foreignObject|\bid=',charts[0],re.I):
            legends=re.findall(r'<p class="legend">.*?</p>',saved,flags=re.S)
            headings=re.findall(r'<h3>(.*?)</h3>',saved[:saved.find('<svg')],flags=re.S)
            context=(headings[-1] if headings else 'Saved response')+' — engineering simulation, not experimental calibration.'
            preview='<figure class="preview">'+charts[0]+'<figcaption>'+context+(legends[0] if legends else '')+'</figcaption></figure>'
            home=home.replace('<h2>Results</h2>','<h2>Results</h2>'+preview,1)
    legacy='<details class="panel"><summary>Earlier examples and compatible links</summary><p id="pipeline-example"><a href="examples/pipeline.html">Compact engineering example</a></p>'
    if (site/'examples/cs137-10k/comparison.html').is_file():
        legacy+='<p id="native-cs137-10k"><a href="results/cs137-10k/index.html">Earlier 10k campaign</a></p>'
    return action_first(home)+legacy+'</details>'

def action_first(home):
    """DOM order, not CSS-only order, keeps mobile and keyboard routes aligned."""
    def move(match):
        card=match.group(0)
        action=re.search(r'<a\s+href="[^"]+"[^>]*>.*?</a>',card,flags=re.S)
        heading=re.search(r'<h2>.*?</h2>',card,flags=re.S)
        if not action or not heading:
            return card
        anchor=action.group(0)
        card=card[:action.start()]+card[action.end():]
        return card.replace(heading.group(0),heading.group(0)+'<p class="card-action">'+anchor+'</p>',1)
    return re.sub(r'<article class="card">.*?</article>',move,home,flags=re.S)
