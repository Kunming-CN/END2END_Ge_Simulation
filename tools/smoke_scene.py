"""Load and render one existing ParaView event after migration; no rebuild."""
import json, sys
from pathlib import Path
from paraview.simple import LoadState, RenderAllViews, GetSources, GetLayouts, SaveScreenshot
root = Path(__file__).resolve().parents[1]
ident = sys.argv[1]
if ident not in ('AK01', 'GeGI_3D'):
    raise SystemExit('Smoke-test detector must be AK01 or GeGI_3D')
state = root / 'Additional_Simulations' / 'Visualization_3D' / 'detectors' / ident / 'runs' / '20260922_suite_v3' / 'events' / 'fixed' / 'scene.pvsm'
LoadState(str(state))
RenderAllViews()
layouts = list(GetLayouts().values())
if not layouts: raise RuntimeError('No layout loaded')
SaveScreenshot(str(root / '.local' / ('native-' + ident + '.png')), layouts[0], ImageResolution=[1200, 800])
report = {'detector': ident, 'state_loaded_and_rendered': True, 'sources': len(GetSources()), 'layouts': len(layouts)}
(root / '.local' / ('native-' + ident + '.json')).write_text(json.dumps(report, indent=2))
print(json.dumps(report), flush=True)
