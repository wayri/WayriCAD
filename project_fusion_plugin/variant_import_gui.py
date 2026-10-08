"""Native source-variant and destination-configuration choices for Fusion."""
from __future__ import annotations

import copy
from pathlib import Path
import wx

from .model import MergeError
from .variants import DEFAULT, detect_variants

MODES = ('base', 'merge', 'separate')


def apply_window_icon(window):
    """Use Fusion's bundled icon in its native windows as well as KiCad's menu."""
    path = Path(__file__).with_name('icon.png')
    if not path.is_file():
        return
    if not wx.Image.FindHandler(wx.BITMAP_TYPE_PNG):
        wx.Image.AddHandler(wx.PNGHandler())
    icon = wx.Icon(str(path), wx.BITMAP_TYPE_PNG)
    if icon.IsOk():
        icons = wx.IconBundle(); icons.AddIcon(icon); window.SetIcons(icons)


def disposition_label(spec):
    """Describe the destination without conflating it with the source choice."""
    mode = getattr(spec, 'variant_mode', 'base')
    if mode == 'base':
        return 'Imported base'
    name = getattr(spec, 'destination_variant', None) or '[Choose destination]'
    return ('Merge into ' if mode == 'merge' else 'Separate: ') + name


def destination_names(target_project, sources):
    """List saved target configurations and names introduced by this setup."""
    names = [DEFAULT]
    if target_project and Path(target_project).is_file():
        names = detect_variants(target_project)
    for source in sources:
        name = getattr(source, 'destination_variant', None)
        if getattr(source, 'variant_mode', 'base') == 'separate' and name and name not in names:
            names.append(name)
    return names


class VariantImportDialog(wx.Dialog):
    """Return a copied source specification; cancellation never changes setup."""
    def __init__(self, parent, spec, destinations):
        super().__init__(parent, title='Source variant and import destination',
                         size=(650, 540), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((600, 520))
        apply_window_icon(self)
        self.spec = copy.deepcopy(spec)
        self.destinations = list(dict.fromkeys([DEFAULT, *destinations]))
        root = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self, label=f'Import configuration for {spec.alias}')
        root.Add(title, 0, wx.ALL, 14)
        form = wx.FlexGridSizer(cols=2, vgap=10, hgap=12)
        form.AddGrowableCol(1)
        self.source = wx.Choice(self, choices=detect_variants(spec))
        self.source.SetStringSelection(spec.variant or DEFAULT)
        form.Add(wx.StaticText(self, label='Source variant'), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.source, 1, wx.EXPAND)
        root.Add(form, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 14)
        self.mode = wx.RadioBox(self, label='How should Fusion import this configuration?',
                                choices=['Use selected state as imported base',
                                         'Merge selected state into a destination variant',
                                         'Keep selected state as a separate named variant'],
                                majorDimension=1, style=wx.RA_SPECIFY_COLS)
        self.mode.SetSelection(MODES.index(getattr(spec, 'variant_mode', 'base')))
        self.mode.Bind(wx.EVT_RADIOBOX, self.update_mode)
        root.Add(self.mode, 0, wx.EXPAND | wx.ALL, 14)
        fields = wx.FlexGridSizer(cols=2, vgap=10, hgap=12)
        fields.AddGrowableCol(1)
        fields.Add(wx.StaticText(self, label='Working variant'), 0, wx.ALIGN_CENTER_VERTICAL)
        self.target = wx.Choice(self, choices=self.destinations)
        self.target.SetSelection(0)
        self.target.SetStringSelection(getattr(spec, 'destination_variant', None) or DEFAULT)
        fields.Add(self.target, 1, wx.EXPAND)
        fields.Add(wx.StaticText(self, label='Separate variant name'), 0, wx.ALIGN_CENTER_VERTICAL)
        initial = getattr(spec, 'destination_variant', None)
        if not initial or initial == DEFAULT:
            initial = spec.alias + '-' + (spec.variant if spec.variant and spec.variant != DEFAULT else 'Default')
        self.name = wx.TextCtrl(self, value=initial)
        fields.Add(self.name, 1, wx.EXPAND)
        root.Add(fields, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 14)
        self.explanation = wx.StaticText(self)
        root.Add(self.explanation, 1, wx.EXPAND | wx.ALL, 14)
        root.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 14)
        self.SetSizer(root)
        self.update_mode()
        self.CentreOnParent()

    def update_mode(self, event=None):
        mode = MODES[self.mode.GetSelection()]
        self.target.Enable(mode == 'merge')
        self.name.Enable(mode == 'separate')
        text = {
            'base': 'The selected source state becomes the base of the imported copy. Existing destination components and their variants stay unchanged.',
            'merge': 'Source Default remains the imported base. The selected source state becomes an override on imported components in the chosen working variant. Existing destination components are retained.',
            'separate': 'Source Default remains the imported base. The selected source state is retained under a new destination variant name. Use Variant Manager afterward to compare or manage it.',
        }[mode]
        self.explanation.SetLabel(text + '\n\nSource files are unchanged. Named footprint substitutions are refused; synchronize a source copy and use base import for another physical configuration. Named PCB-presence changes require schematic-only import.')
        self.explanation.Wrap(max(520, self.GetClientSize().width - 32))
        self.Layout()

    def result(self):
        result = copy.deepcopy(self.spec)
        result.variant = self.source.GetStringSelection()
        result.variant_mode = MODES[self.mode.GetSelection()]
        result.destination_variant = (self.target.GetStringSelection() if result.variant_mode == 'merge'
                                      else self.name.GetValue().strip() if result.variant_mode == 'separate' else DEFAULT)
        if result.variant_mode == 'separate' and (not result.destination_variant or result.destination_variant == DEFAULT):
            raise MergeError('Enter a nonempty name for the separate variant; <Default> is reserved.')
        return result


def choose_variant_import(parent, spec, destinations):
    with VariantImportDialog(parent, spec, destinations) as dialog:
        while dialog.ShowModal() == wx.ID_OK:
            try:
                return dialog.result()
            except MergeError as exc:
                wx.MessageBox(str(exc), 'Variant destination', wx.OK | wx.ICON_ERROR, dialog)
    return None
