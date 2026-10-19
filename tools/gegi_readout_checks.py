"""Independent saved-signal checks for the frozen GeGI nominal electronics.

No field, transport, drift or calibration injection is generated. The analytic
response below verifies the existing exactly pole-zero-matched linear circuit;
it is not a new electronics profile or a measured GeGI transfer function.
"""
from __future__ import annotations
import math
import numpy as np

ELECTRON_C = 1.602176634e-19


def matched_response(time_ns, wired_charge_keV, recipe, horizon_ns=None):
    """Exact interval-current convolution, independently of Julia's state matrix.

    For tau_PZ=tau_feedback, a delta charge produces
    gain*Q/Cf * (t/tau_s)^2 exp(-t/tau_s)/2. Native charge differences represent
    constant current over each original interval. Integrate this impulse over
    the interval rather than treating a finite current bin as a delta charge.
    """
    c, cal = recipe['readout_config'], recipe['electronics_calibration']
    if c['pole_zero_tau_us'] != c['feedback_tau_us']:
        raise ValueError('Analytic check requires matched pole-zero/feedback times')
    if c.get('peak_gate_start_ns') is not None or c.get('peak_gate_end_ns') is not None:
        raise ValueError('Analytic check requires the saved ungated profile')
    t, q = np.asarray(time_ns, float), np.asarray(wired_charge_keV, float)
    dt = cal['time_step_ns']
    if (len(t) < 2 or t.shape != q.shape or not np.isfinite(q).all()
            or not np.allclose(t, np.arange(len(t))*dt, rtol=0, atol=1e-8)
            or t[0] != 0 or q[0] != 0):
        raise ValueError('Invalid original uniform charge grid')
    if horizon_ns is not None:
        n = int(math.ceil(horizon_ns/dt))
        q = q[:n]
    else:
        n = len(q) + int(math.ceil(1000*c['tail_shaping_constants']*c['shaping_tau_us']/dt))
    tau = 1000*c['shaping_tau_us']
    # Five-point Gauss-Legendre integrates each analytic smooth one-ns bin to
    # floating-point precision without cancellation between nearly equal CDFs.
    nodes, weights = np.polynomial.legendre.leggauss(5)
    left = np.arange(n-1)*dt
    u = (left[:, None]+dt*(nodes+1)/2)/tau
    kernel = ((u*u*np.exp(-u)/2)@weights)/2
    scale = c['gain']*1000/recipe['ionisation_energy_eV']*ELECTRON_C/(c['feedback_capacitance_pF']*1e-12)
    size = 1 << (n+len(q)-2).bit_length()
    shaped = np.zeros(n)
    shaped[1:] = np.fft.irfft(np.fft.rfft(np.diff(q), size)*np.fft.rfft(kernel, size), size)[:n-1]*scale
    peak_index = int(np.argmax(shaped)); peak = float(shaped[peak_index])
    code = 0 if peak <= 0 else min(2**c['adc_bits']-1, int(math.floor(peak/cal['adc_lsb_V'])))
    return {'peak_V': peak, 'peak_time_ns': peak_index*dt, 'adc_code': code,
            'analog_energy_keV': peak/cal['volts_per_keV'],
            'adc_midpoint_energy_keV': (code+.5)*cal['adc_lsb_V']/cal['volts_per_keV'],
            'charge_balance_C': float(np.diff(q).sum()-(q[-1]-q[0]))*1000/recipe['ionisation_energy_eV']*ELECTRON_C,
            'sample_count': n}


def verify_channel(saved, native, recipe, horizon_ns=None):
    result = matched_response(native['time_ns'],
        np.asarray(native['signed_induced_keV'])*saved['wiring_factor'], recipe, horizon_ns)
    voltage_error = abs(result['peak_V']-saved['peak_V'])
    # Near-zero induction-only numerical peaks can have a different argmax;
    # amplitude and ADC identities remain meaningful, timing there does not.
    tolerance = 2e-10*max(1., abs(saved['peak_V']))
    if voltage_error > tolerance or result['adc_code'] != saved['adc_code']:
        raise ValueError('Saved analog peak/ADC disagrees with analytic circuit')
    if saved.get('accepted') and not math.isclose(result['adc_midpoint_energy_keV'],
            saved['reconstructed_energy_keV'], rel_tol=0, abs_tol=1e-9):
        raise ValueError('Fixed gain ADC-energy identity changed')
    return {'contact_id': saved['contact_id'], 'peak_absolute_error_V': voltage_error,
            'adc_code_equal': True, 'energy_gain_equal': True,
            'sample_count': result['sample_count'], 'charge_balance_C': result['charge_balance_C']}
