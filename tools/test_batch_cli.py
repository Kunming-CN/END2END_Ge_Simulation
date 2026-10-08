"""Public batch commands delegate to the shared controller without running science."""
import contextlib
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import scenario_workflow as W


class BatchCommands(unittest.TestCase):
    def setUp(self):
        self.controller = types.ModuleType('batch_execution')
        for name in ('check', 'execute', 'inspect', 'request_stop'):
            setattr(self.controller, name, Mock(return_value={'status': name}))

    def invoke(self, arguments, reader):
        output = io.StringIO()
        with patch.dict(sys.modules, batch_execution=self.controller), patch.object(W, 'read', reader), contextlib.redirect_stdout(output):
            W.main(arguments)
        return json.loads(output.getvalue())

    def test_check_uses_explicit_configuration_and_bounded_acceptance(self):
        selection, acceptance = {'name': 'checked'}, {'kind': 'bounded'}
        reader = Mock(side_effect=[selection, acceptance])
        result = self.invoke(['check-batches', '--config', 'selection.json', '--acceptance', 'acceptance.json'], reader)
        self.controller.check.assert_called_once_with(selection, acceptance=acceptance)
        self.assertEqual(reader.call_args_list[0].args, (Path('selection.json'),))
        self.assertEqual(result['status'], 'check')
        self.controller.execute.assert_not_called()

    def test_run_resume_inspect_and_stop_use_the_recorded_task(self):
        plan = {'kind': 'checked-plan'}
        self.invoke(['run-batches', '--plan', 'checked.json'], Mock(return_value=plan))
        self.controller.execute.assert_called_once_with(plan, dispatch_id=None)
        self.controller.execute.reset_mock()
        reader = Mock(return_value=plan)
        self.invoke(['resume-batches', '--name', 'saved'], reader)
        reader.assert_called_once_with(W.run_path('saved') / 'resolved-config.json')
        self.controller.execute.assert_called_once_with(plan, resume=True, dispatch_id=None)
        self.invoke(['inspect-batches', '--name', 'saved'], Mock())
        self.controller.inspect.assert_called_once_with('saved')
        self.invoke(['stop-batches', '--name', 'saved'], Mock())
        self.controller.request_stop.assert_called_once_with('saved')

    def test_check_consumes_the_exact_control_export_wrapper(self):
        selection = {'name': 'student-export', 'primary_count': 10001}
        exported = {'kind': 'local_scenario_batch_request_v2', 'schema_version': 2, 'selection': selection}
        self.invoke(['check-batches', '--config', 'exported.json'], Mock(return_value=exported))
        self.controller.check.assert_called_once_with(selection, acceptance=None)
        self.controller.execute.assert_not_called()

    def test_malformed_exports_and_checked_plans_are_not_configuration(self):
        exported = {'kind': 'local_scenario_batch_request_v2', 'schema_version': 2, 'selection': {}}
        invalid = [dict(exported, schema_version=True), dict(exported, schema_version=3),
                   dict(exported, extra='unexpected'),
                   {'kind': 'local_scenario_batch_preview_v2', 'resolved': {}},
                   {'kind': 'local_scenario_batch_execution_v3', 'resolved': {}}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(W.ControlError):
                self.invoke(['check-batches', '--config', 'exported.json'], Mock(return_value=value))
        self.controller.check.assert_not_called()
        self.controller.execute.assert_not_called()

    def test_missing_arguments_and_acceptance_on_other_actions_refuse_before_dispatch(self):
        for arguments in (['check-batches'], ['run-batches'], ['resume-batches'], ['inspect-batches'], ['stop-batches'],
                          ['run-batches', '--plan', 'checked.json', '--acceptance', 'acceptance.json']):
            with self.subTest(arguments=arguments), self.assertRaises(W.ControlError):
                self.invoke(arguments, Mock(side_effect=AssertionError('must not read inputs')))
        self.controller.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
