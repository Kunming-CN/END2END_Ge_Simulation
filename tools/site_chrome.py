"""Shared document frame over retained historical HTML; scientific assets stay exact."""
import re
from site_routes import page_navigation, relative_url

STYLE = '''
body.site-document{margin:0!important;padding:24px!important;background:#f6f8fa!important;color:#173047!important;font:16px/1.6 system-ui!important;max-width:1440px!important;box-sizing:border-box;margin-inline:auto!important}
.site-document>main,.site-document>header{max-width:1180px;margin-inline:auto}
.site-document>header{background:transparent;color:#173047;padding:0}
.site-document h1{font-size:clamp(2rem,3vw,2.5rem);line-height:1.2}
.site-document p,.site-document li{max-width:90ch}.site-document a{color:#075e9b}
.site-document .archive-identity{padding:16px 20px;margin:16px 0 24px;border-left:4px solid #37718e;background:#e8f1f7;color:#173047}
.site-document img,.site-document iframe{max-width:100%}.site-document pre{white-space:pre-wrap;overflow-wrap:anywhere}
.site-document .site-table-scroll{overflow:auto}.site-document table{max-width:100%}
.site-document #page-navigation{max-width:1180px;margin-inline:auto}
.site-document #page-navigation a,.site-document #page-navigation span,.site-document #page-navigation li{color:#173047}
.site-document .small,.site-document .muted{color:#465e70}
.site-document button,.site-document select,.site-document input{background:#fff;color:#173047;border:1px solid #687d8e}
.site-document #status,.site-document #event-status{color:#173047}
.site-document .channels{grid-template-columns:repeat(auto-fit,minmax(80px,1fr))}
.site-document label,.site-document select{max-width:100%;min-width:0}
.site-document th{color:#173047}.site-document .note{background:#e8f1f7;color:#173047}
@media(max-width:760px){body.site-document{padding:12px!important}.site-document table{font-size:14px}}
'''


def frame_html(text, path):
    """Give immutable evidence a clear parent route without changing its content."""
    # Some legacy documents put navigation before their implicit body. Remove
    # that whole block before finding the first actual content element.
    text = re.sub(r'<!-- page-navigation:start -->.*?<!-- page-navigation:end -->', '', text, flags=re.S)
    if not re.search(r'<html\b',text,re.I):
        if re.search(r'<!doctype\b[^>]*>',text,re.I):
            text=re.sub(r'(<!doctype\b[^>]*>)',r'\1<html lang="en">',text,count=1,flags=re.I)
        else:
            text='<!doctype html><html lang="en">'+text
        if not re.search(r'</html>',text,re.I):
            text+='</html>'
    if not re.search(r'<body\b',text,re.I):
        start=re.search(r'<(?:header|h1|main|nav|section)\b',text,re.I)
        if start is None:
            raise ValueError('Saved report has no document content: '+path)
        head,body=text[:start.start()],text[start.start():]
        if not re.search(r'<head\b',head,re.I):
            head=re.sub(r'(<html\b[^>]*>)',r'\1<head>',head,count=1,flags=re.I)
        if '</head>' not in head.lower():
            head+='</head>'
        body=body.replace('</html>','</body></html>') if '</html>' in body else body+'</body></html>'
        text=head+'<body>'+body
    text = re.sub(r'<style id="shared-document-frame">.*?</style>', '', text, flags=re.S)
    text = re.sub(r'<aside class="archive-identity">.*?</aside>', '', text, flags=re.S)
    text = re.sub(r'(<body\b[^>]*)(>)', lambda m: (
        m[1] if 'class=' in m[1] else m[1]+' class="site-document"')+m[2], text, count=1, flags=re.I)
    # Saved reports with a pre-existing class retain it as well.
    text = re.sub(r'(<body\b[^>]*class=")([^"]*)(")',
                  lambda m:m[1]+('site-document ' if 'site-document' not in m[2].split() else '')+m[2]+m[3],text,count=1,flags=re.I)
    note = ''
    if path.startswith('examples/'):
        note = ('<aside class="archive-identity"><strong>Original saved evidence</strong><p>'
                'This report preserves its original study conditions and recorded outcomes. '
                'Use the breadcrumb to return to the maintained study and its current views.</p></aside>')
    frame = '<style id="shared-document-frame">'+STYLE+'</style>'+page_navigation(path)+note
    return re.sub(r'(<body\b[^>]*>)',lambda m:m[1]+frame,text,count=1,flags=re.I)


def assembly_html(text, path):
    """Put the saved assembly canvas before its optional radiation controls."""
    text = re.sub(r'<style>#page-navigation\{.*?</style>','',text,count=1,flags=re.S)
    start = text.find('<p>The four built-in samples')
    end = text.find('<div class="bar" aria-label="Camera controls">')
    destination = '<details id="event-record-panel">'
    if start >= 0 and end > start and destination in text:
        controls = '<section id="saved-radiation-samples"><h2>Saved radiation samples</h2>'+text[start:end]+'</section>'
        text = text[:start]+text[end:]
        text = text.replace(destination,controls+destination,1)
    text = text.replace('<h2>Geometry and saved radiation steps</h2>','<h2>Three-dimensional geometry</h2>')
    measured = re.search(r'<p class="note"><strong>Measured front layers; nominal enclosure.</strong>.*?</p>',text,re.S)
    if measured:
        text=text[:measured.start()]+text[measured.end():]
        text=text.replace('<h2>Dimensions and assumptions</h2>','<h2>Dimensions and assumptions</h2>'+measured[0],1)
    return frame_html(text,path)
