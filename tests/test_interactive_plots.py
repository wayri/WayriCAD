import unittest,json,math
from wayricad_runtime.interactive_plots import interactive_plot
class InteractivePlotsTests(unittest.TestCase):
 def test_unknowns_escape_and_isolation(self):
  one=interactive_plot('<script>',[[1,2,math.nan,'</script>']],polygons=[[[0,0],[2,0],[0,3]]])
  self.assertIn('"rows": [[1, 2, null, "\\u003c/script>"]]',one)
  self.assertNotIn('NaN',one);self.assertIn('&lt;script&gt;',one)
  self.assertIn('inside(p,q.poly)',one);self.assertIn('Number.isFinite(q.r[2])',one)
  two=interactive_plot('Other',[])
  self.assertNotEqual(one.split('id="')[1].split('"')[0],two.split('id="')[1].split('"')[0])
 def test_native_unknown_and_hole_probes(self):
  from matplotlib.figure import Figure
  from matplotlib.backends.backend_agg import FigureCanvasAgg
  from matplotlib.backend_bases import MouseEvent
  from wayricad_runtime.plot_probe import attach_probes
  f=Figure();canvas=FigureCanvasAgg(f);ax=f.add_subplot();ax.set(xlim=(0,3),ylim=(0,3));canvas.draw()
  ctrl=attach_probes(canvas,ax,[[.5,.5,2,'cell'],[2.5,2.5,None,'unknown']],polygons=[[[0,0],[1,0],[0,1]],[[2,2],[3,2],[2,3]]])
  for x,y in [(.2,.2),(1.5,1.5),(2.2,2.2)]:
   sx,sy=ax.transData.transform((x,y));canvas.callbacks.process('button_press_event',MouseEvent('button_press_event',canvas,sx,sy,button=1));canvas.callbacks.process('button_release_event',MouseEvent('button_release_event',canvas,sx,sy,button=1))
  self.assertEqual(len(ctrl['probes']),1);ctrl['disconnect']()
if __name__=='__main__':unittest.main()
