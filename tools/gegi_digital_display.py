"""Render the saved digital strip example in the Results hub."""
from html import escape
import json
import re


def render(site):
    data = site/'results/gegi-digital/event.json'
    if not data.exists():
        return
    ex = json.loads(data.read_bytes())
    rows = []
    for c in ex['channels']:
        slow = 'Below threshold' if 'slow_below_threshold' in c['flags'] else (
            'Unavailable' if c['slow_energy_keV'] is None else f'{c["slow_energy_keV"]:.2f}')
        rows.append(f'<tr><th scope="row">{escape(c["name"])}</th>'
                    f'<td>{max(abs(v) for v in c["signed_induced_keV"]):.2f}</td>'
                    f'<td>{c["signed_induced_keV"][-1]:.2f}</td><td>{c["fast_area_V_ns"]:.3f}</td><td>{slow}</td></tr>')
    card = f'''<section id="gegi" class="panel" data-dataset="gegi">
<h2>How neighboring GeGI strips sense a drifting charge</h2>
<p>During drift, both neighboring strips respond to the moving carriers. Their induced charge returns to zero, while their fast areas differ. The collecting strip supplies the slow energy signal.</p>
<figure style="margin:0"><img style="width:100%;height:auto" width="1450" height="870" src="gegi-digital/signals.png" alt="Induced charge and digital fast and slow signals on three adjacent strips">
<figcaption>Simulated primary {ex["event_id"]} · {ex["counts"]["initial_primaries"]:,} initial primaries, {ex["counts"]["nonzero_primaries"]} with a germanium deposit. Nominal digital readout.</figcaption></figure>
<div style="overflow-x:auto"><table><thead><tr><th>Strip</th><th>Largest |Q| (keV equivalent)</th><th>Final Q (keV equivalent)</th><th>Fast area (V·ns)</th><th>Slow energy (keV)</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p><a href="gegi-digital/event.json">Event samples and readout settings</a> · <a href="gegi-campaign/index.html">View the saved Compton study</a></p></section>'''
    benchmark = ex.get('position_benchmark')
    if benchmark:
        xy = benchmark['all_axes']
        card = card.removesuffix('</section>') + f'''<h3>Position check on independent simulated points</h3>
<p>The time difference between the two collecting strips selects a depth-dependent calibration of the neighboring signals.
Training used {benchmark["trained"]} injected points on four strip pairs. On {benchmark["n"]} separate {benchmark["energy_keV"]:g} keV points,
{benchmark["both"]} returned both lateral coordinates. Using the strip center for each unavailable axis,
the radial XY RMS error changed from <strong>{xy["center_rmse_mm"]:.2f} to {xy["substrip_rmse_mm"]:.2f} mm</strong>.
The depth RMS error was {benchmark["z"]["rmse_mm"]:.2f} mm on {benchmark["z"]["compared"]} points.
These errors compare simulated coordinates within the sampled region.</p></section>'''
    page = site/'results/index.html'
    old = page.read_text(encoding='utf-8')
    updated, n = re.subn(r'<section id="gegi"[^>]*>.*?</section>', lambda m: card, old, flags=re.S)
    if n != 1:
        raise ValueError('Expected one GeGI panel in the generated results hub.')
    page.write_text(updated, encoding='utf-8', newline='\n')
