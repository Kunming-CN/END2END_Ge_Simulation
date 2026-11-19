"""Join scored Ge photon chords to charged-secondary births for the two Co histories."""

from math import atan2, degrees, dist, fsum, hypot

from gegi_two_site_geometry_reference import MATCH_TOL_MM, photon_steps


def direction(start, end):
    return tuple(b - a for a, b in zip(start, end, strict=True))


def angle_deg(a, b):
    if not hypot(*a) or not hypot(*b):
        return None
    cross = (a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0])
    return degrees(atan2(hypot(*cross), fsum(x*y for x, y in zip(a, b, strict=True))))


def photon_path(folder, done, raw_id, root_track_id, anchors, hashes, *, source_position_mm):
    """Keep original STEP row IDs and report which scored vertices have a unique birth match."""
    rows = photon_steps(folder, done, [raw_id], hashes)[raw_id]
    steps = sorted((row for row in rows if row['photon_trackid'] == root_track_id),
                   key=lambda row: (row['pre_time_ns'], row['raw_row_index']))
    if not steps:
        raise ValueError(f'No scored Ge photon steps for event {raw_id}, track {root_track_id}')

    records, matched = [], []
    for i, step in enumerate(steps):
        pre, post = step['pre_position_mm'], step['post_position_mm']
        matches = [j for j, birth in enumerate(anchors) if step['pre_time_ns'] <= birth['birth_time_ns']
                   and dist(post, birth['birth_position_mm']) <= MATCH_TOL_MM]
        entry = dict(step, matching_anchor_indices=matches)
        if len(matches) == 1:
            j, = matches
            matched.append(j)
            birth = anchors[j]
            entry.update(birth_process=birth['birth_process'], birth_time_ns=birth['birth_time_ns'],
                         post_to_birth_mm=dist(post, birth['birth_position_mm']))
        if i + 1 < len(steps):
            following = steps[i+1]
            gap = dist(post, following['pre_position_mm'])
            entry['gap_to_next_scored_step_mm'] = gap
            entry['outgoing_turn_deg'] = (angle_deg(direction(pre, post),
                                                    direction(following['pre_position_mm'], following['post_position_mm']))
                                          if gap <= MATCH_TOL_MM else None)
        records.append(entry)

    first = steps[0]
    return dict(raw_event_id=raw_id, photon_track_id=root_track_id, steps=records,
                all_vertices_match_birth_order=(len(matched) == len(steps) == len(anchors)
                                                and matched == list(range(len(anchors)))),
                direct_scored_step_edep_keV=fsum(row['deposited_energy_keV'] for row in steps),
                programmed_source_position_mm=source_position_mm,
                incoming_direction_difference_from_programmed_source_deg=angle_deg(
                    direction(source_position_mm, first['post_position_mm']),
                    direction(first['pre_position_mm'], first['post_position_mm'])),
                ge_entry_kinetic_energy_keV=None,
                definition='Each row is a scored Ge chord of the depositing primary photon. Its local STEP '
                           'deposition excludes energy deposited by descendants. Turns use contiguous chords. '
                           'The Ge STEP table does not record incident kinetic energy.')
