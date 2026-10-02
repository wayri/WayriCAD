"""Actual generated root sheet blocks, with editable placement in millimetres."""
from .preview import PlacementPreview, Primitive
from . import sexpr as sx

class SheetPreview(PlacementPreview):
    def show_schematic(self,path,movable):
        self.clear();self.locked_aliases=set()
        for sheet in sx.children(sx.load(path),'sheet'):
            alias=sx.propval(sheet,'Sheetname');at=sx.child(sheet,'at');size=sx.child(sheet,'size')
            if at is None or size is None:continue
            x,y=map(float,at[1:3]);w,h=map(float,size[1:3])
            self.boxes.append((alias,x,y,x+w,y+h))
            if alias not in movable:self.locked_aliases.add(alias)
            self.primitives.append(Primitive(alias,'Sheet','line',((x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)),0.25))
            for pin in sx.children(sheet,'pin'):
                p=sx.child(pin,'at')
                if p is not None:
                    px,py=map(float,p[1:3]);self.primitives.append(Primitive(alias,'Sheet','line',((px-2,py),(px+2,py)),0.25))
        self.fit()
