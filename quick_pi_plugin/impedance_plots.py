"""Impedance magnitude/reference plots from actual sampled complex matrices."""
import math
import sys

TERMS = ((0, 0, 'Z11'), (0, 1, 'Z12'), (1, 0, 'Z21'), (1, 1, 'Z22'))


def _finite_number(value):
    return (not isinstance(value,bool) and isinstance(value,(int,float))
            and abs(value)<=sys.float_info.max and math.isfinite(value))


def samples(result):
    if not isinstance(result,dict) or not isinstance(result.get('units'),dict) or (
            result['units'].get('impedance') != 'ohm' or result['units'].get('frequency') != 'Hz'):
        raise ValueError('Impedance data must explicitly declare ohm and Hz units.')
    rows = result.get('frequencies')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
        raise ValueError('Provide 1 to 10,000 sampled impedance rows.')
    frequencies, matrices = [], []
    for row in rows:
        if not isinstance(row,dict):raise ValueError('Every frequency sample must be an object.')
        frequency = row.get('frequency_hz')
        if not _finite_number(frequency) or frequency <= 0:
            raise ValueError('Frequencies must be finite positive hertz.')
        if frequencies and frequency <= frequencies[-1]:
            raise ValueError('Reference frequencies must increase strictly.')
        matrix = row.get('z_ohm')
        if not isinstance(matrix, list) or len(matrix) != 2 or any(not isinstance(line,list) or len(line)!=2 for line in matrix):
            raise ValueError('Each sample needs the complete 2 by 2 complex matrix.')
        values = []
        for line in matrix:
            for value in line:
                if not isinstance(value,dict) or set(value) != {'real','imag'}:
                    raise ValueError('Complex entries require real and imag values in ohms.')
                parts = [value[key] for key in ('real','imag')]
                if any(not _finite_number(v) for v in parts):
                    raise ValueError('Impedance samples must be finite numbers.')
                if not math.isfinite(math.hypot(*parts)):
                    raise ValueError('Impedance magnitudes must be finite and representable.')
                values.append(complex(*parts))
        frequencies.append(float(frequency));matrices.append(values)
    return frequencies, matrices


def matched_differences(result, reference, column):
    """No extrapolation or interpolation: compare only common sampled frequencies."""
    import bisect
    frequency, values = samples(result)
    ref_frequency, ref_values = samples(reference)
    points, differences = [], []
    for f, row in zip(frequency, values):
        index = bisect.bisect_left(ref_frequency, f)
        if index < len(ref_frequency) and ref_frequency[index] == f:
            candidates = [index]
        else:
            candidates = [i for i in (index-1,index) if 0 <= i < len(ref_frequency)
                          and math.isclose(f,ref_frequency[i],rel_tol=1e-9,abs_tol=0.)]
        if len(candidates) != 1:
            continue
        left,right = abs(row[column]),abs(ref_values[candidates[0]][column])
        if left > 0 and right > 0:
            points.append(f);differences.append(20*(math.log10(left)-math.log10(right)))
    return points, differences


def draw_magnitudes(figure, result, reference=None, reference_label='Imported reference'):
    frequency, values = samples(result)
    probes = {}
    ref_frequency, ref_values = samples(reference) if reference else (None,None)
    axes = figure.subplots(2 if reference else 1, 4, squeeze=False,
                           gridspec_kw={'height_ratios':[3,1]} if reference else None)
    for column, (_,_,name) in enumerate(TERMS):
        axis = axes[0,column]
        z = [row[column] for row in values]
        # Exact zeros have no logarithmic magnitude; preserve them in probes/JSON.
        magnitude = [abs(v) if abs(v)>0 else float('nan') for v in z]
        axis.loglog(frequency,magnitude,color='#2476d8',label='Current model',linewidth=1.7)
        axis.set_title('|'+name+'|');axis.set_ylabel('Impedance (ohm)')
        axis.set_xlabel('Frequency (Hz)');axis.grid(True,which='both',alpha=.24)
        probes[axis]=[('Current model',frequency,z)]
        if reference:
            rz = [row[column] for row in ref_values]
            axis.loglog(ref_frequency,[abs(v) if abs(v)>0 else float('nan') for v in rz],
                        '--',color='#d54b42',label=str(reference_label)[:80],linewidth=1.3)
            probes[axis].append((str(reference_label)[:80],ref_frequency,rz))
            difference = axes[1,column]
            common,delta = matched_differences(result,reference,column)
            difference.semilogx(common,delta,color='#2476d8',marker='.',linewidth=1.3)
            difference.axhline(0,color='#61717b',linewidth=.7)
            difference.set_xlabel('Frequency (Hz)');difference.set_ylabel('Model - reference (dB)')
            difference.grid(True,which='both',alpha=.24)
            probes[difference]=[('Model - reference',common,[complex(value,0) for value in delta],'dB')]
            if not common:difference.set_title('No common nonzero samples',fontsize=8)
        if column==0:axis.legend(fontsize=7)
    return probes


def probe_text(probes, axis, frequency):
    if axis not in probes or not _finite_number(frequency) or frequency <= 0:
        return ''
    log_frequency = math.log(frequency)
    lines=[]
    for item in probes[axis]:
        label,fs,zs,*units=item
        if not fs:continue
        index=min(range(len(fs)),key=lambda i:abs(math.log(fs[i])-log_frequency))
        value=zs[index]
        if units:
            lines.append(f'{label}: {fs[index]:.8g} Hz; {value.real:.8g} {units[0]}')
            continue
        lines.append(f'{label}: {fs[index]:.8g} Hz; |Z|={abs(value):.8g} ohm; '
                     f'Re={value.real:.8g}, Im={value.imag:.8g} ohm; '
                     f'phase={math.degrees(math.atan2(value.imag,value.real)):.5g} deg')
    return '\n'.join(lines)
