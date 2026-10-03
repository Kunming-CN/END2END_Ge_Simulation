"""Saved SVG projection tests; no native/transport/readout invocation."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import saved_waveforms as P
import local_ui_workflow_jobs as J
import scenario_workflow as W


def svg(caption,namespace=''):
    return "<svg role='img' aria-label='"+caption+"' viewBox='0 0 600 205'"+namespace+"><path d='M55 30 V165 H565' fill='none' stroke='#888'/><polyline points='55,160 565,35' fill='none' stroke='currentColor' stroke-width='1.7'/><text x='5' y='35'>-0.003</text><text x='415' y='192'>1.0e4 ns</text></svg>"


def record(primary=2,group='0',namespace=''):
    figures=''.join('<figure><figcaption>'+caption+'</figcaption>'+svg(caption,namespace)+'</figure>' for caption in P.CAPTIONS)
    return '<details><summary>Event '+str(primary)+' / group '+group+'</summary>'+figures+'<p>Bounded display samples; current belongs to the original intervals in traces.jsonl.</p></details>'


def projected(body):return P.project(body.encode(),'owned','a'*64,2,0)


class Projection(unittest.TestCase):
    def test_original_fragments_captions_signed_numeric_strings_and_hash_exact(self):
        body='<!doctype html><title>Saved</title>'+record()
        value=projected(body)
        self.assertEqual(value['figures'],[{'caption':caption,'svg':svg(caption)} for caption in P.CAPTIONS])
        self.assertEqual(value['summary_sha256'],hashlib.sha256(body.encode()).hexdigest())
        self.assertEqual((value['name'],value['configuration_sha256'],value['primary_id'],value['group_id']),('owned','a'*64,2,0))
        self.assertIn('original intervals',value['notes'][0]);self.assertEqual(value['science_calls'],0)

    def test_none_is_distinct_from_zero_and_no_fallback_identity(self):
        body=(record(2,'nothing')+record(3,'0')).encode()
        self.assertIsNone(P.project(body,'owned','a'*64,2,None)['group_id'])
        for primary,group in ((2,0),(3,None),(99,0),(3,2)):
            with self.subTest(identity=(primary,group)),self.assertRaises(W.ControlError):P.project(body,'owned','a'*64,primary,group)

    def test_fixed_standard_namespace_is_preserved(self):
        body=record(namespace=" xmlns='"+P.SVG_NS+"'")
        self.assertEqual(projected(body)['figures'][0]['svg'],svg(P.CAPTIONS[0]," xmlns='"+P.SVG_NS+"'"))

    def test_unsafe_svg_and_rehashed_markup_reject(self):
        original=record()
        mutants=[original.replace("<path ","<path onload='alert(1)' ",1),
                 original.replace("<path ","<path style='fill:url(https://evil.example)' ",1),
                 original.replace("<path ","<path href='https://evil.example' ",1),
                 original.replace("<path ","<path xlink:href='x' ",1),
                 original.replace('<path ',"<path xmlns:x='https://evil.example' ",1),
                 original.replace('<svg ',"<svg xmlns='https://evil.example' ",1),
                 original.replace('<svg ',"<s:svg xmlns:s='"+P.SVG_NS+"' ",1).replace('</svg>','</s:svg>',1),
                 original.replace('<path ',"<foreignObject/><path ",1),
                 original.replace('<path ',"<script>alert(1)</script><path ",1),
                 original.replace('<path ',"<style>svg{fill:url(x)}</style><path ",1),
                 original.replace('<path ',"<a href='x'/><path ",1),
                 original.replace("stroke='#888'","stroke='url(https://evil.example)'",1),
                 original.replace("55,160 565,35","NaN,160 565,35",1),
                 original.replace("55,160 565,35","1e999,160 565,35",1),
                 original.replace('<text ','<TEXT ',1).replace('</text>','</TEXT>',1),
                 '<script>alert(1)</script>'+original,
                 original.replace('<svg ','<svg <?unsafe x?> ',1),
                 original.replace('<path ',"<!DOCTYPE svg [<!ENTITY x SYSTEM 'file:///x'>]><path ",1)]
        for body in mutants:
            with self.subTest(hash=hashlib.sha256(body.encode()).hexdigest()),self.assertRaises(W.ControlError):projected(body)

    def test_duplicate_malformed_partial_identity_and_wrong_figure_count_reject(self):
        original=record()
        mutants=[original+original,original.replace('Event 2 / group 0','Event 02 / group 0'),
                 original.replace('Event 2 / group 0','Event 2 / group none'),
                 original.replace('Event 2 / group 0','Event 2 / group -1'),
                 original.replace('</details>',''),original.replace('</svg>','',1),
                 original.replace("viewBox='0 0 600 205'","viewBox='0 0 600 205' viewBox='1 2 3 4'",1),
                 original.replace('<figure>','<figure><figure>',1),
                 original.replace('Charge (fC)','Wrong charge',1),
                 original.replace('<p>','<figure><figcaption>Extra</figcaption>'+svg('Extra')+'</figure><p>',1)]
        for body in mutants:
            with self.subTest(body=body[:80]),self.assertRaises(W.ControlError):projected(body)

    def test_typed_identity_refuses_bool_negative_unknown_or_partial(self):
        for primary,group in ((True,0),(2,False),(-1,None),(2,-1),(2,'none')):
            with self.subTest(identity=(primary,group)),self.assertRaises(W.ControlError):P.project(record().encode(),'owned','a'*64,primary,group)

    def test_actual_completed_summary_projects_all_twenty_exact_records(self):
        directory=W.ROOT/'.local/runs/m14a-gamma-ui-03'
        if not directory.exists():self.skipTest('Optional owner-local completed artifact absent in clean clone')
        body=(directory/'response/summary.html').read_bytes();before=hashlib.sha256(body).hexdigest()
        traces=[json.loads(line) for line in (directory/'response/traces.jsonl').read_text().splitlines()]
        self.assertEqual(len(traces),20)
        for trace in traces:
            value=P.project(body,'actual-saved','a'*64,trace['event_id'],trace['group_id'])
            self.assertEqual(len(value['figures']),4);self.assertEqual(value['summary_sha256'],before)
            for figure in value['figures']:self.assertIn(figure['svg'].encode(),body)
        self.assertEqual((directory/'response/summary.html').read_bytes(),body)

    def test_controller_requires_terminal_artifact_validation_before_projection(self):
        base=W.ROOT/'.local/product-delivery-v1/implementation-tests';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as folder:
            controller=J.WorkflowController(Path(folder));body=record().encode()
            job={'id':'a'*32,'name':'owned','status':'completed','created_utc':'synthetic',
                 'plan':{'configuration_sha256':'a'*64,'resolved':{'selection':{'name':'owned'}}}}
            controller._jobs=[job];directory=W.run_path('owned',Path(folder));(directory/'response').mkdir(parents=True)
            (directory/'response/summary.html').write_bytes(body)
            W.write(directory/'COMPLETE.json',{'artifacts':{'response/summary.html':{'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body)}}},fresh=True)
            with patch.object(W,'inspect',side_effect=W.ControlError('Changed artifact')) as inspect,patch.object(P,'project') as project:
                with self.assertRaises(W.ControlError):controller.waveforms('owned',2,0)
                inspect.assert_called_once();project.assert_not_called()
            malicious=body.replace(b'<path ',b"<path onload='alert(1)' ",1)
            (directory/'response/summary.html').write_bytes(malicious)
            W.write(directory/'COMPLETE.json',{'artifacts':{'response/summary.html':{'sha256':hashlib.sha256(malicious).hexdigest(),'bytes':len(malicious)}}})
            with patch.object(W,'inspect',return_value={}) as inspect,self.assertRaises(W.ControlError):controller.waveforms('owned',2,0)
            inspect.assert_called_once()
            job['status']='dispatch_uncertain'
            with patch.object(W,'inspect') as inspect,self.assertRaises(W.ControlError):controller.waveforms('owned',2,0)
            inspect.assert_not_called()


if __name__=='__main__':unittest.main()
