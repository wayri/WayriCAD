"""Semantic icons retain text, cache work and keep workflow stages readable."""
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

from wayricad_runtime import visual_feedback as feedback


class VisualFeedbackTests(unittest.TestCase):
    def setUp(self):
        feedback._BITMAPS.clear()

    def fake_wx(self):
        theme=[1,2]
        images=[]
        def make(art,client,size):
            value=SimpleNamespace(IsOk=lambda:True,size=size)
            images.append((art,client,size))
            return value
        wx=SimpleNamespace(NullBitmap=SimpleNamespace(IsOk=lambda:False),
            Size=lambda x,y:(x,y),SYS_COLOUR_WINDOW=0,SYS_COLOUR_WINDOWTEXT=1,
            SystemSettings=SimpleNamespace(GetColour=lambda name:SimpleNamespace(GetRGBA=lambda:theme[name])),
            ArtProvider=SimpleNamespace(GetBitmap=make),ART_BUTTON='button',
            EVT_SYS_COLOUR_CHANGED='theme',EVT_DPI_CHANGED='dpi',LEFT='left')
        for names in feedback._ART.values():
            for name in names:setattr(wx,name,name)
        return wx,theme,images

    def test_roles_are_presentation_only_and_labels_remain_meaningful(self):
        self.assertEqual(feedback.action_role('&Preview'),'preview')
        self.assertEqual(feedback.action_role('Run selected checks'),'run')
        self.assertEqual(feedback.action_role('Open report'),'open')
        self.assertIsNone(feedback.action_role('Unrecognized action'))
        for label in ('Analyze', 'Analyse', 'Run', 'Solve', 'Preview', 'Validate',
                      'Export', 'Import', 'Open', 'Load', 'Save', 'Help', 'Cancel',
                      'Stop', 'Select', 'Clear', 'Reset', 'Focus', 'Fit', 'Apply',
                      'Delete', 'Remove', 'Undo', 'Redo', 'Refresh', 'Search'):
            self.assertIsNotNone(feedback.action_role(label),label)

    def test_existing_artwork_and_unrecognized_controls_are_untouched(self):
        wx,theme,images=self.fake_wx()
        existing=SimpleNamespace(IsOk=lambda:True)
        button=SimpleNamespace(GetLabel=lambda:'Open model',GetBitmap=lambda:existing)
        unknown=SimpleNamespace(GetLabel=lambda:'Custom component action')
        with patch.dict(sys.modules,{'wx':wx}):
            self.assertIs(feedback.decorate_button(button),button)
            self.assertIs(feedback.decorate_button(unknown),unknown)
        self.assertFalse(images)
        self.assertFalse(hasattr(button,'_wayricad_visual_feedback'))

    def test_cache_changes_only_for_dpi_or_system_theme(self):
        wx,theme,images=self.fake_wx()
        window=SimpleNamespace(FromDIP=lambda size:(size[0]*2,size[1]*2))
        with patch.dict(sys.modules,{'wx':wx}):
            first=feedback.bitmap('run',window)
            self.assertIs(first,feedback.bitmap('run',window))
            self.assertEqual(images[0][2],(32,32));self.assertEqual(len(images),1)
            theme[0]=3
            self.assertIsNot(first,feedback.bitmap('run',window))
            self.assertEqual(len(images),2)

    def test_decoration_preserves_label_tooltip_and_does_not_duplicate_bindings(self):
        wx,theme,images=self.fake_wx()
        button=SimpleNamespace(GetLabel=lambda:'Preview board',GetToolTipText=lambda:'Existing specific explanation',
            SetToolTip=Mock(),SetBitmap=Mock(),SetBitmapPosition=Mock(),SetBitmapMargins=Mock(),
            FromDIP=lambda size:size,Bind=Mock(),GetParent=lambda:SimpleNamespace(Layout=Mock()))
        with patch.dict(sys.modules,{'wx':wx}):
            self.assertIs(feedback.decorate_button(button,'preview'),button)
            feedback.decorate_button(button,'run')
            self.assertEqual(button.GetLabel(),'Preview board')
            button.SetToolTip.assert_not_called()
            self.assertEqual(button.Bind.call_count,2)
            self.assertEqual(button._wayricad_visual_feedback['role'],'run')
            event=SimpleNamespace(Skip=Mock())
            button._wayricad_visual_feedback['refresh'](event)
            event.Skip.assert_called_once()


try:
    import wx
except ImportError:
    wx=None


@unittest.skipIf(wx is None,'Native wxPython is required')
class NativeVisualFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=wx.GetApp() or wx.App(False)

    def setUp(self):
        feedback._BITMAPS.clear()
        self.frame=wx.Frame(None,title='Workflow feedback test',size=(400,180))
        self.panel=wx.Panel(self.frame)

    def tearDown(self):
        self.frame.Destroy()
        self.app.ProcessPendingEvents()

    def test_native_button_retains_text_and_tooltip_at_physical_dpi(self):
        button=wx.Button(self.panel,label='Run check')
        button.SetToolTip('Analyze the saved selection')
        feedback.decorate_button(button,'run')
        self.assertEqual(button.GetLabel(),'Run check')
        self.assertEqual(button.GetToolTipText(),'Analyze the saved selection')
        self.assertTrue(button.GetBitmap().IsOk())
        expected=button.FromDIP((16,16))
        self.assertEqual(tuple(button.GetBitmap().GetSize()),tuple(expected))

    def test_visible_stage_and_completion_remain_compact_when_narrow(self):
        from wayricad_runtime.guided_ui import WorkflowGuide
        guide=WorkflowGuide(self.panel,'Component review','Choose a component',
                            ['Select','Preview','Apply'],lambda event:None)
        outer=wx.BoxSizer(wx.VERTICAL);outer.Add(guide.panel,0,wx.EXPAND)
        self.panel.SetSizer(outer);self.frame.Show();self.frame.SetSize((360,200))
        self.panel.Layout();self.app.Yield()
        self.assertTrue(guide.progress.IsShown())
        self.assertTrue(guide.progress.GetLabel().startswith('1/3'))
        self.assertLessEqual(guide.panel.GetMinSize().width,self.panel.GetClientSize().width)
        guide.set_step(1,'Inspect the selected preview')
        self.assertTrue(guide.progress.GetLabel().startswith('2/3'))
        guide.set_step(3,'All steps complete')
        self.assertEqual(guide._status_role,'success')
        self.assertIn('Complete',guide.progress.GetLabel())
        guide.set_step(3,'Blocked: fix the missing source')
        self.assertEqual(guide._status_role,'error')

    def test_late_icons_remeasure_label_without_clipping(self):
        button=wx.Button(self.panel,label='Apply selected rows')
        layout=wx.BoxSizer(wx.HORIZONTAL);layout.Add(button,0)
        self.panel.SetSizer(layout);self.frame.Show();self.panel.Layout()
        feedback.decorate_button(button,'apply');self.panel.Layout();self.app.Yield()
        self.assertGreaterEqual(button.GetSize().width,button.GetBestSize().width)
        self.assertGreaterEqual(button.GetMinSize().height,button.GetBestSize().height)


if __name__=='__main__':unittest.main()
