// Saved-site publication checks. Private scientific regressions never run science.
import fs from 'node:fs';
import path from 'node:path';

export const FIXTURE_CHECKS = [
  'tools/test_site.py', 'tools/test_contacts.py', 'tools/test_pipeline.py',
  'tools/test_gamma_showcase.py', 'tools/test_saved_terminal.py',
  'tools/test_local_ui_workflow_jobs.py', 'tools/test_local_ui_workflow_protocol.py',
  'tools/test_local_ui_jobs.py', 'tools/test_local_ui.py',
  'transport/test_scenario_prepare.py', 'tools/test_lithium_report.py',
  'tools/test_gallery_navigation.py', 'tools/test_site_restructure.py', 'tools/test_site_discovery.py',
];
export const PRIVATE_REGRESSIONS = [
  {test:'tools/test_gamma_complete_example.py', roots:['.local/gamma-complete-v1','.local/m11c-gamma-native-v1']},
  {test:'tools/test_gamma_complete_showcase.py', roots:['.local/m11c-gamma-native-v1','.local/gamma-complete-v1']},
  {test:'tools/test_saved_focus_waveforms.py', roots:['.local/runs/m14a-gamma-ui-03','.local/runs/m14a2-km-ui-02']},
  {test:'tools/test_saved_focus_pages.py', roots:['.local/pipeline-showcase']},
];
export const JAVASCRIPT_CHECKS = [
  'tools/test_focused_plots.js','tools/test_local_workflow.js','tools/test_publication_preflight.mjs',
];

export const PRIVATE_BUNDLE_CHECKS = [
  {root:'.local/gamma-complete-v1',validator:'tools/gamma_complete_showcase.py',bundle:'.local/gamma-complete-v1/bundle'},
];

export function preflight({root,python,node,run,log=console.log}) {
  run(python,['-B',path.join(root,'tools/export_models.py'),'--validate']);
  // A suite may skip its marker-gated test. Validate a present private root
  // directly so an absent completion marker cannot admit a partial bundle.
  for (const check of PRIVATE_BUNDLE_CHECKS) {
    if (fs.existsSync(path.join(root,check.root))) {
      run(python,['-B',path.join(root,check.validator),'validate',path.join(root,check.bundle)]);
    }
  }
  for (const test of FIXTURE_CHECKS) run(python,['-B',path.join(root,test)]);
  for (const {test,roots} of PRIVATE_REGRESSIONS) {
    // Run private regressions when their input roots are recorded. The direct
    // bundle check above is independent of unittest's completion-marker skips.
    if (roots.some(relative=>fs.existsSync(path.join(root,relative)))) {
      run(python,['-B',path.join(root,test)]);
    } else {
      log(`SKIP private saved-data regression: ${test} (no recorded input roots present).`);
    }
  }
  for (const test of JAVASCRIPT_CHECKS) run(node,[path.join(root,test)]);
  // Verifies every checked public artifact and bundle independently of .local.
  run(python,['-B',path.join(root,'tools/check_site.py')]);
}
