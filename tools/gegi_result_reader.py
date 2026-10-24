"""Bounded read-only views of sealed GeGI results.json, without bulk JSON load.

One sequential scan binds the original bytes and indexes exact event/imaging
ranges. Subsequent requests parse only one selected range. This is a reader for
the existing GeGI result object, not a new scientific storage format.
"""
import hashlib
import json
from pathlib import Path
import re
import stat

import scenario_workflow as W

BLOCK = 64 * 1024
MAX_HEADER = 2 * 1024 * 1024
MAX_PART = 64 * 1024 * 1024
HEADER = {'kind','status','configuration_sha256','counts','channels','limitations',
          'depth_calibration','reconstruction_algorithm','signal_use_counts'}
EVENT_INDEX = {'event_id','status','truth_edep_keV'}
STRUCTURE = re.compile(rb'["\\{}\[\]]')
SCALAR_END = re.compile(rb'[\s,}\]]')
NONSPACE = re.compile(rb'\S')


def file_state(path):
    path=Path(path).absolute()
    for item in (path,*path.parents):
        value=item.lstat()
        W.require(not item.is_symlink() and not
                  (getattr(value,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT),
                  'Linked saved GeGI result path refused.')
    s=path.stat()
    return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)


class _Scan:
    def __init__(self,stream):
        self.stream=stream;self.buffer=b'';self.index=0;self.offset=0
        self.hashes=[hashlib.sha256()];self.peak_buffer_bytes=0

    def ready(self):
        if self.index==len(self.buffer):
            self.buffer=self.stream.read(BLOCK);self.index=0
            self.peak_buffer_bytes=max(self.peak_buffer_bytes,len(self.buffer))
        return bool(self.buffer)

    def take(self,count):
        body=self.buffer[self.index:self.index+count]
        for digest in self.hashes:digest.update(body)
        self.index+=count;self.offset+=count
        return body

    def peek(self):
        W.require(self.ready(),'Truncated saved GeGI JSON.')
        return self.buffer[self.index]

    def space(self):
        while self.ready():
            match=NONSPACE.search(self.buffer,self.index)
            self.take((match.start() if match else len(self.buffer))-self.index)
            if match:return

    def expect(self,char):
        self.space();W.require(self.peek()==ord(char),'Unexpected saved GeGI JSON structure.')
        self.take(1)

    def value(self,limit=None):
        self.space();start=self.offset;digest=hashlib.sha256();self.hashes.append(digest)
        parts=[];length=0
        def consume(count):
            nonlocal length
            body=self.take(count);length+=len(body)
            if limit is not None:
                W.require(length<=limit,'Saved GeGI metadata exceeds its bounded reader limit.')
                parts.append(body)
        first=self.peek()
        if first in (ord('{'),ord('['),ord('"')):
            stack=[];quoted=False
            while True:
                W.require(self.ready(),'Truncated saved GeGI value.')
                match=STRUCTURE.search(self.buffer,self.index)
                if match is None:
                    consume(len(self.buffer)-self.index);continue
                char=self.buffer[match.start()];consume(match.start()-self.index+1)
                if quoted:
                    if char==ord('\\'):
                        W.require(self.ready(),'Truncated saved GeGI string escape.');consume(1)
                    elif char==ord('"'):
                        quoted=False
                        if not stack:break
                elif char==ord('"'):quoted=True
                elif char in (ord('{'),ord('[')):stack.append(ord('}') if char==ord('{') else ord(']'))
                elif char in (ord('}'),ord(']')):
                    W.require(stack and stack.pop()==char,'Mismatched saved GeGI JSON container.')
                    if not stack:break
        else:
            while self.ready():
                match=SCALAR_END.search(self.buffer,self.index)
                consume((match.start() if match else len(self.buffer))-self.index)
                if match:break
            W.require(length>0,'Empty saved GeGI JSON value.')
        self.hashes.pop()
        entry={'offset':start,'bytes':self.offset-start,'sha256':digest.hexdigest()}
        return entry,json.loads(b''.join(parts)) if limit is not None else None

    def members(self):
        self.expect('{');self.space()
        if self.peek()==ord('}'):self.take(1);return
        seen=set()
        while True:
            _,key=self.value(512)
            W.require(type(key) is str and key not in seen,'Duplicate or invalid saved GeGI object key.')
            seen.add(key);self.expect(':');yield key
            self.space();char=self.peek();self.take(1)
            if char==ord('}'):return
            W.require(char==ord(','),'Invalid saved GeGI object separator.')


def scan(path,expected_sha256):
    """Hash every original byte; retain only small headers and event identities."""
    path=Path(path);before=file_state(path);header={};events=[];imaging=None
    with path.open('rb') as stream:
        reader=_Scan(stream)
        for key in reader.members():
            if key=='events':
                reader.expect('[');reader.space()
                if reader.peek()==ord(']'):reader.take(1);continue
                while True:
                    reader.space();start=reader.offset;digest=hashlib.sha256();reader.hashes.append(digest)
                    meta={}
                    for field in reader.members():
                        _,value=reader.value(MAX_HEADER if field in EVENT_INDEX else None)
                        if field in EVENT_INDEX:meta[field]=value
                    reader.hashes.pop()
                    W.require(type(meta.get('event_id')) is int and meta['event_id']>=0 and
                              type(meta.get('status')) is str and type(meta.get('truth_edep_keV')) in (int,float),
                              'Invalid saved GeGI event index identity.')
                    events.append({'metadata':meta,'offset':start,'bytes':reader.offset-start,'sha256':digest.hexdigest()})
                    reader.space();char=reader.peek();reader.take(1)
                    if char==ord(']'):break
                    W.require(char==ord(','),'Invalid saved GeGI event array separator.')
            else:
                entry,value=reader.value(MAX_HEADER if key in HEADER else None)
                if key in HEADER:header[key]=value
                if key=='imaging':imaging=entry
        reader.space();W.require(not reader.ready(),'Trailing bytes after saved GeGI results.')
        W.require(reader.hashes[0].hexdigest()==expected_sha256,'Saved GeGI results differ from their completion seal.')
        peak=reader.peak_buffer_bytes
    W.require(file_state(path)==before,'Saved GeGI results changed while indexing.')
    counts=header.get('counts') or {};ids=[e['metadata']['event_id'] for e in events]
    W.require(header.get('kind')=='gegi_multichannel_results_v1' and
              header.get('status') in W.TERMINAL and
              [c['id'] for c in header.get('channels',[])]==list(range(1,35)) and
              counts.get('nonzero_primaries')==len(events) and len(set(ids))==len(ids) and
              counts.get('initial_primaries')==counts.get('zero_deposit_primaries',-1)+len(events) and
              all(i<counts['initial_primaries'] for i in ids),'Saved GeGI header or original event census changed.')
    return {'header':header,'events':events,'imaging':imaging,'source_state':before,
            'scan_bytes':before[2],'peak_scan_buffer_bytes':peak}


class Reader:
    def __init__(self,path,expected_sha256,*,name,configuration_sha256,derivative=None,seal_paths=()):
        self.path=Path(path);self.sha256=expected_sha256
        self.identity={'name':name,'configuration_sha256':configuration_sha256,
                       'saved_derivative_name':derivative,'results_sha256':expected_sha256}
        self.seals={Path(p):W.sha(p) for p in seal_paths}
        self.index=scan(self.path,expected_sha256)
        W.require(self.index['header']['configuration_sha256']==configuration_sha256,
                  'Saved GeGI result configuration differs from the selected run.')
        self._events={e['metadata']['event_id']:e for e in self.index['events']}
        self.guard()

    def guard(self,expected_sha256=None):
        W.require(expected_sha256 is None or expected_sha256==self.sha256,
                  'The requested GeGI result version differs from the opened summary.')
        W.require(file_state(self.path)==self.index['source_state'] and
                  all(W.sha(path)==digest for path,digest in self.seals.items()),
                  'Saved GeGI source or completion seal changed. Preserve it for inspection and reopen Control.')

    def summary(self,expected_sha256=None):
        self.guard(expected_sha256)
        return {**self.index['header'],**self.identity,'kind':'gegi_multichannel_summary_v1',
                'result_kind':'gegi_multichannel_results_v1',
                'event_index':[e['metadata'] for e in self.index['events']],
                'imaging_available':self.index['imaging'] is not None}

    def _part(self,entry):
        W.require(entry['bytes']<=MAX_PART,'Selected GeGI record exceeds the 64 MiB viewer limit; use its original local file.')
        with self.path.open('rb') as stream:stream.seek(entry['offset']);body=stream.read(entry['bytes'])
        W.require(len(body)==entry['bytes'] and hashlib.sha256(body).hexdigest()==entry['sha256'],
                  'Selected saved GeGI bytes changed.')
        value=json.loads(body);self.guard()
        return value

    def event(self,event_id,expected_sha256=None):
        self.guard(expected_sha256)
        W.require(type(event_id) is int and event_id in self._events,'The original GeGI event ID is not in this saved result.')
        value=self._part(self._events[event_id])
        W.require(value['event_id']==event_id,'Selected saved GeGI event identity changed.')
        return {**self.identity,'kind':'gegi_multichannel_event_v1','event_id':event_id,'event':value}

    def imaging(self,expected_sha256=None):
        self.guard(expected_sha256)
        W.require(self.index['imaging'] is not None,'This saved GeGI result contains no imaging record.')
        return {**self.identity,'kind':'gegi_multichannel_imaging_v1','imaging':self._part(self.index['imaging'])}
