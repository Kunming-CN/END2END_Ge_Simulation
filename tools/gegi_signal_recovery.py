"""Assign uses to saved GeGI signals without inventing interaction identities.

Fixed-gain spectroscopy reuses the original face-sum implementation. Collection
on a guard is useful for total pulse energy but does not provide a strip position.
Adjacent strips are reported, never merged into an assumed photon interaction.
"""
from __future__ import annotations

import gegi_imaging as I

KIND = 'gegi_saved_signal_use_v1'


def classify_observables(observed, reconstruction=None):
    """Only allowlisted signals enter; source, tracks and interaction truth do not."""
    reconstruction = reconstruction or {}
    spectrum = I.readout_summary(observed)
    out = {'kind': KIND, 'event_id': observed['event_id'],
           'pulse_group_id': observed['pulse_group_id'],
           'category': 'failed_or_incomplete', 'spectroscopy': spectrum,
           'supported_imaging': False, 'conditional_candidate_count': 0,
           'guard': {'collecting_ids': [], 'transient_ids': [],
                     'transient_scope': 'Saved nonzero waveform with no above-threshold terminal collection'},
           'strip_counts': [0, 0], 'strip_threshold_keV': I.MIN_COLLECTED_KEV,
           'adjacent_strip_pairs': [],
           'same_pixel_multiplicity': 'unknown', 'photon_multiplicity': 'unresolved',
           'truth_used': False, 'source_label_used': False}
    if observed['status'] != 'completed' or observed['channels'] is None:
        return out
    channels = observed['channels']
    collecting = [c for c in channels if I.terminal_collection(c, c['wiring_factor'])]
    guards = [c['contact_id'] for c in channels
              if c['collection_candidate'] is True and c['contact_id'] in (17, 34)]
    out['guard']['collecting_ids'] = guards
    diagnostics = reconstruction.get('signed_signal_diagnostics', {}).get('nonzero_channels', [])
    out['guard']['transient_ids'] = [d['contact_id'] for d in diagnostics
        if d['contact_id'] in (17, 34) and d['contact_id'] not in guards
        and max(abs(d['minimum_wired_keV']), abs(d['maximum_wired_keV'])) >= I.MIN_COLLECTED_KEV]
    faces = [[c['contact_id'] for c in collecting if low <= c['contact_id'] <= high]
             for low, high in ((1, 16), (18, 33))]
    out['strip_counts'] = [len(face) for face in faces]
    out['adjacent_strip_pairs'] = [[cid, cid+1] for face in faces for cid in sorted(face) if cid+1 in face]
    out['same_pixel_multiplicity'] = ('unidentifiable' if out['strip_counts'] == [1, 1]
                                      else 'not_resolved_by_strip_counts')
    # Native terminal charge remains a separate diagnostic, never an ADC gain
    # correction or a replacement for missing/rejected readout energies.
    terminal = [sum(c['final_induced_keV'] * c['wiring_factor'] for c in channels
                    if low <= c['contact_id'] <= high) for low, high in ((1, 17), (18, 34))]
    out['terminal_charge_diagnostic'] = {'x_keV_equivalent': terminal[0],
        'y_keV_equivalent': terminal[1], 'mean_keV_equivalent': sum(terminal)/2,
        'scope': 'Signed native terminal charge; includes subthreshold signals; separate from peak-ADC energy'}
    spectrum['face_compatible'] = bool(spectrum['accepted'] and
        abs(spectrum['x_energy_keV'] - spectrum['y_energy_keV']) <=
        max(I.PAIR_ABS_KEV, I.PAIR_REL * max(spectrum['x_energy_keV'], spectrum['y_energy_keV'])))
    spectrum['energy_scope'] = 'Total pulse-group deposited-energy response; multiple photons are not separated'
    out['conditional_candidate_count'] = len(reconstruction.get('candidates', []))
    if out['conditional_candidate_count']:
        out['category'] = 'ambiguous_imaging'
    elif spectrum['accepted']:
        out['category'] = 'spectroscopy_only'
    else:
        out['category'] = 'unresolved_signal'
    return out
