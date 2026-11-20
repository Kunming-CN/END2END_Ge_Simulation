"""Deterministic stage profiling contracts; no workers, sleeps or simulations."""

import copy
import json
import unittest

from gegi_resource_monitor import NATIVE_OUTCOMES, TIMER_HISTOGRAM_UPPER_SECONDS, TIMER_STAGES, TimerTotals


class Clock:
    def __init__(self, value=0.):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class StageTimerTests(unittest.TestCase):
    def test_measured_stages_histogram_boundaries_and_constant_size(self):
        clock = Clock()
        timers = TimerTotals(clock=clock)
        for elapsed in (0., .0001, .001, .01, .1, 1., 10., 60., 600., 601.):
            with timers.measure('native_group'):
                clock.advance(elapsed)
        row = timers.snapshot()['stages']['native_group']
        self.assertEqual(row['count'], 10)
        self.assertAlmostEqual(row['total_seconds'], 1272.1111)
        self.assertEqual(row['min_seconds'], 0.)
        self.assertAlmostEqual(row['max_seconds'], 601.)
        self.assertEqual(sum(row['histogram_counts']), 10)
        # Direct recorded values test exact upper-inclusive bin boundaries;
        # the clock test above also exercises floating-point measured times.
        exact = TimerTotals()
        for elapsed in (0., *TIMER_HISTOGRAM_UPPER_SECONDS, 601.):
            exact.record('readout', elapsed)
        self.assertEqual(exact.snapshot()['stages']['readout']['histogram_counts'], [2, 1, 1, 1, 1, 1, 1, 1, 1])
        before = len(json.dumps(exact.snapshot()))
        for _ in range(2000):
            exact.record('readout', .125)
        snapshot = exact.snapshot()
        self.assertEqual(set(snapshot['stages']), set(TIMER_STAGES))
        self.assertLess(len(json.dumps(snapshot))-before, 100)
        self.assertTrue(all(len(row['histogram_counts']) == 9 for row in snapshot['stages'].values()))
        self.assertIsNone(snapshot['stages']['transport_run']['min_seconds'])

    def test_snapshot_json_restore_downtime_exclusion_and_independent_counts(self):
        clock = Clock(10.)
        timers = TimerTotals(clock=clock)
        with timers.measure('transport_prepare'):
            clock.advance(.25)
        timers.record_native('completed')
        timers.record_native('failed')
        timers.record_native('unavailable')
        state = json.loads(json.dumps(timers.snapshot(), allow_nan=False))
        original = copy.deepcopy(state)
        resumed_clock = Clock(50000.)
        resumed = TimerTotals(state, clock=resumed_clock)
        with resumed.measure('native_group'):
            resumed_clock.advance(.5)
        resumed.record_native('completed')
        snapshot = resumed.snapshot()
        self.assertEqual(snapshot['native_outcomes'], {'completed': 2, 'failed': 1, 'unavailable': 1})
        self.assertEqual(snapshot['stages']['transport_prepare']['total_seconds'], .25)
        self.assertEqual(snapshot['stages']['native_group']['total_seconds'], .5)
        self.assertEqual(state, original)
        snapshot['stages']['native_group']['histogram_counts'][0] = 999
        self.assertNotEqual(snapshot, resumed.snapshot())
        self.assertEqual(TimerTotals(resumed.snapshot()).snapshot(), resumed.snapshot())

    def test_exception_is_recorded_and_reraised_without_native_failure_inference(self):
        clock = Clock()
        timers = TimerTotals(clock=clock)
        failure = RuntimeError('Preserved worker failure')
        with self.assertRaises(RuntimeError) as caught:
            with timers.measure('native_group'):
                clock.advance(.75)
                raise failure
        self.assertIs(caught.exception, failure)
        row = timers.snapshot()['stages']['native_group']
        self.assertEqual((row['count'], row['exception_count'], row['total_seconds']), (1, 1, .75))
        self.assertEqual(timers.snapshot()['native_outcomes'], {key: 0 for key in NATIVE_OUTCOMES})

    def test_checkpoint_inside_scope_marks_unsealed_measurement_on_restore(self):
        clock = Clock()
        timers = TimerTotals(clock=clock)
        with timers.measure('checkpoint'):
            clock.advance(.1)
            saved = json.loads(json.dumps(timers.snapshot(), allow_nan=False))
            self.assertEqual(saved['in_flight_stages'], ['checkpoint'])
            self.assertEqual(saved['stages']['checkpoint']['count'], 0)
            clock.advance(.2)
        self.assertAlmostEqual(timers.snapshot()['stages']['checkpoint']['total_seconds'], .3)
        resumed = TimerTotals(saved, clock=Clock(10000.))
        row = resumed.snapshot()['stages']['checkpoint']
        self.assertEqual((row['count'], row['total_seconds'], row['unsealed_measurement_count']), (0, 0., 1))
        self.assertEqual(row['exception_count'], 0)
        self.assertEqual(resumed.snapshot()['in_flight_stages'], [])

    def test_nested_different_stages_are_inclusive_and_same_stage_is_refused(self):
        clock = Clock()
        timers = TimerTotals(clock=clock)
        with timers.measure('transport_cli'):
            clock.advance(.1)
            with timers.measure('transport_prepare'):
                clock.advance(.2)
                self.assertEqual(timers.snapshot()['in_flight_stages'], ['transport_cli', 'transport_prepare'])
            with self.assertRaisesRegex(ValueError, 'already active'):
                with timers.measure('transport_cli'):
                    pass
            clock.advance(.1)
        state = timers.snapshot()
        self.assertAlmostEqual(state['stages']['transport_cli']['total_seconds'], .4)
        self.assertAlmostEqual(state['stages']['transport_prepare']['total_seconds'], .2)
        self.assertIn('nested stage totals overlap', state['scope'])

    def test_invalid_times_outcomes_and_changed_checkpoint_census_are_rejected(self):
        timers = TimerTotals()
        for stage, duration in (('arbitrary', 1.), ('readout', -1.), ('readout', float('nan')),
                                ('readout', float('inf')), ('readout', True)):
            with self.assertRaises(ValueError):
                timers.record(stage, duration)
        with self.assertRaises(ValueError):
            timers.record_native('accepted_energy')
        timers.record('export', 2.)
        for change in ('kind', 'histogram', 'native', 'bounds', 'count', 'active'):
            state = timers.snapshot()
            if change == 'kind':
                state['kind'] = 'other'
            elif change == 'histogram':
                state['stages']['export']['histogram_counts'][0] += 1
            elif change == 'native':
                state['native_outcomes']['failed'] = -1
            elif change == 'bounds':
                state['stages']['export']['min_seconds'] = 3.
            elif change == 'count':
                state['stages']['export']['exception_count'] = 2
            else:
                state['in_flight_stages'] = ['unknown']
            with self.subTest(change=change), self.assertRaises(ValueError):
                TimerTotals(state)


if __name__ == '__main__':
    unittest.main()
