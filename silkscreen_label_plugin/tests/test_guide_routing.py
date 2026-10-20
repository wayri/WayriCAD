"""A guide can detour around a blocker while its caller retains clearance gates."""
import unittest
from silkscreen_label_plugin.guide_routing import dogleg_paths, visibility_path
from silkscreen_label_plugin.placement import segment_segment_distance

class DoglegTests(unittest.TestCase):
    def test_orthogonal_two_bend_path_clears_blocked_straight_line(self):
        paths=list(dogleg_paths((0,0),(10,0),[(4,-1,6,1)],1))
        self.assertTrue(paths)
        def outside(path):
            return all(not (min(a[0],b[0])<=7 and max(a[0],b[0])>=3 and
                            min(a[1],b[1])<=2 and max(a[1],b[1])>=-2)
                       for a,b in zip(path,path[1:]))
        self.assertTrue(any(outside(path) for path in paths))
        for path in paths:
            self.assertEqual(path[0],(0,0));self.assertEqual(path[-1],(10,0))
            self.assertTrue(all(a[0]==b[0] or a[1]==b[1] for a,b in zip(path,path[1:])))
            self.assertGreater(segment_segment_distance(path[0],path[1],path[2],path[3]),0)

    def test_candidate_order_deduplication_and_budget_are_deterministic(self):
        boxes=[(x,-x,x+1,x+2) for x in range(100)]
        paths=list(dogleg_paths((0,0),(100,100),boxes,2,limit=7))
        self.assertLessEqual(len(paths),7);self.assertEqual(len(paths),len(set(paths)))
        self.assertEqual(paths,list(dogleg_paths((0,0),(100,100),list(reversed(boxes)),2,limit=7)))
        for margin,limit in ((-1,2),(1,0)):
            with self.assertRaises(ValueError):list(dogleg_paths((0,0),(1,1),[],margin,limit))

class VisibilityTests(unittest.TestCase):
    @staticmethod
    def clear_for(boxes, bounds=(-100,-100,200,200), margin=0):
        def intersects(a,b,box):
            low,high=0.,1.
            for axis in (0,1):
                delta=b[axis]-a[axis]
                left=box[axis]-margin;right=box[axis+2]+margin
                if delta==0:
                    if not left<=a[axis]<=right:return False
                else:
                    first=(left-a[axis])/delta;last=(right-a[axis])/delta
                    low=max(low,min(first,last));high=min(high,max(first,last))
                    if low>high:return False
            return True
        def clear(a,b):
            return all(bounds[0]<=p[0]<=bounds[2] and bounds[1]<=p[1]<=bounds[3]
                       for p in (a,b)) and not any(intersects(a,b,box) for box in boxes)
        return clear

    def test_multibend_staggered_obstacles_and_exact_callback(self):
        boxes=[(20,0,23,28),(45,12,48,40),(70,0,73,28)]
        clear=self.clear_for(boxes,(0,0,100,40),margin=1)
        route=visibility_path((2,5),(98,35),boxes,1,clear,max_nodes=48,max_checks=2048)
        self.assertIsNotNone(route)
        self.assertGreater(len(route),4)
        self.assertEqual(route[0],(2,5));self.assertEqual(route[-1],(98,35))
        self.assertTrue(all(clear(a,b) for a,b in zip(route,route[1:])))
        self.assertEqual(route,visibility_path((2,5),(98,35),list(reversed(boxes)),1,clear))

    def test_clear_arbitrary_angle_and_45_degree_routes(self):
        for end in ((60,60),(60,17)):
            route=visibility_path((0,0),end,[],0,lambda a,b:True)
            self.assertEqual(route,((0,0),end))
        # A genuinely diagonal bend is available when a central blocker is used.
        boxes=[(40,40,60,60)]
        route=visibility_path((0,0),(100,100),boxes,1,self.clear_for(boxes))
        self.assertIsNotNone(route)
        self.assertTrue(any(a[0]!=b[0] and a[1]!=b[1] for a,b in zip(route,route[1:])))

    def test_failure_budgets_and_callback_exceptions(self):
        boxes=[(4,-100,6,100)]
        self.assertIsNone(visibility_path((0,0),(10,0),boxes,1,
                                         self.clear_for(boxes,(0,-10,10,10))))
        calls=[]
        def blocked(a,b):calls.append((a,b));return False
        self.assertIsNone(visibility_path((0,0),(100,100),[(i,2,i+1,3) for i in range(100)],
                                         1,blocked,max_nodes=8,max_checks=3))
        self.assertLessEqual(len(calls),3)
        self.assertIsNone(visibility_path((0,0),(0,0),[],0,blocked))
        def failure(a,b):raise RuntimeError('Native clearance failed')
        with self.assertRaisesRegex(RuntimeError,'Native clearance'):
            visibility_path((0,0),(10,0),[],0,failure)
        for kwargs in ({'margin':-1},{'max_nodes':1},{'max_checks':0}):
            options=dict(margin=0);options.update(kwargs)
            with self.assertRaises(ValueError):
                visibility_path((0,0),(10,0),[],segment_clear=blocked,**options)

if __name__=='__main__':unittest.main()
