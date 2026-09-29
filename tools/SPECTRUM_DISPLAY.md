# Saved-spectrum display

The current spectrum pages use step histograms, default true logarithmic count
axes, and per-chart Log / Linear controls. This is presentation only: no radiation,
field solving, carrier transport, electronics processing, fitting or smearing runs.

## Current pages and unchanged originals

| Current display | Original source report |
|---|---|
| `docs/spectra/million-truth.html` | `docs/examples/cs137-1m/report.html` |
| `docs/spectra/million-response.html` | `docs/examples/cs137-1m-response/report.html` |
| `docs/spectra/cs137-10k.html` | `docs/examples/cs137-10k/comparison.html` |
| `docs/spectra/pipeline.html` | `docs/examples/pipeline.html` |

Current homepage/result/detector routes and local workspace links use these new
views. Original reports remain available as explicitly linked archived displays;
their file hashes, numerical downloads, publication receipts and source generators
are unchanged. Old incoming links can still open those unchanged originals.

There are four truth plots, four response overlays, ten 10k stage spectra, one
pipeline plot with two detector states, and one homepage response preview. Time
waveforms, current/preamp/shaper traces, field views and depth diagnostics are not
energy spectra and are not changed. The inspected gallery/supplement captions
contain no further count-versus-energy distributions; no spectrum was invented
from selected waveform examples or repeated numerical variants.

## Exact display semantics

Counts remain raw integer counts per existing bin. Horizontal segments span true
bin edges, not interpolated centres. Log zero-count bins break the path; no
pseudocount is added. The axis floor is 0.5 solely to make count-one bins visible.
Linear mode restores the zero-count segments. Solid/dashed outlines and labelled
legends distinguish overlaid populations without relying only on color.

The truth histogram keeps exact-zero events in its separate category; this is
not the same as a bin containing zero events. Negative equivalent energy remains
negative on x. Underflow/overflow, population totals and bins outside a zoom view
remain distinct. Existing 1-keV and 5-keV bins are unchanged. The pipeline retains
its original 24-bin rule and complete event/waveform payload; changing model or
event cannot retune calibration or normalize the spectrum.

## Maintenance and validation

Edit `spectrum_plot.py` (static rendering), `spectrum_controls.js` (matching browser
controls), and `spectrum_display.py` (explicit readers and publication adapter).
`build_site.py --restructure` builds these views from the validated saved snapshot,
then updates current navigation. Do not run the original scientific report makers
or hand-edit generated HTML to change chart styling.

`docs/spectra/manifest.json` records origin report/data/receipt hashes, generator
hashes, display specs, static SVG/control/style seals and derived page hashes.
Final staging verifies deterministic rendering against current sources, including
the actual homepage preview. Saved-snapshot checks remain compatible with prior
generators so a later presentation update can validate its starting snapshot.

Run `python tools/test_spectrum_display.py` for exact-bin, count-one, zero-gap,
negative-energy, rehashed-mutation, repeat-generation and JS/Python geometry
checks. Browser acceptance additionally exercises the actual generated pages,
model/event changes, offline controls, keyboard/mobile use and static no-JavaScript
fallback. Normal site, link, archive and model checks still apply.

The original two scoped reviewer threads remain the reviewers for this work.
Local evidence is `.local/spectrum-display-v1/`. A display test pass is not new
scientific validation, calibrated energy resolution or clean-machine reproduction.

## Recorded review and acceptance

The original site-UX and workflow threads completed three scoped rounds: source
inventory, reciprocal implementation review, and final evidence inspection. Both
closed the display release without remaining blockers. These are AI source/evidence
reviews, not independent laboratory certification or re-execution of the tests.

The final 19 spectrum tests and five additional site suites passed (81 tests total).
Browser acceptance checked 20 current panels, two pipeline detector states,
unchanged counts/paths across scale changes, unchanged waveform/geometry DOM,
keyboard input, offline HTML and static log fallback. The supplied mobile/tablet
viewports are desktop-browser emulation, not native iPad/Safari certification.

All 1,439 prior public files remain; original reports, numerical bundles, models,
geometry assets and media are unchanged. All 173 protected local files retain
SHA-256, size and modification time. No completed science was run again.
