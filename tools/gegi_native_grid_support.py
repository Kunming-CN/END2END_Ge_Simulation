"""Read saved native weighting-grid axes only; no cache load or simulation.

Fixed lateral validation (11,26), z=0, fractions (-.2,-.2). Geometry and electric
field axes absent from saved evidence remain explicitly unavailable.
"""
from __future__ import annotations
import bisect
import itertools
import json
from pathlib import Path
import struct
import time

import gegi_full34_pilot as P
from gegi_full34_pilot import W,ROOT

AXES = '.local/gegi-10m/signal-recovery-v1/validation/boundary-grid-pilot/grid-comparison/multichannel-grid.json'
RESULTS = P.CALIBRATION+'/full34-lateral-pilot/results'


def float32(x):
    return struct.unpack('<f',struct.pack('<f',x))[0]


def support(ticks,coordinate_mm):
    # Match K.injection's native Float32 millimetres-to-metres conversion.
    coordinate=float32(float32(coordinate_mm)/float32(1000))
    index=bisect.bisect_right(ticks,coordinate)-1
    W.require(0<=index<len(ticks)-1,'Fixed point outside recorded native grid.')
    return {'native_coordinate_m':coordinate,'lower_index_zero_based':index,
        'lower_mm':ticks[index]*1000,'upper_mm':ticks[index+1]*1000,
        'exact_tick':coordinate==ticks[index]}


def main():
    started=time.perf_counter();axes_path=ROOT/AXES;native=W.read(axes_path)
    result_root=ROOT/RESULTS;request_path=result_root.parent/'request.json';req=W.read(request_path)
    identity_path=ROOT/req['source_bank']['identity']['ref'];identity=W.read(identity_path)
    W.require(native['field_cache_sha256']==req['field_cache']['sha256'] and
        [g['contact_id'] for g in native['grids']]==list(range(1,35)),'Recorded grid/cache identity changed.')
    grid=native['grids'][0];axes=grid['axis_ticks_m']
    same=all(g['shape']==grid['shape'] and g['axis_ticks_m']==axes for g in native['grids'])
    W.require(same,'All34 native weighting grids are not identical.')
    target=next(p for p in req['points'] if p['role']=='validation' and p['contact_ids']==[11,26] and
        p['lateral_offset_pitch_fraction']==[-.2,-.2] and p['position_mm'][2]==0)
    training=[p for p in req['points'] if p['role']=='train' and p['contact_ids']==[11,26] and p['position_mm'][2]==0]
    W.require(len(training)==9,'Fixed saved training stencil changed.')
    def location(point):
        return {'record_ref':point['record_ref'],'position_mm':point['position_mm'],
            'lateral_offset_pitch_fraction':point['lateral_offset_pitch_fraction'],
            'x_cell':support(axes[0],point['position_mm'][0]),'y_cell':support(axes[1],point['position_mm'][1])}
    target_location=location(target);x=target_location['x_cell'];y=target_location['y_cell']
    corners=[[a,b,0.] for a,b in itertools.product((x['lower_mm'],x['upper_mm']),(y['lower_mm'],y['upper_mm']))]
    xc=identity['channels'][10]['strip_center_mm'];yc=identity['channels'][25]['strip_center_mm'];px,py=target['strip_pitch_mm']
    nominal=all(xc-px/2<a<xc+px/2 and yc-py/2<b<yc+py/2 for a,b,z in corners)
    output={'kind':'gegi_saved_native_grid_support_v1','status':'saved_axes_complete_geometry_and_Efield_unavailable',
        'field_cache_sha256':native['field_cache_sha256'],'input_bindings':[P.binding(axes_path),P.binding(request_path),P.binding(identity_path)],
        'all34_weighting_grid_identity':{'same_shape_and_every_axis_tick':same,'contacts':list(range(1,35)),'shape':grid['shape'],
            'basis':'Existing saved native axis export; raw cache SHA unchanged. No new field/cache load.'},
        'target':target_location,'training_z0':list(map(location,training)),
        'target_coarse_training_cell_indices':{'x':sorted({support(axes[0],p['position_mm'][0])['lower_index_zero_based'] for p in training
            if p['lateral_offset_pitch_fraction'][0] in (-.4,0.)}),
            'y':sorted({support(axes[1],p['position_mm'][1])['lower_index_zero_based'] for p in training
            if p['lateral_offset_pitch_fraction'][1] in (-.4,0.)})},
        'four_native_XY_corners_mm':corners,
        'nominal_pitch_box_assignment':{'contact_ids':[11,26],'all_corners_inside':nominal,
            'scope':'Pitch-box containment only; this does not establish native semiconductor/contact membership.'},
        'native_corner_geometry':{'status':'unavailable','inside_semiconductor':None,'contact_ids':None,
            'reason':'Not exported by existing axes evidence. Owner requested pause before any cache load; no new native geometry query performed.'},
        'electric_field_vs_weighting_axes':{'status':'unavailable',
            'reason':'Existing native grid export contains weighting axes only; no electric-field axis snapshot.'},
        'interpretation':'Training XY samples straddle multiple native weighting-grid cells. This is grid-support evidence, not proof that complete drift waveforms are bilinear in injection XY.',
        'new_cache_loads':0,'new_drifts':0,'new_solves':0,'new_calibration_injections':0,
        'new_corner_injection_request_prepared':False,'tool':P.binding(Path(__file__)),
        'elapsed_seconds':time.perf_counter()-started}
    path=result_root/'grid-support.json'
    with path.open('xb') as stream:stream.write(W.encoded(output)+b'\n')
    print(json.dumps({'output':str(path),'sha256':W.sha(path),'target':target_location,
        'corners_mm':corners,'all34_same_grid':same,'nominal_pixel_assignment':nominal,
        'native_geometry_and_Efield':'unavailable_no_cache_load'},indent=2))


if __name__=='__main__':main()
