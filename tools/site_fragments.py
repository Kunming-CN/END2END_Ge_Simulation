"""Small structural edits for generated HTML; preserve unrelated bytes."""
from html.parser import HTMLParser

def remove_sections(text, identifiers):
    """Remove complete managed sections by parsed ID, regardless of quote/attribute order."""
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1]+len(line))
    class Sections(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.depth=0
            self.start=None
            self.ranges=[]
        def position(self):
            line, col=self.getpos()
            return offsets[line-1]+col
        def handle_starttag(self,tag,attrs):
            if tag=='section':
                if self.start is None and dict(attrs).get('id') in identifiers:
                    self.start=self.position()
                    self.start_depth=self.depth
                self.depth+=1
        def handle_endtag(self,tag):
            if tag=='section':
                self.depth-=1
                if self.start is not None and self.depth==self.start_depth:
                    end=text.find('>',self.position())+1
                    self.ranges.append((self.start,end))
                    self.start=None
    parser=Sections()
    parser.feed(text)
    if parser.start is not None:
        raise ValueError('Unclosed managed HTML section')
    for start,end in reversed(parser.ranges):
        text=text[:start]+text[end:]
    return text

def ids(text):
    class IDs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.items=[]
        def handle_starttag(self,tag,attrs):
            value=dict(attrs).get('id')
            if value is not None:
                self.items.append(value)
    parser=IDs()
    parser.feed(text)
    return parser.items

def prepend_main(text, fragment):
    import re
    openings=list(re.finditer(r'<main\b[^>]*>',text))
    if len(openings)!=1:
        raise ValueError('Expected one detector main element')
    end=openings[0].end()
    return text[:end]+fragment+text[end:]
