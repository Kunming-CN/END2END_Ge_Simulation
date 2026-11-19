"""Attach and display the saved independent-window GeGI library replay."""

from hashlib import sha256
from io import BytesIO
import json
import math

from gegi_plane_prior_display import COMMERCIAL_KEY, SUMMARY
from gegi_shared_clock_display import table


IMAGE = SUMMARY.with_name('simultaneous-spectrum-and-images.png')
RSS5 = 'https://www.spectrumtechniques.com/product/rss5/'
BLOCKS = [f'b{i:06d}' for i in range(5, 30)]
CENSUS = ('triggers', 'triggers_with_geometry', 'allowed_hypotheses', 'hypotheses',
          'projected_mass', 'unresolved_mass')
PRIORS = ('uniform-area', 'uniform-solid-angle')
COBALT_ROI = 'pooled_1173_and_1332_keV'


def direction_error(peak, known):
    if peak is None:
        return None
    cosine = sum(x*y for x, y in zip(peak, known, strict=True))/(math.hypot(*peak)*math.hypot(*known))
    return math.degrees(math.acos(max(-1., min(1., cosine))))


def compact_priors(prior, result, config, cobalt):
    if (prior['kind'] != 'gegi_commercial_simultaneous_prior_comparison_v1'
            or prior['status'] != 'completed' or prior['planned_blocks'] != BLOCKS
            or prior['processed_blocks'].keys() != result['blocks'].keys()
            or prior['campaign_sha256'] != result['configuration_sha256'] or prior['sources'] != config['sources']
            or any(prior['grid'][key] != value for key, value in config['plane'].items())
            or any(prior['grid'][axis] != result['imaging']['grid'][axis] for axis in ('x_mm', 'y_mm'))):
        raise ValueError('The prior comparison requires the same complete acquisition, source settings, and plane')
    for name, block in result['blocks'].items():
        saved = prior['processed_blocks'][name]
        provenance = block['provenance']
        if (saved['seal_sha256'], saved['report_sha256'], saved['acquisition_plane_sha256']) != (
                block['receipt_sha256'], provenance['report_sha256'], provenance['plane_sha256']):
            raise ValueError(f'The prior comparison refers to another acquisition or plane in {name}')

    layers = result['imaging']['layers']
    cs_label, = (label for label, layer in layers.items()
                 if layer.get('held_out_position_comparison', {}).get('source') == 'cs137-left')
    co_labels = [label for label, layer in layers.items()
                 if layer.get('held_out_position_comparison', {}).get('source') == 'co60-right']
    co_counts = {key: sum(layers[label][key] for label in co_labels) for key in CENSUS}
    area_peak = layers[cs_label]['peaks'][:1]
    comparisons = {}
    cases = (('cs137-left', cs_label, layers[cs_label], area_peak[0]['position_mm'] if area_peak else None),
             ('co60-right', COBALT_ROI, co_counts, cobalt['peak_position_mm']))
    for source, label, counts, baseline_peak in cases:
        part = dict(counts={key: counts[key] for key in CENSUS}, peaks={})
        for name in PRIORS:
            layer = prior['pooled'][name][label]
            reference = layer['held_out_comparison']
            peak = layer['blind_peaks'][0] if layer['blind_peaks'] else None
            if (reference['source'] != source
                    or reference['expected_position_mm'] != config['sources'][source]['position_mm']
                    or any(not math.isclose(layer['accounting'][key], counts[key], rel_tol=0., abs_tol=1.e-9)
                           for key in CENSUS)
                    or (name == PRIORS[0] and (peak['position_mm'] if peak else None) != baseline_peak)):
                raise ValueError('The prior comparison changed the measured counts or default peak')
            part['peaks'][name] = dict(peak, **reference['peak_offsets'][0]) if peak else None
        comparisons[source] = part
    return comparisons


def attach(site, campaign):
    raw = (campaign/'results.json').read_bytes()
    result = json.loads(raw)
    clock = result['clock_reference']
    if (result['kind'] != 'gegi_commercial_simultaneous_results_v1' or result['status'] != 'completed'
            or clock['status'] != 'completed'
            or any(names != BLOCKS for names in (result['planned_blocks'], result['completed_blocks'],
                                                clock['completed_blocks'], list(result['blocks']), list(clock['blocks'])))
            or any(clock['blocks'][name]['shard_receipt_sha256'] != result['blocks'][name]['receipt_sha256']
                   for name in BLOCKS)):
        raise ValueError('The exhibit requires all 25 finalized acquisitions and matching clock diagnostics')

    config_raw = (campaign/'campaign.json').read_bytes()
    config = json.loads(config_raw)
    results_sha = sha256(raw).hexdigest()
    interval_raw = (campaign/'sampling-intervals.json').read_bytes()
    intervals = json.loads(interval_raw)
    if (sha256(config_raw).hexdigest() != result['configuration_sha256'] or list(config['blocks']) != BLOCKS
            or config['live_time_per_block_s'] != .25
            or intervals['kind'] != 'gegi_simultaneous_block_sampling_v1' or intervals['completed_blocks'] != BLOCKS
            or intervals['results_sha256'] != results_sha):
        raise ValueError('The acquisition configuration or sampling intervals do not match the finalized results')

    from PIL import Image

    prior_raw = (campaign/'alternate-prior.json').read_bytes()
    prior_sha = sha256(prior_raw).hexdigest()
    if intervals['alternate_prior_sha256'] != prior_sha:
        raise ValueError('The sampling intervals refer to a different prior comparison')
    figure = (campaign/IMAGE.name).read_bytes()
    with Image.open(BytesIO(figure)) as image:
        if (image.format != 'PNG' or image.info.get('Description') != f'results_sha256={results_sha}'
                or image.info.get('AlternatePriorSHA256') != prior_sha):
            raise ValueError('The acquisition figure does not match the finalized results')
        figure_size = image.size
        image.verify()

    acquisition, imaging = result['acquisition'], result['imaging']
    counts, sources, exposure = (acquisition[key] for key in ('counts', 'sources', 'exposure'))
    for key, source in sources.items():
        design = config['sources'][key]
        if any(source[field] != design[field] for field in ('activity_bq', 'position_mm')):
            raise ValueError('The recorded source settings differ from the campaign configuration')
    sources = {key: dict(source, isotope=config['sources'][key]['isotope']) for key, source in sources.items()}
    windows = acquisition['measured_energy_window_counts']
    all_triggers = imaging['layers']['all']
    overlap = clock['pooled']['overlap_counts']['all_qualified']
    if (counts['qualified_triggers'] != counts['qualified_energies'] + counts['triggers_without_energy']
            or counts['qualified_energies'] != sum(windows.values())
            or acquisition['spectra']['combined']['entries'] != counts['qualified_energies']
            or overlap['qualified_triggers'] != counts['qualified_triggers']
            or intervals['mixed_rise_fraction']['numerator'] != overlap['mixed_source_merged_timing_graph']
            or intervals['mixed_rise_fraction']['denominator'] != counts['qualified_triggers']
            or intervals['lines'].keys() != windows.keys() - {'other_energy'}
            or exposure['clock_live_time_ns'] != len(BLOCKS)*config['live_time_per_block_s']*1.e9
            or not math.isclose(all_triggers['projected_mass'] + all_triggers['unresolved_mass'],
                                all_triggers['triggers'], abs_tol=1.e-9)):
        raise ValueError('Final acquisition, imaging, or overlap counts do not close')

    lines = {}
    for label, sampling in sorted(intervals['lines'].items(), key=lambda item: float(item[0].removesuffix('_keV'))):
        layer = imaging['layers'][label]
        reference = layer['held_out_position_comparison']
        known = reference['source_position_mm']
        if known != sources[reference['source']]['position_mm']:
            raise ValueError('The line image refers to a different programmed source')
        peak = layer['peaks'][0] if layer['peaks'] else None
        lines[label] = dict({key: layer[key] for key in CENSUS}, accepted_energies=windows[label],
                            peak=peak, direction_error_deg=direction_error(peak['position_mm'] if peak else None, known),
                            **reference, sampling=sampling)
    cobalt = intervals['combined_cobalt']
    cobalt_lines = [line for line in lines.values() if line['source'] == 'co60-right']
    if (cobalt['source_position_mm'] != sources['co60-right']['position_mm']
            or len(cobalt_lines) != 2
            or any(not math.isclose(cobalt[key], sum(line[key] for line in cobalt_lines), abs_tol=1.e-9)
                   for key in ('triggers', 'projected_mass', 'unresolved_mass'))):
        raise ValueError('The pooled cobalt image does not match its two line windows')
    cobalt['direction_error_deg'] = direction_error(cobalt['peak_position_mm'], cobalt['source_position_mm'])
    prior_comparison = compact_priors(json.loads(prior_raw), result, config, cobalt)

    first = BLOCKS[0]
    trigger = clock['blocks'][first]['overlap_examples']['mixed_graph_two_strip']
    groups = sorted(trigger['groups'], key=lambda group: group['first_ge_deposit_ns'])
    if len(groups) != 2 or {group['source'] for group in groups} != sources.keys():
        raise ValueError('The illustrated rise requires one deposit group from each source')
    example = dict(block=first, trigger_number=trigger['trigger_number'], energy_keV=trigger['energy_keV'],
                   deposit_onset_gap_ns=groups[1]['first_ge_deposit_ns']-groups[0]['first_ge_deposit_ns'],
                   isotope_order=[sources[group['source']]['isotope'] for group in groups])
    public = dict(blocks=len(BLOCKS), live_time_per_block_s=config['live_time_per_block_s'],
                  counts=counts, exposure=exposure, sources=sources, activity_reference_url=RSS5,
                  overlap=overlap, example=example, lines=lines, combined_cobalt=cobalt,
                  prior_comparison=prior_comparison,
                  imaging={key: all_triggers[key] for key in CENSUS},
                  grid={key: imaging['grid'][key] for key in ('assumed_z_mm', 'step_mm', 'extent_mm')},
                  sampling=dict(resamples=intervals['resamples'], seed=intervals['seed'],
                                mixed_rise_fraction=intervals['mixed_rise_fraction']),
                  figure_size_px=figure_size, source_sha256=dict(configuration=result['configuration_sha256'],
                      results=results_sha, sampling_intervals=sha256(interval_raw).hexdigest(), alternate_prior=prior_sha,
                      figure=sha256(figure).hexdigest()))
    existing = json.loads((site/SUMMARY).read_bytes())
    existing[COMMERCIAL_KEY] = public
    (site/IMAGE).write_bytes(figure)
    (site/SUMMARY).write_text(json.dumps(existing, allow_nan=False, separators=(',', ':'))+'\n',
                              encoding='utf-8', newline='\n')


def format_peak(peak):
    if peak is None:
        return 'Unavailable'
    xy = '({:g}, {:g})'.format(*peak['position_mm'][:2]).replace('-', '−')
    edge = ' (edge)' if peak['on_image_edge'] else ''
    return f"{xy} mm{edge} · {peak['distance_mm']:.1f} mm offset · {peak['direction_error_deg']:.1f}°"


def section(site):
    summary = site/SUMMARY
    if not summary.is_file():
        return ''
    data = json.loads(summary.read_bytes()).get(COMMERCIAL_KEY)
    if data is None:
        return ''
    if sha256((site/IMAGE).read_bytes()).hexdigest() != data['source_sha256']['figure']:
        raise ValueError('The simultaneous acquisition figure differs from its saved summary')
    counts, exposure, image, example = (data[key] for key in ('counts', 'exposure', 'imaging', 'example'))
    clock_s, qualified_s = (exposure[key]/1.e9 for key in ('clock_live_time_ns', 'qualified_adc_live_time_ns'))
    cs, co = (data['sources'][key] for key in ('cs137-left', 'co60-right'))
    rows = []
    for label, line in data['lines'].items():
        peak = line['peak']
        xy = '({:g}, {:g})'.format(*peak['position_mm'][:2]).replace('-', '−') if peak else 'Unavailable'
        variation = line['sampling']['blind_peak'].get('peak_offset_mm_p025_median_p975')
        interval = f'{variation[0]:.1f}–{variation[2]:.1f}' if variation else 'Unavailable'
        rows.append((f"{float(label.removesuffix('_keV')):,.0f} keV", f"{line['accepted_energies']:,}",
                     f"{line['triggers_with_geometry']:,}/{line['triggers']:,}", xy,
                     f"{line['primary_peak_distance_mm']:.1f}" if peak else 'Unavailable',
                     f"{line['direction_error_deg']:.1f}°" if peak else 'Unavailable', interval))
    comparison = table(rows, ('Energy window', 'Accepted energies', 'Projected / two-strip', 'Peak X, Y (mm)',
                              'Offset (mm)', 'Direction error', '95% resampled offset (mm)'),
                       'Blind line-window peaks and errors relative to the programmed sources')
    prior_rows = []
    for key, name in (('cs137-left', 'Cs-137, 662 keV'), ('co60-right', 'Co-60, both windows')):
        part = data['prior_comparison'][key]
        prior_rows.append((name, *(format_peak(part['peaks'][prior]) for prior in PRIORS)))
    prior_table = table(prior_rows, ('Source window', 'Uniform area (default)', 'Uniform solid angle'),
                        'Image peak X, Y and errors from the programmed source')
    width, height = data['figure_size_px']
    def position(source):
        return ('({:g}, {:g}, {:g})'.format(*source['position_mm'])).replace('-', '−')

    return f'''<h2 id="gegi-commercial-acquisition">Shared spectrum and conditional source-plane maps</h2>
<div class="gegi-result-summary"><p><strong>{data['blocks']} independent {data['live_time_per_block_s']*1000:g} ms historical library replay windows,
summed {clock_s:g} s.</strong> Each window resets its source clocks and electronics state and reuses archived single-isotope histories.
This is readout evidence; it does not implement the planned joint source generation and ≥60 s uninterrupted production acquisition.</p>
<p>The replay recorded <strong>{counts['qualified_triggers']:,} qualified triggers</strong> and
<strong>{counts['qualified_energies']:,} accepted energies</strong> in {qualified_s:.8f} s of qualified ADC time.
The images compare where each isotope’s gamma-line cones point under two imaging priors.</p>
<p><a href="#gegi-data-methods">Find data and methods</a></p></div>
<figure class="gegi-result-figure"><img width="{width}" height="{height}" src="gegi-digital/{IMAGE.name}"
alt="Combined energy spectrum, one mixed-source ADC rise, and four maps comparing area and solid-angle priors for both isotopes">
<figcaption>The waveform shows one mixed-source rise. The two deposit groups began {example['deposit_onset_gap_ns']:.0f} ns apart.
Co-60 maps pool the 1,173 and 1,332 keV windows. Crosses mark the programmed sources and circles mark the image maxima.
<a href="gegi-digital/{IMAGE.name}">Open the full-size figure</a>.</figcaption></figure>
<h3>Source direction and unresolved events</h3>
{prior_table}
<p>Without using the programmed coordinates to locate the peaks, both priors project the same measured cones and
interaction orders onto z = {data['grid']['assumed_z_mm']:g} mm. Direction errors are angles from the detector center.
Of {image['triggers']:,} two-strip triggers, {image['triggers']-image['triggers_with_geometry']:,} had no usable projection.
Including the unprojected orders of other triggers, {image['unresolved_mass']:,.1f} trigger units remained unresolved.</p>
<div id="gegi-data-methods"><h3>Data and methods</h3>
<p><a href="gegi-digital/{SUMMARY.name}">Open acquisition counts, line-window results and source hashes (JSON)</a>.
The historical replay is under the retained data key <code>{COMMERCIAL_KEY}</code>.</p>
<p><a href="../methods/index.html#gegi-acquisition-method">How GeGI acquisition and imaging work</a></p></div>
<details><summary>Line-window counts and sampling intervals</summary>{comparison}
<p>Intervals come from {data['sampling']['resamples']:,} whole-exposure resamples under this simulated setup.</p></details>
<details><summary>Source placement, acquisition and event counts</summary>
<p>Cs-137 was modeled at {position(cs)} mm ({cs['activity_bq']/1000:g} kBq) and Co-60 at
{position(co)} mm ({co['activity_bq']/1000:g} kBq), using nominal activities from the
<a href="{RSS5}">Spectrum Techniques RSS5 check-source set</a>.</p>
<p>The total window clock is {clock_s:g} s; qualified ADC time is {qualified_s:.8f} s.
The windows used disjoint archived source libraries, sampled with replacement within each window.
Independent source clocks scheduled occurrences of these archived histories. For each of 34
electrodes, the simulation summed signed analog preamplifier voltages, then added channel noise, digitized, and applied the trigger.</p>
<p>{counts['triggers_without_energy']:,} qualified triggers had no accepted energy. Of {image['triggers']:,} two-strip
triggers, {image['triggers_with_geometry']:,} contributed {image['hypotheses']:,} projected orders from
{image['allowed_hypotheses']:,} allowed orders. The timing comparison associated {data['overlap']['mixed_source_merged_timing_graph']:,} qualified
rises with deposits from both sources. It found simultaneous native current on measured strips in
{data['overlap']['both_source_simultaneous_native_current_on_measured_strips']:,} qualified rises.
The illustrated rise reconstructed to {example['energy_keV']:.2f} keV, with {example['isotope_order'][0]} followed by
{example['isotope_order'][1]} in the simulated deposit history.</p></details>'''
