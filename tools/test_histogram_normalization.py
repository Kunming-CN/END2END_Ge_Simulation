"""Synthetic source/merge/export contracts; no radiation, SSD or electronics."""
import copy, csv, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import batch_execution as E
import decay_workflow as D
import histogram_normalization as H
import scenario_workflow as W

class Normalization(unittest.TestCase):
    def setUp(self):
        base=W.ROOT/'.local/strict02-normalization-v1/implementation/test-work'
        base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.native={'simulation/native_response.jl':W.sha(W.ROOT/'simulation/native_response.jl')}
        self.merge={'tools/batch_execution.py':W.sha(W.ROOT/'tools/batch_execution.py')}
        self.oldnative={'simulation/native_response.jl':H.LEGACY_NATIVE_SHA256}
        self.oldmerge={'tools/batch_execution.py':H.LEGACY_MERGE_SHA256}

    def counts(self,source,n=5,line=7,accepted=2):
        value=dict(initial_primaries=n,initial_decays=n,zero_deposit_primaries=n-2,
            groups=2,accepted=accepted,rejected=2-accepted,native_failed_groups=2-accepted,
            readout_rejected=0,line_photons=line,decay_photons=line+1)
        if source!=W.CS:
            names=[v['name'] for v in D.preset(source)['diagnostic_lines']]
            value['line_photon_counts']={name:line if i==0 else 0 for i,name in enumerate(names)}
        return value

    def histogram(self,source,counts,legacy=False):
        normal=H.descriptor(source,None if source==W.CS else D.preset(source))
        key=H.LEGACY_KEY if normal is None or legacy else H.DIAGNOSTIC_KEY
        cases=[('accepted_peak_ADC',211,2),('deposited_per_decay',-1,1),
               ('deposited_per_decay',200,counts['initial_primaries']-2),('deposited_per_decay',1000,1)]
        bins=[H.row(stage,bin,n,counts,key) for stage,bin,n in cases if n>0]
        return H.attach(dict(width_keV=5,normalization_denominators=counts,bins=bins,note=H.NOTE),None if legacy else normal)

    def csv(self,path,h):
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=H.fields(h.get('normalization',{}).get('value_key',H.LEGACY_KEY)))
            writer.writeheader();writer.writerows(h['bins'])
        return path

    def checked(self,h,source,counts,pins=None,csv_path=None,merged=False):
        return H.validate(h,counts,source,None if source==W.CS else D.preset(source),
            pins or self.native,csv_path=csv_path,merged=merged)

    def test_three_registered_sources_have_exact_distinct_windows_and_values(self):
        expected={'am241_point_decay_v1':[[59,60]],'ba133_point_decay_v1':[[80,82],[355,357]],
                  'co60_point_decay_v1':[[1172,1175],[1331,1334]]}
        for source,windows in expected.items():
            with self.subTest(source=source):
                counts=self.counts(source);h=self.histogram(source,counts)
                check=self.checked(h,source,counts,csv_path=self.csv(self.root/(source+'.csv'),h))
                self.assertEqual(h['schema_version'],2)
                self.assertEqual([v['window_keV'] for v in h['normalization']['diagnostic_lines']],windows)
                self.assertEqual(h['normalization']['window_interval'],'closed [lower, upper] keV')
                self.assertEqual(h['normalization']['aggregation'],'sum_of_named_window_photon_counts')
                self.assertEqual(h['bins'][0][H.DIAGNOSTIC_KEY],2/7)
                self.assertNotIn(H.LEGACY_KEY,h['bins'][0]);self.assertIsNone(check['legacy_alias'])

    def test_zero_denominators_remain_null_in_json_and_empty_in_csv(self):
        source='am241_point_decay_v1';counts=self.counts(source,line=0,accepted=0)
        h=self.histogram(source,counts);path=self.csv(self.root/'zero.csv',h)
        self.checked(h,source,counts,csv_path=path)
        for row in h['bins']:
            self.assertIsNone(row[H.DIAGNOSTIC_KEY]);self.assertIsNone(row['per_accepted_pulse'])
        counts=self.counts(W.CS);counts.update(initial_decays=None,line_photons=None,accepted=0)
        h=self.histogram(W.CS,counts);self.checked(h,W.CS,counts,csv_path=self.csv(self.root/'unknown.csv',h))
        self.assertTrue(all(row['per_initial_decay'] is None and row[H.LEGACY_KEY] is None for row in h['bins']))

    def test_rehashed_descriptor_changes_and_missing_v2_descriptor_refused(self):
        source='co60_point_decay_v1';counts=self.counts(source);original=self.histogram(source,counts)
        W.write(self.root/'rehash.json',original);original_sha=W.sha(self.root/'rehash.json')
        edits=[lambda h:h['normalization'].update(source_id='ba133_point_decay_v1'),
               lambda h:h['normalization']['diagnostic_lines'][0]['window_keV'].__setitem__(0,660),
               lambda h:h['normalization']['diagnostic_lines'].pop(),
               lambda h:h['normalization'].update(window_interval='[lower, upper)'),
               lambda h:h['normalization'].update(aggregation='union_of_windows'),
               lambda h:h['normalization'].update(denominator_count_key='initial_decays'),
               lambda h:h['normalization'].update(source_registry_sha256='0'*64),
               lambda h:h['normalization'].update(schema_version=True),
               lambda h:h.pop('normalization'),lambda h:h.update(schema_version=True)]
        for edit in edits:
            h=copy.deepcopy(original);edit(h);W.write(self.root/'rehash.json',h)
            self.assertNotEqual(W.sha(self.root/'rehash.json'),original_sha)
            with self.assertRaises(W.ControlError):self.checked(W.read(self.root/'rehash.json'),source,counts)
        changed=D.preset(source).copy();changed['diagnostic_lines']=D.preset('ba133_point_decay_v1')['diagnostic_lines']
        with self.assertRaises(W.ControlError):H.descriptor(source,changed)
        counts['line_photon_counts'][next(iter(counts['line_photon_counts']))]+=1
        with self.assertRaises(W.ControlError):self.checked(self.histogram(source,counts),source,counts)

    def test_csv_column_numeric_and_null_tampering_refused_after_rehash(self):
        source='am241_point_decay_v1';counts=self.counts(source);h=self.histogram(source,counts)
        path=self.csv(self.root/'changed.csv',h);original=path.read_text()
        for changed in (original.replace(H.DIAGNOSTIC_KEY,H.LEGACY_KEY),
                        original.replace(str(2/7),'0.5',1),original.replace('accepted_peak_ADC','native_terminal_charge',1)):
            path.write_text(changed);W.sha(path)
            with self.assertRaises(W.ControlError):self.checked(h,source,counts,csv_path=path)
        counts=self.counts(source,line=0);h=self.histogram(source,counts);self.csv(path,h)
        cells=list(csv.reader(path.open(newline='')));cells[1][7]='0'
        with path.open('w',newline='') as stream:csv.writer(stream).writerows(cells)
        with self.assertRaises(W.ControlError):self.checked(h,source,counts,csv_path=path)

    def test_historical_alias_requires_recorded_exporter_and_matching_source(self):
        source='ba133_point_decay_v1';counts=self.counts(source);h=self.histogram(source,counts,legacy=True)
        before=W.encoded(h);check=self.checked(h,source,counts,self.oldnative)
        self.assertEqual(check['legacy_alias']['interpreted_key'],H.DIAGNOSTIC_KEY)
        self.assertEqual(check['normalization']['source_id'],source);self.assertEqual(W.encoded(h),before)
        for pins in (self.native,{},dict(self.oldnative,**{'native_response.jl':'f'*64})):
            with self.assertRaises(W.ControlError):H.validate(h,counts,source,D.preset(source),pins)
        with self.assertRaises(W.ControlError):self.checked(self.histogram(source,counts),source,counts,self.oldnative)

    def batches(self,source,legacy=False,legacy_parent=False):
        part=E.partition(5,42,3);contract=None if source==W.CS else D.preset(source)
        r=dict(selection=dict(name='export',detector='AK02',source=source,primary_count=5),batching=part,
               source_sha256=self.oldmerge if legacy_parent else self.merge)
        if contract is not None:r['decay_source_contract']=contract
        plan=dict(resolved=r,configuration_sha256=W.digest(r));total={}
        for batch in E.iter_batches(part):
            base=E.batch_directory(self.root,batch['batch_index']);(base/'response').mkdir(parents=True)
            (base/'batch-complete.json').write_text('{}')
            counts=self.counts(source,n=batch['primary_count'],line=7+batch['batch_index'])
            counts['zero_deposit_primaries']=batch['primary_count']-2
            h=self.histogram(source,counts,legacy=legacy)
            W.write(base/'response/histograms.json',h);self.csv(base/'response/histograms.csv',h)
            W.write(base/'response/run.json',dict(counts=counts,source_id=source,source_contract=contract,
                source_sha256=self.oldnative if legacy else self.native))
            E.add_counts(total,counts)
        return plan,total

    def test_new_merge_interprets_legacy_batches_and_preserves_exact_integer_counts(self):
        for source in ('am241_point_decay_v1','ba133_point_decay_v1','co60_point_decay_v1'):
            with self.subTest(source=source),tempfile.TemporaryDirectory(dir=self.root) as leaf:
                previous=self.root;self.root=Path(leaf)
                try:
                    plan,counts=self.batches(source,legacy=True)
                    preserved={p:W.sha(p) for p in self.root.rglob('*') if p.is_file()}
                    prefix=dict(completed_batch_count=2,completed_primary_count=5,counts=counts,batch_receipt_chain_sha256='d'*64)
                    with patch.object(E,'checked_prefix',return_value=prefix):result=E.export_results(plan,self.root)
                    merged=W.read(self.root/'results/histograms.json')
                    self.checked(merged,source,counts,self.merge,self.root/'results/histograms.csv',merged=True)
                    self.assertEqual(merged['normalization_denominators'],counts)
                    self.assertEqual(merged['bins'][0]['count'],4)
                    self.assertEqual(merged['bins'][0][H.DIAGNOSTIC_KEY],4/15)
                    self.assertTrue(all(W.sha(p)==digest for p,digest in preserved.items()))
                    with patch.object(E,'checked_prefix',return_value=prefix):E.validate_output('results',plan,self.root,None,result)
                finally:self.root=previous

    def test_old_merged_results_validate_without_upgrading_saved_bytes(self):
        source='co60_point_decay_v1';plan,counts=self.batches(source,legacy=True,legacy_parent=True)
        base=self.root/'results';base.mkdir()
        h=E.aggregate_histograms(plan,self.root,counts,legacy_output=True)
        W.write(base/'histograms.json',h);self.csv(base/'histograms.csv',h)
        prefix=dict(completed_batch_count=2,completed_primary_count=5,counts=counts,batch_receipt_chain_sha256='d'*64)
        result=dict(kind='batch_parent_results_v1',status='complete',configuration_sha256=plan['configuration_sha256'],
                    **prefix,artifacts={name:W.sha(base/name) for name in ('histograms.json','histograms.csv')})
        before={p:W.sha(p) for p in base.iterdir()}
        with patch.object(E,'checked_prefix',return_value=prefix):E.validate_output('results',plan,self.root,None,result)
        self.assertTrue(all(W.sha(p)==digest for p,digest in before.items()));self.assertNotIn('schema_version',h)

    def test_cs137_default_merge_contract_preserved(self):
        plan,counts=self.batches(W.CS);h=E.aggregate_histograms(plan,self.root,counts)
        self.assertEqual(set(h),{'bins','width_keV','normalization_denominators','note'})
        self.assertIn(H.LEGACY_KEY,h['bins'][0]);self.assertNotIn(H.DIAGNOSTIC_KEY,h['bins'][0])
        self.assertEqual(h['bins'][0][H.LEGACY_KEY],4/15)

    def test_generic_stage_to_parent_injected_execution_retains_zeros_and_failures(self):
        from test_batch_execution import Execution
        for source in ('am241_point_decay_v1','ba133_point_decay_v1','co60_point_decay_v1'):
            with self.subTest(source=source):
                fixture=Execution();fixture.setUp()
                try:
                    fixture.plan=fixture.check(dict(fixture.selection,source=source))
                    original_rows=fixture.rows
                    def rows(batch):
                        for event in original_rows(batch):
                            event['line_photon_counts']={x['name']:1 if i==0 else 0
                                for i,x in enumerate(D.preset(source)['diagnostic_lines'])}
                            yield event
                    fixture.rows=rows
                    def worker(stage,plan,directory,batch,root):
                        result=fixture.worker(stage,plan,directory,batch,root)
                        if stage!='response':return result
                        base=E.stage_base(directory,stage,batch);contract=D.preset(source)
                        counts=result['counts'];counts['line_photon_counts']={x['name']:counts['line_photons'] if i==0 else 0
                            for i,x in enumerate(contract['diagnostic_lines'])}
                        h=W.read(base/'histograms.json');h['normalization_denominators']=counts
                        h['bins']=[H.row(r['stage'],r['bin'],r['count'],counts,H.DIAGNOSTIC_KEY) for r in h['bins']]
                        H.attach(h,H.descriptor(source,contract));W.write(base/'histograms.json',h);self.csv(base/'histograms.csv',h)
                        result.update(source_id=source,source_contract=contract)
                        result['artifacts']={name:W.sha(base/name) for name in (*result['artifacts'],'histograms.csv')}
                        W.write(base/'run.json',result);return result
                    result=fixture.execute(worker=worker)
                    self.assertEqual(result['status'],'completed_with_native_failures')
                    self.assertEqual(result['counts']['initial_primaries'],3)
                    self.assertEqual(result['counts']['zero_deposit_primaries'],1)
                    self.assertEqual(result['counts']['native_failed_groups'],1)
                    saved=E.inspect('fixture',fixture.root)
                    self.assertEqual(saved['histogram_normalization_interpretation']['histogram_schema_version'],2)
                    self.assertEqual(saved['histogram_normalization_interpretation']['normalization']['source_id'],source)
                finally:fixture.doCleanups()

if __name__=='__main__':unittest.main()
