"""Progressive workspace actions and custody-checked plot exports."""
from pathlib import Path
import os
import tempfile

import wx

from .model import config_digest, source_identity


def output_path(raw, extension, parent, *, confirm_added_extension=False):
    """Add a missing extension without bypassing overwrite confirmation."""
    path = Path(raw)
    if not path.suffix:
        path = path.with_suffix(extension)
        if confirm_added_extension and path.exists():
            answer = wx.MessageBox('Replace the existing '+path.name+'?', 'Replace output',
                                   wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION, parent)
            if answer != wx.YES: return None
    if path.suffix.lower() != extension:
        raise ValueError('Choose a '+extension+' filename for this output.')
    return path


def result_views(result, dimension):
    """Return only spatial views whose solved samples are present."""
    result = result or {}
    names = []
    if result.get('field') or result.get('thermal'):
        names.append('Field probes' if dimension == '2D' else '3D fields')
    if dimension == '3D' and result.get('radiation'):
        names.append('3D radiation')
    return names


def plot_name(frame, dimension):
    """Resolve the requested dimension without substituting an unavailable field."""
    if frame.results_button.GetValue():
        if dimension == '2D' and frame.current_group == 'Charts':
            return frame.tabs.GetPageText(frame.tabs.GetSelection())
        names = result_views(frame.result, dimension)
        if not names:
            raise ValueError('This result has no '+dimension+' field. Turn off Show results to export geometry.')
        selected = frame.tabs.GetPageText(frame.tabs.GetSelection())
        return selected if selected in names else names[0]
    return 'PCB enclosure' if dimension == '2D' else '3D setup'


def check_plot_source(frame, name):
    """Check current setup/source before and after writing a figure."""
    current = source_identity(frame.session.board)
    if frame.result is not None:
        from .reporting import validate_report_result
        validate_report_result(frame.result, expected_config=frame.config(), expected_source=current)
    elif frame.session.review is not None:
        review = frame.session.review
        if current != review['source'] or config_digest(frame.config()) != review['config_sha256']:
            raise ValueError('Board or setup changed; Preview again before exporting geometry.')
    elif name == 'PCB enclosure' and frame.region_listing is not None:
        if frame.region_listing['source'] != current:
            raise ValueError('Board changed; reload its outlines before exporting.')
    else:
        raise ValueError('Preview geometry before exporting this plot.')
    if frame.viewports[name].renderer is None:
        raise ValueError('This view has no geometry or solved data to export.')


def export_plot(frame, dimension, path=None):
    """Atomically save the selected 2D plot or current 3D camera as PNG."""
    name = plot_name(frame, dimension)
    check_plot_source(frame, name)
    if path is None:
        with wx.FileDialog(frame, 'Save '+dimension+' plot',
                defaultDir=str(frame.session.board.parent),
                defaultFile=frame.session.board.stem+'-emerge-'+dimension.lower()+'.png',
                wildcard='PNG image (*.png)|*.png', style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return None
            path = output_path(dialog.GetPath(), '.png', frame, confirm_added_extension=True)
            if path is None: return None
    path = output_path(path, '.png', frame)
    frame.select_view(name)
    viewport = frame.viewports[name]
    viewport.refresh_canvas()
    descriptor, temporary = tempfile.mkstemp(prefix='.'+path.stem+'-', suffix='.png', dir=path.parent)
    os.close(descriptor)
    try:
        if hasattr(viewport, 'export_image'):
            viewport.export_image(temporary)
        else:
            viewport.canvas.draw()
            viewport.figure.savefig(temporary, dpi=200, format='png')
        if Path(temporary).read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError('The renderer did not produce a PNG; the destination was preserved.')
        check_plot_source(frame, name)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    frame.SetStatusText('Saved '+dimension+' plot: '+path.name+(' · current 3D camera image' if dimension=='3D' else ''))
    return path


def build_export_menu(frame):
    """Offer figures and reports together, with unavailable outputs disabled."""
    menu = wx.Menu()
    for dimension, label in (('2D', 'Save 2D plot (PNG)…'), ('3D', 'Save 3D view (PNG)…')):
        item = menu.Append(wx.ID_ANY, label)
        try:
            available = frame.viewports[plot_name(frame, dimension)].renderer is not None
        except ValueError:
            available = False
        item.Enable(available)
        item.SetHelp('Static image of the current view; the native 3D viewer remains interactive.' if available
                     else 'Preview this geometry or solve a study that provides this field.')
        menu.Bind(wx.EVT_MENU, lambda event, dimension=dimension: frame.export_plot(dimension), id=item.GetId())
    menu.AppendSeparator()
    for label, kind in (('Preview report', 'preview'), ('Export HTML report…', 'html'), ('Export PDF report…', 'pdf')):
        item = menu.Append(wx.ID_ANY, label)
        item.Enable(frame.result is not None and not getattr(frame, 'report_busy', False))
        item.SetHelp('Reports require completed, current simulation results.')
        def report(event, kind=kind):
            if kind == 'preview': frame.navigate('Report')
            frame.generate_report(kind)
        menu.Bind(wx.EVT_MENU, report, id=item.GetId())
    return menu


def build_more_menu(frame):
    """Keep specialist views and controls one click away from the main canvas."""
    menu = wx.Menu()
    for label, group, available in (
            ('Result charts', 'Charts', bool(frame.result and frame.result.get('s_parameters'))),
            ('Result summary', 'Results', frame.result is not None)):
        item = menu.Append(wx.ID_ANY, label); item.Enable(available)
        menu.Bind(wx.EVT_MENU, lambda event, group=group: frame.navigate(group), id=item.GetId())
    menu.AppendSeparator()
    details = menu.AppendCheckItem(wx.ID_ANY, 'Probe details')
    details.Check(frame.visual_splitter.IsSplit())
    menu.Bind(wx.EVT_MENU, frame.toggle_inspector, id=details.GetId())
    settings = menu.Append(wx.ID_ANY, 'Display settings…')
    menu.Bind(wx.EVT_MENU, frame.show_view_options, id=settings.GetId())
    controls = menu.AppendCheckItem(wx.ID_ANY, 'Viewport controls')
    controls.Check(getattr(frame, 'viewport_controls_visible', False))
    def show_controls(event):
        frame.viewport_controls_visible = controls.IsChecked()
        for viewport in frame.viewports.values(): viewport.show_controls(frame.viewport_controls_visible)
    menu.Bind(wx.EVT_MENU, show_controls, id=controls.GetId())
    focus = menu.AppendCheckItem(wx.ID_ANY, 'Focus view')
    focus.Check(frame.focus_button.GetValue())
    def focus_view(event):
        frame.focus_button.SetValue(focus.IsChecked()); frame.focus_view()
    menu.Bind(wx.EVT_MENU, focus_view, id=focus.GetId())
    return menu
