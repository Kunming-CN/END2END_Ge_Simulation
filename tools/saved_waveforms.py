"""Strict read-only projection of four original figures; no numerical plotting."""
import hashlib
from html import unescape
from html.parser import HTMLParser
import math
import re
from xml.etree import ElementTree

from local_ui_jobs import ControlError

SVG_NS='http://www.w3.org/2000/svg'
CAPTIONS=('Charge (fC)','Original-bin current (nA)','Analog preamp (V)','Analog shaper (V)')
ATTRIBUTES={'svg':{'role','aria-label','viewbox','xmlns'},'path':{'d','fill','stroke'},
            'polyline':{'points','fill','stroke','stroke-width'},'text':{'x','y'}}
NUMBER=r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
IDENTITY=re.compile(r'Event (0|[1-9]\d*) / group (nothing|0|[1-9]\d*)')


def require(condition,message='Unsupported saved waveform markup.'):
    if not condition:raise ControlError(message)


def numbers(value,count=None):
    parts=re.split(r'[\s,]+',value.strip())
    require(parts and (count is None or len(parts)==count) and all(
        re.fullmatch(NUMBER,x) and math.isfinite(float(x)) for x in parts))
    return parts


class Figures(HTMLParser):
    def __init__(self,text):
        super().__init__(convert_charrefs=False)
        self.text=text;self.offsets=[0]
        self.offsets.extend(match.end() for match in re.finditer('\n',text))
        self.record=None;self.stack=[];self.records={};self.capture=None;self.svg_start=None

    def source_offset(self):
        line,column=self.getpos();return self.offsets[line-1]+column

    def validate(self,tag,attrs):
        require(tag in ATTRIBUTES and len(attrs)==len({key for key,value in attrs}))
        values=dict(attrs);require(set(values)<=ATTRIBUTES[tag] and all(value is not None for value in values.values()))
        if 'xmlns' in values:require(tag=='svg' and values['xmlns']==SVG_NS)
        if tag=='svg':
            require(values.get('role')=='img' and values.get('aria-label')==self.record['figure']['caption'])
            numbers(values.get('viewbox',''),4)
        for key,value in values.items():
            if key in ('x','y','stroke-width'):numbers(value,1)
            elif key=='points':require(len(numbers(value))%2==0)
            elif key=='d':require(re.fullmatch(r'[MmLlHhVvZz0-9.,eE+\-\s]+',value) is not None)
            elif key=='fill':require(value=='none')
            elif key=='stroke':require(value in ('#888','currentColor'))

    def handle_starttag(self,tag,attrs):
        if tag=='details':
            require(self.record is None and not attrs,'Nested or attributed saved waveform record.')
            self.record={'identity':None,'figures':[],'notes':[]};self.stack=['details'];return
        if self.record is None:
            require(tag in ('html','head','body','meta','title','style','h1','p','pre','a'))
            return
        parent=self.stack[-1]
        if parent=='details':require(tag in ('summary','figure','p') and not attrs)
        elif parent=='figure':require(tag in ('figcaption','svg'))
        elif parent=='svg':require(tag in ('path','polyline','text'))
        else:require(False)
        if tag=='summary':require(self.record['identity'] is None);self.capture=[]
        elif tag=='figure':self.record['figure']={'caption':None,'svg':None}
        elif tag=='figcaption':
            require(not attrs and self.record['figure']['caption'] is None);self.capture=[]
        elif tag=='p':self.capture=[]
        elif tag=='svg':
            require(self.record['figure']['caption'] is not None and self.record['figure']['svg'] is None)
            self.validate(tag,attrs);self.svg_start=self.source_offset()
        elif tag in ATTRIBUTES:self.validate(tag,attrs)
        self.stack.append(tag)

    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if self.record is not None:self.finish(tag,self.source_offset()+len(self.get_starttag_text()))

    def finish(self,tag,end):
        require(self.stack and self.stack[-1]==tag,'Unbalanced saved waveform markup.')
        if tag=='summary':
            match=IDENTITY.fullmatch(''.join(self.capture));require(match is not None,'Malformed saved waveform identity.')
            identity=(int(match[1]),None if match[2]=='nothing' else int(match[2]))
            require(identity not in self.records,'Duplicate saved waveform identity.')
            self.record['identity']=identity;self.capture=None
        elif tag=='figcaption':self.record['figure']['caption']=''.join(self.capture);self.capture=None
        elif tag=='svg':
            fragment=self.text[self.svg_start:end]
            require(len(fragment.encode('utf-8'))<=2*1024*1024 and '<!' not in fragment and '<?' not in fragment)
            try:tree=ElementTree.fromstring(fragment)
            except ElementTree.ParseError as error:raise ControlError('Malformed saved SVG XML.') from error
            require(tree.tag in ('svg','{'+SVG_NS+'}svg'))
            require(all(element.tag in tuple(ATTRIBUTES)+tuple('{'+SVG_NS+'}'+name for name in ATTRIBUTES)
                        for element in tree.iter()))
            self.record['figure']['svg']=fragment;self.svg_start=None
        elif tag=='figure':
            figure=self.record.pop('figure');require(figure['caption'] is not None and figure['svg'] is not None)
            self.record['figures'].append(figure)
        elif tag=='p':self.record['notes'].append(''.join(self.capture));self.capture=None
        elif tag=='details':
            require(self.record['identity'] is not None and
                    [figure['caption'] for figure in self.record['figures']]==list(CAPTIONS),
                    'Saved waveform record must contain its four original figures.')
            self.records[self.record['identity']]=self.record;self.record=None
        self.stack.pop()

    def handle_endtag(self,tag):
        if self.record is not None:
            start=self.source_offset();end=self.text.find('>',start)
            require(end>=start);self.finish(tag,end+1)

    def handle_data(self,data):
        if self.record is None:return
        if self.capture is not None:self.capture.append(data)
        elif self.stack[-1]=='text':require(re.fullmatch(NUMBER+r'(?: ns)?',data) is not None)
        else:require(not data.strip())

    def handle_entityref(self,name):self.handle_data(unescape('&'+name+';'))
    def handle_charref(self,name):self.handle_data(unescape('&#'+name+';'))
    def handle_comment(self,data):require(self.record is None)
    def handle_decl(self,decl):require(self.record is None and decl.lower()=='doctype html')
    def handle_pi(self,data):require(False)
    def unknown_decl(self,data):require(False)


def project(body,name,configuration_sha256,primary_id,group_id):
    require(type(primary_id) is int and 0<=primary_id<=2147483646 and
            (group_id is None or type(group_id) is int and 0<=group_id<=2147483646),
            'Invalid exact waveform identity.')
    try:
        text=body.decode('utf-8');parser=Figures(text);parser.feed(text);parser.close()
    except (UnicodeError,ValueError,AssertionError) as error:raise ControlError('Malformed saved waveform document.') from error
    require(parser.record is None and not parser.stack,'Incomplete saved waveform record.')
    require((primary_id,group_id) in parser.records,'No saved waveform for this exact primary and group.')
    selected=parser.records[(primary_id,group_id)]
    return {'kind':'saved_waveform_projection_v1','name':name,'configuration_sha256':configuration_sha256,
            'primary_id':primary_id,'group_id':group_id,'summary_sha256':hashlib.sha256(body).hexdigest(),
            'figures':selected['figures'],'notes':selected['notes'],'science_calls':0}
