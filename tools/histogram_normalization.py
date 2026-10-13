"""Source-aware histogram semantics; saved scientific bytes are never rewritten.

The unversioned generic exporter used the Cs137 label for a different denominator.
Only its recorded, known exporter revision can use that historical alias. New
descriptors are reconstructed from the unchanged source registry, not trusted
because an artifact or descriptor has been rehashed.
"""
import copy, csv, math
from pathlib import Path
import scenario_workflow as W
from workflow_batches import typed_equal

LEGACY_KEY = 'per_emitted_660_663_keV_photon'
DIAGNOSTIC_KEY = 'per_emitted_diagnostic_window_photon'
LEGACY_NATIVE_SHA256 = '814417d83d696c0cac51f4cb39fd1fd461989e93e90ca9e0b3e12ea9f07b7077'
LEGACY_MERGE_SHA256 = 'bc8236cc487d61f2aa03e41de752ec5e002ac9b5a803ba90536bb8adb75a1157'
STAGES = {'deposited_per_decay','deposited_per_group','native_terminal_charge','window_charge',
          'preamp_charge_equivalent','analog_shaped_equivalent','accepted_peak_ADC'}
NOTE = 'Raw stage counts with distinct denominators, not efficiencies or physical resolution; Erec contains accepted pulses only.'


def descriptor(source_id, source_contract=None, root=W.ROOT):
    """None preserves the exact legacy Cs137/gamma export contract."""
    if source_id in (None, W.CS, W.GAMMA):
        return None
    from decay_workflow import preset, REGISTRY
    p = preset(source_id, root)
    W.require(source_contract is not None and typed_equal(source_contract, p),
              'Histogram source contract differs from the selected registry preset.')
    return {'kind':'source_diagnostic_photon_normalization_v1','schema_version':1,
            'source_id':source_id,'isotope':p['isotope'],'source_registry_ref':REGISTRY,
            'source_registry_sha256':W.sha(Path(root)/REGISTRY),
            'diagnostic_lines':copy.deepcopy(p['diagnostic_lines']),
            'window_interval':'closed [lower, upper] keV',
            'aggregation':'sum_of_named_window_photon_counts',
            'denominator_count_key':'line_photons','value_key':DIAGNOSTIC_KEY,
            'qualification':'diagnostic photon counts only; not branching intensity, activity or efficiency'}


def fields(value_key=LEGACY_KEY):
    return ('stage','bin','lower_keV','upper_keV','count','per_initial_primary',
            'per_initial_decay',value_key,'per_accepted_pulse')


def row(stage, bin, count, counts, value_key=LEGACY_KEY):
    ratio = lambda key: None if counts.get(key) in (None, 0) else count/counts[key]
    return {'stage':stage,'bin':bin,'lower_keV':None if bin==-1 else -1000+5*bin,
            'upper_keV':None if bin==1000 else -1000+5*(bin+1),'count':count,
            'per_initial_primary':ratio('initial_primaries'),'per_initial_decay':ratio('initial_decays'),
            value_key:ratio('line_photons'),'per_accepted_pulse':ratio('accepted')}


def legacy_authority(source_sha256, *, merged=False):
    pins = source_sha256 if type(source_sha256) is dict else {}
    names = ('tools/batch_execution.py',) if merged else ('native_response.jl','simulation/native_response.jl')
    expected = LEGACY_MERGE_SHA256 if merged else LEGACY_NATIVE_SHA256
    present = [pins[n] for n in names if n in pins]
    return bool(present) and all(h == expected for h in present)


def add_diagnostic_event(total, event):
    """Accumulate named counts from original source truth, including zeros."""
    lines=event.get('line_photon_counts')
    W.require(type(lines) is dict and set(lines)==set(total) and
              all(type(n) is int and n>=0 for n in lines.values()) and
              type(event.get('line_photon_count')) is int and event['line_photon_count']==sum(lines.values()),
              'Source event diagnostic photon counts differ from named-window truth.')
    for name,n in lines.items():total[name]+=n


def check_diagnostic_counts(expected, counts):
    W.require(typed_equal(counts.get('line_photon_counts'),expected) and
              type(counts.get('line_photons')) is int and counts['line_photons']==sum(expected.values()),
              'Response diagnostic photon counts differ from original named-window truth.')


def interpretation(histogram, counts, source_id, source_contract=None, source_sha256=None,
                   *, merged=False, root=W.ROOT):
    normal = descriptor(source_id, source_contract, root)
    W.require(type(histogram) is dict and type(histogram.get('width_keV')) is int and
              histogram['width_keV']==5 and typed_equal(histogram.get('normalization_denominators'),counts),
              'Histogram bins/denominators changed.')
    versioned = 'schema_version' in histogram or 'normalization' in histogram
    if normal is None:
        W.require(not versioned,'Legacy Cs137/gamma histogram contract changed.')
        return {'histogram_schema_version':1,'stored_value_key':LEGACY_KEY,'normalization':None,
                'legacy_alias':None}
    names = {v['name'] for v in normal['diagnostic_lines']}
    line_counts = counts.get('line_photon_counts')
    W.require(type(line_counts) is dict and set(line_counts)==names and
              all(type(n) is int and n>=0 for n in line_counts.values()) and
              type(counts.get('line_photons')) is int and counts['line_photons']==sum(line_counts.values()),
              'Diagnostic photon denominator differs from the named-window counts.')
    if versioned:
        W.require(type(histogram.get('schema_version')) is int and histogram['schema_version']==2 and
                  typed_equal(histogram.get('normalization'),normal),
                  'Histogram normalization descriptor differs from source/window authority.')
        W.require(not legacy_authority(source_sha256,merged=merged),
                  'New histogram schema contradicts the known historical exporter revision.')
        key = DIAGNOSTIC_KEY
    else:
        W.require(legacy_authority(source_sha256,merged=merged),
                  'Unversioned generic histogram lacks the known historical exporter authority.')
        key = LEGACY_KEY
    return {'histogram_schema_version':2 if versioned else 1,'stored_value_key':key,
            'normalization':normal,'legacy_alias':None if versioned else
            {'stored_key':LEGACY_KEY,'interpreted_key':DIAGNOSTIC_KEY,
             'reason':'historical generic exporter label; denominator is the selected diagnostic windows'}}


def validate(histogram, counts, source_id, source_contract=None, source_sha256=None,
             *, merged=False, csv_path=None, root=W.ROOT):
    interpreted = interpretation(histogram,counts,source_id,source_contract,source_sha256,merged=merged,root=root)
    W.require(type(histogram.get('bins')) is list,'Histogram bins must be an ordered list.')
    seen = set()
    for value in histogram['bins']:
        W.require(type(value) is dict,'Invalid histogram row.')
        stage, bin, n = value.get('stage'),value.get('bin'),value.get('count')
        key = (stage,bin) if type(stage) is str and type(bin) is int else None
        W.require(type(stage) is str and stage in STAGES and type(bin) is int and -1<=bin<=1000 and
                  type(n) is int and n>0 and key not in seen,'Invalid/repeated histogram bin.')
        # Typed equality avoids accepting Boolean/integer or float/integer edits.
        W.require(typed_equal(value,row(stage,bin,n,counts,interpreted['stored_value_key'])),
                  'Histogram boundaries or normalized values changed.')
        seen.add(key)
    if csv_path is not None:
        with Path(csv_path).open(encoding='utf-8',newline='') as stream:
            actual = list(csv.reader(stream))
        header = fields(interpreted['stored_value_key'])
        W.require(actual and tuple(actual[0])==header and len(actual)==len(histogram['bins'])+1,
                  'Histogram CSV/JSON schema or row count differs.')
        for cells, value in zip(actual[1:],histogram['bins']):
            W.require(len(cells)==len(header),'Histogram CSV column count changed.')
            for field, cell in zip(header,cells):
                expected = value[field]
                if expected is None: ok = cell==''
                elif type(expected) is str: ok = cell==expected
                else:
                    try:
                        parsed = int(cell) if type(expected) is int else float(cell)
                        ok = math.isfinite(parsed) and parsed==expected
                    except (ValueError,OverflowError): ok = False
                W.require(ok,'Histogram CSV/JSON semantics or values differ: '+field)
    return interpreted


def attach(histogram, normal):
    if normal is not None:
        histogram.update(schema_version=2,normalization=copy.deepcopy(normal))
    return histogram
