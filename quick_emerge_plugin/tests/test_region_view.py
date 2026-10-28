"""Low-memory Agg checks for the saved-board, pre-extraction context."""
import copy
import unittest
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.path import Path
from quick_emerge_plugin.region_view import board_context


class BoardContextTests(unittest.TestCase):
    def setUp(self):
        self.figure=Figure(figsize=(8,6));FigureCanvasAgg(self.figure)
        self.listing={'board_outline':[{'outer_mm':[[0,0],[40,0],[40,30],[0,30]],
            'holes_mm':[[[5,5],[5,8],[8,8],[8,5]]]}], 'board_bounds_mm':[0,0,40,30],
            'areas':[{'id':'roi','name':'RF enclosure','outline':[{'outer_mm':[[10,10],[30,10],[30,15],[20,15],[20,25],[10,25]],'holes_mm':[]}]}]}

    def test_actual_concave_outlines_and_holes_without_copper_or_fill(self):
        original=copy.deepcopy(self.listing)
        board_context(self.figure,self.listing,{'copper':True,'ports':True})
        axes=self.figure.axes[0]
        self.assertEqual(len(axes.patches),2)
        board,area=axes.patches
        self.assertEqual(board.get_gid(),'saved-board-outline')
        self.assertEqual(area.get_gid(),'saved-rule-area-outline')
        self.assertEqual(list(board.get_path().codes).count(Path.MOVETO),2)
        self.assertEqual(list(area.get_path().codes).count(Path.MOVETO),1)
        np.testing.assert_allclose(area.get_path().vertices[:-1],self.listing['areas'][0]['outline'][0]['outer_mm'])
        self.assertTrue(all(p.get_facecolor()[3]==0 for p in axes.patches))
        self.assertEqual(len(axes.collections),0)
        self.assertEqual(len(axes.lines),0)
        self.assertTrue(any(t.get_text()=='RF enclosure' for t in axes.texts))
        self.assertIn('Preview copper',axes.get_title())
        self.assertTrue(any('copper has not been extracted' in t.get_text() for t in axes.texts))
        self.figure.canvas.draw()
        self.assertEqual(self.listing,original)

    def test_missing_and_unavailable_enclosures_are_explicit(self):
        self.listing['areas']=[];board_context(self.figure,self.listing)
        self.assertTrue(any('No saved rule areas' in t.get_text() for t in self.figure.axes[0].texts))
        self.listing['areas']=[{'id':'curve','name':'Curved RF','outline':[],'unsupported':['Curved contours']}]
        board_context(self.figure,self.listing)
        axes=self.figure.axes[0]
        self.assertEqual(len(axes.patches),1)
        self.assertTrue(any('Unavailable enclosure geometry: Curved RF' in t.get_text() for t in axes.texts))
        self.figure.canvas.draw()
        with self.assertRaisesRegex(ValueError,'no outline'):
            board_context(self.figure,{'board_outline':[],'board_bounds_mm':[0,0,80,80]})


if __name__=='__main__':unittest.main()
