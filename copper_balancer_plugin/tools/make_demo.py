"""Create a small board exercising copper, slots, cutouts and keepouts."""
from pathlib import Path
import pcbnew as p


def vec(x,y):
    return p.VECTOR2I(p.FromMM(x),p.FromMM(y))


def make_board():
    board = p.BOARD()
    def edge(a,b):
        shape = p.PCB_SHAPE(board)
        shape.SetShape(p.SHAPE_T_SEGMENT)
        shape.SetStart(vec(*a))
        shape.SetEnd(vec(*b))
        shape.SetWidth(p.FromMM(.05))
        shape.SetLayer(p.Edge_Cuts)
        board.Add(shape)
    for ring in (((0,0),(70,0),(70,45),(0,45)),((47,15),(55,15),(55,23),(47,23))):
        for a,b in zip(ring,ring[1:]+ring[:1]):
            edge(a,b)
    net = p.NETINFO_ITEM(board,"GND")
    board.Add(net)
    for x,y in ((7,7),(63,38)):
        fp = p.FOOTPRINT(board)
        fp.SetReference("H1" if x==7 else "H2")
        board.Add(fp)
        fp.SetPosition(vec(x,y))
        pad = p.PAD(fp)
        pad.SetAttribute(p.PAD_ATTRIB_NPTH)
        pad.SetShape(p.PAD_SHAPE_CIRCLE)
        pad.SetSize(vec(3.2,3.2))
        pad.SetDrillSize(vec(3.2,3.2))
        pad.SetLayerSet(p.LSET.AllCuMask())
        pad.SetPosition(vec(x,y))
        fp.Add(pad)
    fp = p.FOOTPRINT(board)
    fp.SetReference("U1")
    board.Add(fp)
    fp.SetPosition(vec(25,22))
    for i in range(8):
        pad = p.PAD(fp)
        pad.SetAttribute(p.PAD_ATTRIB_SMD)
        pad.SetShape(p.PAD_SHAPE_ROUNDRECT)
        pad.SetSize(vec(2.2,1.3))
        pad.SetRoundRectRadiusRatio(.2)
        pad.SetPosition(vec(21+(i//4)*8,17+(i%4)*3))
        layers = p.LSET()
        layers.AddLayer(p.F_Cu)
        pad.SetLayerSet(layers)
        pad.SetNumber(str(i+1))
        pad.SetNetCode(net.GetNetCode())
        fp.Add(pad)
    for a,b in (((9,10),(21,17)),((21,17),(21,26)),((29,17),(40,7)),((29,26),(40,35))):
        track = p.PCB_TRACK(board)
        track.SetStart(vec(*a))
        track.SetEnd(vec(*b))
        track.SetWidth(p.FromMM(.8))
        track.SetLayer(p.F_Cu)
        track.SetNetCode(net.GetNetCode())
        board.Add(track)
    via = p.PCB_VIA(board)
    via.SetPosition(vec(40,35))
    via.SetWidth(p.FromMM(1.5))
    via.SetDrill(p.FromMM(.7))
    via.SetViaType(p.VIATYPE_THROUGH)
    via.SetLayerPair(p.F_Cu,p.B_Cu)
    via.SetNetCode(net.GetNetCode())
    board.Add(via)
    zone = p.ZONE(board)
    zone.SetLayer(p.F_Cu)
    zone.SetIsRuleArea(True)
    zone.SetDoNotAllowZoneFills(True)
    outline = zone.Outline()
    outline.NewOutline()
    for x,y in ((4,32),(22,32),(22,41),(4,41)):
        outline.Append(p.FromMM(x),p.FromMM(y))
    board.Add(zone)
    return board


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    (root/'examples').mkdir(exist_ok=True)
    path = root/'examples'/'copper-balancer-demo.kicad_pcb'
    p.SaveBoard(str(path),make_board())
    print(path)
