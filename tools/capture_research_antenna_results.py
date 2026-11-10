"""Solve a bounded WLAN example or capture its actual native result views."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify_install():
    from tools.install_suite import default_destination, installation_target
    packages = files = 0
    for path in sorted((ROOT / 'releases').glob('WayriCAD-*-PCM.zip')):
        with zipfile.ZipFile(path) as archive:
            metadata = json.loads(archive.read('metadata.json'))
            target = installation_target(default_destination('10.0'), metadata['identifier'],
                                         metadata['versions'][0].get('runtime', 'swig'))
            for entry in archive.infolist():
                if entry.filename.startswith('plugins/') and not entry.is_dir():
                    installed = target / entry.filename[len('plugins/'):]
                    if installed.read_bytes() != archive.read(entry):
                        raise ValueError('Installed bytes differ: ' + str(installed))
                    files += 1
            packages += 1
    print(f'Verified {packages} packages and {files} installed files')


def solve(output):
    from quick_emerge_plugin.backend import atomic_json, run_request
    from quick_emerge_plugin.model import config_digest, source_identity
    from quick_emerge_plugin.research_antennas import example_config
    if (output / 'result.json').exists() or (output / 'request.json').exists():
        raise ValueError('Run evidence already exists; choose a new --run-dir to preserve it')
    output.mkdir(parents=True, exist_ok=True)
    board = output / 'context.kicad_pcb'
    board.write_bytes((ROOT / 'quick_emerge_plugin/tests/fixtures/region_coupon.kicad_pcb').read_bytes())
    config = example_config('yang-2016-wlan-monopole')
    config.update(f_start_hz=2.35e9, f_stop_hz=2.55e9, points=3, field_grid=41)
    config['solver'] = 'SUPERLU'
    from quick_emerge_plugin.model import validate_config
    config = validate_config(config)
    atomic_json(output / 'request.json', dict(config=config, config_sha256=config_digest(config),
                                             source=source_identity(board)))
    os.chdir(output)
    run_request(output / 'request.json')


def polarization_plot(result, destination):
    """Post-process the actual boresight Jones vector, without inventing a sweep."""
    import numpy as np
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from quick_emerge_plugin.research_antennas import axial_ratio_db
    data = result['radiation']['boresight_polarization']
    ex, ey = complex(*data['ex_ri']), complex(*data['ey_ri'])
    s0 = abs(ex)**2 + abs(ey)**2
    if s0 <= 0:
        raise ValueError('Zero boresight field cannot define polarization')
    stokes = [(abs(ex)**2-abs(ey)**2)/s0,
              2*(ex*ey.conjugate()).real/s0,
              -2*(ex*ey.conjugate()).imag/s0]
    ar = axial_ratio_db(ex, ey)
    if not np.isclose(ar, data['axial_ratio_db'], atol=1e-9):
        raise ValueError('Stored axial ratio differs from Jones-vector calculation')
    phase = np.linspace(0, 2*np.pi, 721)
    scale = np.sqrt(s0)
    x = (ex*np.exp(1j*phase)).real/scale
    y = (ey*np.exp(1j*phase)).real/scale
    figure = Figure(figsize=(12, 6), dpi=140)
    FigureCanvasAgg(figure)
    axes, bars = figure.subplots(1, 2)
    axes.plot(x, y, color='#167d91', linewidth=2)
    axes.set(xlim=(-1.05, 1.05), ylim=(-1.05, 1.05), aspect='equal',
             xlabel='Re(Ex exp(j phase)) / sqrt(S0)', ylabel='Re(Ey exp(j phase)) / sqrt(S0)',
             title='Actual boresight polarization ellipse\nEqual X/Y scale; nearly linear')
    axes.grid(alpha=.2)
    bars.bar(['S1/S0', 'S2/S0', 'S3/S0'], stokes,
             color=['#167d91', '#bd661d', '#567144'])
    bars.set(ylim=(-1.15, 1.15), ylabel='Normalized Stokes parameter',
             title=f'Axial ratio = {ar:.3f} dB\nOne +Z sample at 2.45 GHz; not an AR bandwidth')
    for i, value in enumerate(stokes):
        bars.text(i, value + (.06 if value >= 0 else -.09), f'{value:.6f}', ha='center')
    bars.axhline(0, color='#777', linewidth=.8)
    figure.suptitle('Yang WLAN | solved Jones-vector analysis | coarse screening', fontsize=14)
    figure.text(.02, .025, 'Post-processed original solver data, not a native plugin polarization panel. '
                'S3 = -2 Im(Ex conj(Ey)); no RHCP/LHCP convention claim.', fontsize=9)
    figure.tight_layout(rect=(0, .07, 1, .93))
    figure.savefig(destination)
    return dict(axial_ratio_db=ar, normalized_stokes=stokes,
                frequency_hz=result['radiation']['frequency_hz'],
                direction=data['direction'], ex_ri=data['ex_ri'], ey_ri=data['ey_ri'])


def capture(result_path, output):
    import wx
    app = wx.App(False)
    from quick_emerge_plugin.ui import QuickEMergeFrame
    result = json.loads(result_path.read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=True)
    frame = QuickEMergeFrame(Path(result['source']['path']), auto_setup=False)
    frame.SetSize((1320, 860))
    frame.Show()
    frame._apply_setup_config(result['config'], result_path)
    frame.install_result(result)
    records = []
    try:
        for view, filename in [('3D setup', 'wlan-design-2d.png'),
                               ('3D setup', 'wlan-design-3d.png'),
                               ('3D setup', 'wlan-design-open.png'),
                               ('S-parameters', 'wlan-s-parameters.png'),
                               ('Smith chart', 'wlan-smith.png'),
                               ('S-parameters', 'wlan-s-phase.png'),
                               ('Field probes', 'wlan-field-slice.png'),
                               ('Radiation pattern', 'wlan-radiation-2d.png'),
                               ('3D fields', 'wlan-field-3d.png'),
                               ('3D radiation', 'wlan-radiation-3d.png')]:
            frame.select_view(view)
            if view == '3D setup':
                frame.viewports[view].set_camera(
                    preset='Top' if filename == 'wlan-design-2d.png' else 'Isometric',
                    projection='ortho')
            if filename == 'wlan-s-phase.png':
                frame.chart_quantity.SetStringSelection('Phase')
                from quick_emerge_plugin import plots
                frame.viewports[view].render(plots.response, result, reset=True,
                                             options={'network_quantity': 'Phase'})
            frame.SetStatusText('Yang WLAN | coarse screening | 2.45 GHz fields | not paper agreement')
            for _ in range(15):
                wx.Yield()
                frame.Refresh()
                frame.Update()
                time.sleep(0.1)
            size = frame.GetClientSize()
            bitmap = wx.Bitmap(size.width, size.height)
            dc = wx.MemoryDC(bitmap)
            dc.Blit(0, 0, size.width, size.height, wx.ClientDC(frame), 0, 0)
            dc.SelectObject(wx.NullBitmap)
            destination = output / filename
            bitmap.SaveFile(str(destination), wx.BITMAP_TYPE_PNG)
            native_export = view.startswith('3D') and filename != 'wlan-design-open.png'
            if native_export:
                frame.viewports[view].export_image(str(destination))
            records.append(dict(view=view, file=filename,
                                capture_method='native framebuffer export' if native_export else 'native window client capture',
                                sha256=hashlib.sha256(destination.read_bytes()).hexdigest()))
        name = 'wlan-polarization.png'
        polarization = polarization_plot(result, output / name)
        records.append(dict(view='Boresight Jones-vector analysis', file=name,
                            capture_method='derived numerical plot; not native plugin screenshot',
                            sha256=hashlib.sha256((output / name).read_bytes()).hexdigest()))
        import vtk
        from quick_emerge_plugin import __version__
        portable = {key: value for key, value in result.items() if key != 'source'}
        samples = output / 'wlan-screening-samples.json'
        samples.write_text(json.dumps(portable, indent=2, allow_nan=False), encoding='utf-8')
        provenance = dict(captured_local_date='2026-11-10', plugin=__version__,
                          python=sys.version.split()[0], wx=wx.version(), vtk=vtk.vtkVersion.GetVTKVersion(),
                          samples_sha256=hashlib.sha256(samples.read_bytes()).hexdigest(),
                          source_context='Public synthetic region_coupon fixture; local source path omitted from portable numerical evidence',
                          result_sha256=hashlib.sha256(result_path.read_bytes()).hexdigest(),
                          config=result['config'], research_sha256=result['research_sha256'],
                          backend=result['backend'], polarization_analysis=polarization, screenshots=records,
                          limitation='Coarse screening; no mesh/boundary convergence or paper agreement')
        (output / 'provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    finally:
        frame.Close()
        for _ in range(5):
            wx.Yield()


def verify_capture(output):
    record = json.loads((output / 'provenance.json').read_text(encoding='utf-8'))
    samples = output / 'wlan-screening-samples.json'
    if hashlib.sha256(samples.read_bytes()).hexdigest() != record['samples_sha256']:
        raise ValueError('Numerical evidence digest mismatch')
    data = json.loads(samples.read_text(encoding='utf-8'))
    if 'source' in data or data['config'] != record['config']:
        raise ValueError('Portable sample custody or privacy mismatch')
    from quick_emerge_plugin.radiation_pattern import radiation_status
    angular, error = radiation_status(data)
    if angular is None:
        raise ValueError(error)
    import numpy as np
    pol = data['radiation']['boresight_polarization']
    ex, ey = complex(*pol['ex_ri']), complex(*pol['ey_ri'])
    singular = np.linalg.svd([[ex.real, -ex.imag], [ey.real, -ey.imag]], compute_uv=False)
    independent_ar = 20*np.log10(singular[0]/singular[1])
    if not np.isclose(independent_ar, record['polarization_analysis']['axial_ratio_db'], atol=1e-9):
        raise ValueError('Polarization plot disagrees with independent ellipse SVD')
    for image in record['screenshots']:
        path = output / image['file']
        if hashlib.sha256(path.read_bytes()).hexdigest() != image['sha256']:
            raise ValueError('Image digest mismatch: ' + image['file'])
        if path.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError('Not a PNG: ' + image['file'])
    print(f'Verified original angular data, portable numerical evidence and {len(record["screenshots"])} image digests')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['solve', 'capture', 'verify', 'verify-install'])
    parser.add_argument('--run-dir', type=Path, default=ROOT / '.validation/research-screenshots')
    parser.add_argument('--output', type=Path, default=ROOT / 'examples/quick_emerge/research_antennas/images')
    args = parser.parse_args()
    if args.mode == 'solve':
        solve(args.run_dir.resolve())
    elif args.mode == 'capture':
        capture(args.run_dir.resolve() / 'result.json', args.output.resolve())
    elif args.mode == 'verify':
        verify_capture(args.output.resolve())
    else:
        verify_install()
