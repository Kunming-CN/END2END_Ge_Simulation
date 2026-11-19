"""Plot the measured spectrum, a shared-clock ADC window and blind line images."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np


def shared_window(axis, campaign, result):
    for block, reference in sorted(result['clock_reference']['blocks'].items()):
        event = reference['overlap_examples'].get('mixed_graph_two_strip')
        if event is None:
            continue
        folder = campaign / block
        with np.load(folder/'two-strip-adc.npz', allow_pickle=False) as adc:
            match, = np.flatnonzero(adc['trigger_time_ns'] == event['trigger_time_ns'])
            if adc['window_status'][match] != 'captured':
                continue
            contacts = list(adc['contact_ids'])
            sample_ns = adc['relative_time_ns']
            voltage = 1000*(adc['adc_codes'][match]*adc['volts_per_code'] - adc['acquisition_baseline_v'][:, None])
        for cid in event['x_collecting_strips'] + event['y_collecting_strips']:
            label = f'X{cid:02d}' if cid <= 16 else f'Y{cid-17:02d}'
            axis.plot(sample_ns, voltage[contacts.index(cid)], '.-', markersize=2.6, linewidth=1.3, label=label)
        for group in event['groups']:
            t = group['first_ge_deposit_ns'] - event['trigger_time_ns']
            axis.axvline(t, color='#53626b', linestyle=':', linewidth=1.3)
            axis.text(t+5, .95, group['source'].split('-')[0].replace('cs137', 'Cs').replace('co60', 'Co'),
                      fontsize=9, va='top', transform=axis.get_xaxis_transform())
        axis.set(title=f"One recorded rise  |  {event['energy_keV']:.2f} keV",
                 xlabel='Time from trigger (ns)', ylabel='Preamp ADC (mV)')
        axis.legend(ncols=2, fontsize=8, loc='center right', frameon=False)
        axis.grid(axis='y', alpha=.15)
        return True
    return False


def plot(campaign, output):
    raw = (campaign/'results.json').read_bytes()
    result = json.loads(raw)
    acquisition, imaging = result['acquisition'], result['imaging']
    live = acquisition['exposure']['clock_live_time_ns'] / 1e9
    qualified = acquisition['exposure']['qualified_adc_live_time_ns'] / 1e9
    specs = acquisition['spectra']['combined']
    fig = plt.figure(figsize=(15.6, 7.7), layout='constrained', facecolor='white')
    grid = fig.add_gridspec(2, 12, height_ratios=[.85, 1.0])
    waveform = fig.add_subplot(grid[0, 8:])
    has_example = shared_window(waveform, campaign, result)
    if not has_example:
        waveform.remove()
    spectrum = fig.add_subplot(grid[0, :8] if has_example else grid[0, :])
    spectrum.stairs(specs['counts'], specs['bin_edges_keV'], color='#214857', linewidth=1.6)
    for energy, label, color, alignment in [(661.657, 'Cs 662', '#157b78', 'right'),
                                            (1173.228, 'Co 1173', '#a84621', 'right'),
                                            (1332.492, 'Co 1332', '#a84621', 'left')]:
        spectrum.axvline(energy, color=color, linestyle='--', linewidth=1.1)
        spectrum.text(energy, .95, label, va='top', ha=alignment, color=color,
                      transform=spectrum.get_xaxis_transform(), fontsize=9)
    spectrum.set(xlabel='Reconstructed energy (keV)', ylabel='Counts per 20 keV',
                 title=f"Combined spectrum  |  {specs['entries']:,} accepted energies")
    spectrum.set_yscale('symlog', linthresh=1)
    spectrum.set_xlim(specs['bin_edges_keV'][0], specs['bin_edges_keV'][-1])
    spectrum.grid(axis='y', alpha=.16)
    alt_raw = (campaign/'alternate-prior.json').read_bytes()
    comparison = json.loads(alt_raw)
    if (set(comparison['processed_blocks']) != set(result['completed_blocks'])
            or comparison['campaign_sha256'] != result['configuration_sha256']):
        raise ValueError('The prior comparison and measured acquisition cover different source blocks')
    panels = []
    for name, isotope in [('661.657_keV', 'Cs 662'), ('pooled_1173_and_1332_keV', 'Co 1173 + 1332')]:
        for prior, caption in [('uniform-area', 'uniform area'), ('uniform-solid-angle', 'solid angle')]:
            layer = comparison['pooled'][prior][name]
            source = layer['held_out_comparison']['expected_position_mm']
            peak = layer['blind_peaks'][0]['position_mm'] if layer['blind_peaks'] else None
            panels.append((f'{isotope} | {caption}', layer['accounting'], np.asarray(layer['mass_trigger_units']),
                           source, peak))
    axes = []
    for i, (label, layer, mass, position, peak) in enumerate(panels):
        ax = fig.add_subplot(grid[1, i*3:(i+1)*3])
        axes.append(ax)
        area = imaging['grid']['extent_mm']
        im = ax.imshow(mass/mass.max() if mass.max() else mass, vmin=0, vmax=1, origin='lower', cmap='magma',
                       extent=[-area, area, -area, area], interpolation='nearest')
        ax.plot(*position[:2], marker='x', color='#70ffc6', markersize=10, markeredgewidth=2.2)
        if peak:
            ax.plot(*peak[:2], marker='o', markersize=10,
                    markerfacecolor='none', markeredgecolor='white', markeredgewidth=1.5, clip_on=False)
        axial = f"  |  z = {imaging['grid']['assumed_z_mm']:g} mm" if i == 1 else ''
        ax.set(xlabel=f'Detector X (mm){axial}', ylabel='Detector Y (mm)' if i == 0 else '',
               title=f"{label}\n{layer['triggers_with_geometry']:,}/{layer['triggers']:,} projected")
    fig.colorbar(im, ax=axes, shrink=.8, label='Cell weight / panel maximum')
    markers = [Line2D([], [], linestyle='', marker='x', color='#196249', label='Programmed source'),
               Line2D([], [], linestyle='', marker='o', markerfacecolor='none', color='#32424d', label='Blind maximum')]
    spectrum.legend(handles=markers, loc='upper right', frameon=False, fontsize=9, title='Map symbols')
    fig.suptitle(f"Simultaneous GeGI acquisition  |  Cs-137 185 kBq + Co-60 37 kBq\n"
                 f"{live:g} s on clock, {qualified:.3f} s qualified  |  "
                 f"{len(result['completed_blocks'])}/{len(result['planned_blocks'])} exposures",
                 fontsize=15)
    tmp = output.with_suffix('.tmp')
    fig.savefig(tmp, format='png', dpi=150, facecolor='white',
                metadata={'Description': 'results_sha256=' + sha256(raw).hexdigest(),
                          'AlternatePriorSHA256': sha256(alt_raw).hexdigest()})
    plt.close(fig)
    tmp.replace(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    args = parser.parse_args()
    plot(args.campaign, args.campaign/'simultaneous-spectrum-and-images.png')
