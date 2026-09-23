"""Optional Nubis SignalIntegrity interoperability; no KiCad or GUI imports.

The route exporter describes an explicitly idealized two-port. The importer
delegates Touchstone decoding to the separately installed upstream library.
"""
from __future__ import annotations

import cmath
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys


LIMITATIONS = [
    'Frequency-domain network data is not protocol compliance or a board field solution.',
    'Port numbering, reference planes and model provenance must be reviewed by the user.',
    'No automatic differential pairing, mixed-mode conversion, eye or BER result is inferred.',
]


def run_desktop(*, python=None, project=None, check=False):
    """Explicitly run the complete upstream desktop in an isolated process.

    Wait for closure so startup failures remain visible. Preflight imports the
    desktop only in a child: upstream modifies its own global configuration on
    import. A successful preflight does not establish a working display server.
    """
    interpreter = Path(python or sys.executable).resolve()
    if not interpreter.is_file():
        raise ValueError('Choose the Python executable in an environment with SignalIntegrity installed.')
    command = [str(interpreter), '-m', 'SignalIntegrity.App.SignalIntegrityApp']
    if project is not None:
        project = Path(project).resolve()
        if not project.is_file() or project.suffix.lower() != '.si':
            raise ValueError('Choose an existing upstream .si project, or omit it to start a new project.')
        command.append(str(project))
    probe = ('import json; import tkinter; '
             'import SignalIntegrity.App.SignalIntegrityApp; '
             'from SignalIntegrity.__about__ import __version__; '
             'print(json.dumps({"version": __version__}))')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        result = subprocess.run([str(interpreter), '-c', probe], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=60, creationflags=flags)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('SignalIntegrity desktop dependency check timed out after 60 seconds.') from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise RuntimeError('SignalIntegrity desktop dependencies are unavailable. Install SignalIntegrity==1.5.2 '
                           'and working Tk in the chosen Python environment. ' + detail)
    try:
        version = json.loads(result.stdout.strip().splitlines()[-1])['version']
    except (ValueError, IndexError, KeyError) as exc:
        raise RuntimeError('SignalIntegrity desktop preflight returned an invalid version response.') from exc
    report = {'schema':'wayricad.signalintegrity-desktop/v1', 'status':'DEPENDENCIES_AVAILABLE',
              'backend_version':version, 'python':str(interpreter),
              'project':str(project) if project else None,
              'scope':'Complete external upstream desktop; native Quick SI embedding is not provided.'}
    if not check:
        # Inherit output so upstream tracebacks are visible; no shell interpolation.
        # The caller explicitly requested a visible interactive application.
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, creationflags=flags)
        if completed.returncode:
            raise RuntimeError(f'SignalIntegrity desktop exited with code {completed.returncode}; inspect its diagnostic output.')
        report['status'] = 'CLOSED'
    return report


def _positive(value, name, allow_zero=False):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(name + ' must be a finite number.') from exc
    if not math.isfinite(result) or result < 0 or (not allow_zero and result == 0):
        raise ValueError(name + ' must be finite and ' + ('nonnegative.' if allow_zero else 'positive.'))
    return result


def ideal_line_touchstone(report, *, stop_hz, points=1001, reference_ohm=50.):
    """Export a lossless uniform line with equal real port references, DC included.

    ABCD = [[cos(theta), j*Zc*sin(theta)], [j*sin(theta)/Zc, cos(theta)]].
    S21 = 2/(A+B/R+C*R+D); S11 = (A+B/R-C*R-D)/denominator.
    The source/load resistances are intentionally not part of this network.
    """
    if report.get('schema') != 'wayricad.quick-si/v1' or report.get('status') != 'SCREENED':
        raise ValueError('Export requires a complete SCREENED Quick SI route report.')
    path = report.get('path', {})
    if not isinstance(path, dict):
        raise ValueError('Route geometry must be a report object.')
    if report.get('terminal_count') != 2 or path.get('zone_count', 0):
        raise ValueError('The ideal line export requires a two-terminal route without zone corridors.')
    zc = _positive(report.get('z0_ohm'), 'Uniform line impedance')
    delay = _positive(report.get('delay_ns'), 'One-way delay') * 1e-9
    stop_hz = _positive(stop_hz, 'Stop frequency in Hz')
    reference_ohm = _positive(reference_ohm, 'Port reference impedance')
    if not math.isfinite(zc / reference_ohm) or not math.isfinite(reference_ohm / zc):
        raise ValueError('Impedance ratio exceeds numerical range.')
    if isinstance(points, bool) or not isinstance(points, int) or not 2 <= points <= 10001:
        raise ValueError('Use an integer from 2 to 10001 frequency points.')
    if not math.isfinite(stop_hz * delay * 2 * math.pi):
        raise ValueError('Frequency and delay product is too large.')
    comments = [
        'WayriCAD Quick SI: IDEAL LOSSLESS UNIFORM LINE; NOT EXTRACTED BOARD S-PARAMETERS',
        'Port 1 = selected source pad; port 2 = selected receiver pad.',
        'No vias, stubs, coupling, dielectric/conductor loss, source or load model.',
        f'Uniform Z0 {zc:.12g} ohm; one-way delay {delay:.12g} s.',
    ]
    for key in ('z0_source', 'delay_source', 'board_sha256'):
        if key in report:
            comments.append(key + ': ' + ' '.join(str(report[key]).splitlines()))
    lines = ['! ' + item for item in comments]
    lines.append(f'# Hz S RI R {reference_ohm:.12g}')
    for index in range(points):
        frequency = stop_hz * (index / (points - 1))
        theta = 2 * math.pi * (frequency * delay)
        a = math.cos(theta)
        b = 1j * zc * math.sin(theta) / reference_ohm
        c = 1j * reference_ohm * math.sin(theta) / zc
        denominator = 2 * a + b + c
        reflection = (b - c) / denominator
        transmission = 2 / denominator
        if not all(math.isfinite(v) for x in (reflection, transmission) for v in (x.real, x.imag)):
            raise ValueError('Line parameters exceed numerical range.')
        # Touchstone two-port order is S11, S21, S12, S22.
        values = [frequency]
        for value in (reflection, transmission, transmission, reflection):
            values.extend((value.real, value.imag))
        lines.append(' '.join(f'{value:.16g}' for value in values))
    return '\n'.join(lines) + '\n'


def analyze_touchstone(source, *, to_port=2, from_port=1):
    """Read bounded Touchstone 1.0 S data via upstream; retain complex response.

    Validate before upstream parsing because its parser accepts incomplete rows
    and silently sorts/deduplicates frequencies. Never turn malformed input into
    an apparently successful report. Noise sections and Touchstone 2 are outside
    this initial adapter's contract.
    """
    source = Path(source).resolve()
    match = re.fullmatch(r'\.s([1-9][0-9]*)p', source.suffix, re.IGNORECASE)
    if not source.is_file() or not match:
        raise ValueError('Choose an existing Touchstone .sNp file.')
    ports = int(match.group(1))
    if ports > 32 or source.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Use at most 32 ports and a file no larger than 16 MiB.')
    if any(isinstance(p, bool) or not isinstance(p, int) or not 1 <= p <= ports for p in (to_port, from_port)):
        raise ValueError(f'Port numbers must be integers between 1 and {ports}.')
    raw = source.read_bytes()
    text = raw.decode('utf-8-sig')
    tokens = []
    option = None
    for line in text.splitlines():
        line = line.split('!', 1)[0].strip()
        if not line:
            continue
        if line.startswith('#'):
            if option is not None or tokens:
                raise ValueError('Use one Touchstone option line before the data.')
            option = line[1:].lower().split()
            if (len(option) != 5 or option[0] not in ('hz', 'khz', 'mhz', 'ghz')
                    or option[1] != 's' or option[2] not in ('ri', 'ma', 'db') or option[3] != 'r'):
                raise ValueError('Use Touchstone 1.0: # Hz|kHz|MHz|GHz S RI|MA|DB R <ohms>.')
            _positive(option[4], 'Port reference impedance')
        else:
            if line.startswith('['):
                raise ValueError('Touchstone 2.0 is not supported by this adapter; export Touchstone 1.0.')
            tokens.extend(line.split())
    if option is None:
        raise ValueError('Supply an explicit Touchstone frequency unit, S format and reference option line.')
    width = 1 + 2 * ports * ports
    if not tokens or len(tokens) % width or len(tokens) // width > 10001:
        raise ValueError('Use 1–10001 complete frequency records, without a noise section.')
    try:
        numbers = [float(token) for token in tokens]
    except ValueError as exc:
        raise ValueError('Touchstone data contains a nonnumeric value.') from exc
    if not all(math.isfinite(value) for value in numbers):
        raise ValueError('Touchstone data must contain only finite values.')
    frequencies = numbers[::width]
    if frequencies[0] < 0 or any(b <= a for a, b in zip(frequencies, frequencies[1:])):
        raise ValueError('Frequencies must be nonnegative and strictly increasing; duplicates are rejected.')
    try:
        from SignalIntegrity.Lib.SParameters.SParameterFile import SParameterFile
        from SignalIntegrity.__about__ import __version__
    except ImportError as exc:
        raise RuntimeError('Install SignalIntegrity==1.5.2 in the Python environment running wayricad-si '
                           '(python -m pip install SignalIntegrity==1.5.2). No package is downloaded automatically.') from exc
    try:
        # Pass the validated snapshot; a concurrent file edit cannot alter parsing.
        network = SParameterFile(str(source), text=text.splitlines(keepends=True))
        response = [complex(value) for value in network.Response(to_port, from_port)]
        hz = [float(value) for value in network.f()]
        reference = float(network.m_Z0)
    except Exception as exc:
        raise ValueError('SignalIntegrity could not read this network: ' + str(getattr(exc, 'message', '') or exc)) from exc
    if len(response) != len(frequencies) or not all(math.isfinite(f) for f in hz):
        raise ValueError('SignalIntegrity returned inconsistent or non-finite frequency data.')
    if not all(math.isfinite(v) for z in response for v in (z.real, z.imag, abs(z))):
        raise ValueError('SignalIntegrity returned a non-finite response.')
    return {
        'schema': 'wayricad.signalintegrity-network/v1', 'status': 'ANALYZED',
        'backend': {'name': 'Nubis SignalIntegrity', 'version': __version__, 'license': 'GPL-3.0-or-later'},
        'source': str(source), 'source_sha256': hashlib.sha256(raw).hexdigest(),
        'ports': ports, 'to_port': to_port, 'from_port': from_port, 'reference_ohm': reference,
        'frequency_hz': hz, 'response_real': [v.real for v in response],
        'response_imag': [v.imag for v in response],
        'magnitude_db': [20 * math.log10(abs(v)) if abs(v) > 0 else None for v in response],
        'phase_deg': [math.degrees(cmath.phase(v)) if abs(v) > 0 else None for v in response],
        'limitations': LIMITATIONS + ['Zero magnitude is reported as null dB and phase, not a finite floor.'],
    }
