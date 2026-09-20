"""Preview-first test-point naming and silkscreen tables, with IPC transactions."""
from __future__ import annotations
import fnmatch
import hashlib
import math


def make_plan(records, pattern='TP*', template='{net}', overrides=None):
    """Only connected single-net test points can receive an unambiguous value."""
    overrides=overrides or {};rows=[]
    for record in records:
        if not fnmatch.fnmatchcase(record['reference'].upper(),pattern.upper()):continue
        nets=sorted(set(n for n in record['nets'] if n))
        reason='Locked footprint' if record.get('locked') else 'No connected net' if not nets else 'Multiple nets; choose a single-net test point' if len(nets)>1 else ''
        net=', '.join(nets)
        try:value=overrides.get(record['id'],template.format(net=net,ref=record['reference']))
        except (KeyError,ValueError,IndexError,AttributeError) as exc:raise ValueError('Use only {net} and {ref} in the label template.') from exc
        if not value or len(value)>160 or any(ord(c)<32 for c in value):reason=reason or 'Label must contain 1–160 printable characters'
        rows.append({**record,'net':net,'proposed':value,'reason':reason})
    return sorted(rows,key=lambda r:r['reference'])


def table_layout(rows,x_mm,y_mm,size_mm=1.0):
    values=[('Test point','Net')]+[(r['reference'],r['net']) for r in rows if not r['reason']]
    if len(values)==1:raise ValueError('No valid reviewed test points for the table.')
    if not all(math.isfinite(v) for v in (x_mm,y_mm,size_mm)) or not .5<=size_mm<=10:raise ValueError('Use finite coordinates and a text size from 0.5 to 10 mm.')
    width=max(len(a) for a,b in values)*size_mm*1.2+2*size_mm
    return [{'text':text,'x_mm':x_mm+column*width,'y_mm':y_mm+row*size_mm*1.8,'size_mm':size_mm} for row,pair in enumerate(values) for column,text in enumerate(pair)]


def native_records(board):
    return [{'id':fp.m_Uuid.AsString(),'reference':fp.GetReference(),'value':fp.GetValue(),
             'nets':[p.GetNetname() for p in fp.Pads()],'x_mm':fp.GetPosition().x/1e6,'y_mm':fp.GetPosition().y/1e6,'locked':fp.IsLocked(),'label_x_mm':fp.Value().GetPosition().x/1e6,'label_y_mm':fp.Value().GetPosition().y/1e6,'label_size_mm':fp.Value().GetTextSize().y/1e6,'pads':[(p.GetPosition().x/1e6,p.GetPosition().y/1e6,p.GetSize().x/1e6,p.GetSize().y/1e6) for p in fp.Pads()]} for fp in board.GetFootprints()]


class LiveTestPoints:
    """Never discovers another socket; revalidates origin and scene before every write."""
    def __init__(self,board_path):
        from pathlib import Path
        from wayricad_runtime.context import connect,saved_board
        self.client=connect();self.path=Path(board_path).resolve()
        if saved_board(self.client)!=self.path:raise RuntimeError('Originating editor does not match this SI board.')
        self.raw=self.client.get_board();self.undo_state=None

    def snapshot(self):
        from wayricad_runtime.context import saved_board
        if saved_board(self.client)!=self.path:raise RuntimeError('Originating editor changed boards. Reopen Quick SI.')
        footprints=self.raw.get_footprints();blobs=[]
        for items in (footprints,self.raw.get_tracks(),self.raw.get_vias(),self.raw.get_zones(),self.raw.get_shapes(),self.raw.get_text()):
            blobs.extend(item.proto.SerializeToString(deterministic=True) for item in items)
        stamp=hashlib.sha256(b''.join(sorted(blobs))).hexdigest()
        rows=[{'id':f.id.value,'reference':f.reference_field.text.value,'value':f.value_field.text.value,
               'nets':[p.net.name for p in f.definition.pads],'x_mm':f.position.x/1e6,'y_mm':f.position.y/1e6,'locked':f.locked,'label_x_mm':f.value_field.text.position.x/1e6,'label_y_mm':f.value_field.text.position.y/1e6,'label_size_mm':f.value_field.text.attributes.size.y/1e6,'pads':[(p.position.x/1e6,p.position.y/1e6,p.padstack.copper_layers[0].size.x/1e6,p.padstack.copper_layers[0].size.y/1e6) for p in f.definition.pads]} for f in footprints]
        rows.sort(key=lambda row:row['id'])
        return stamp,rows,{f.id.value:f for f in footprints}

    def apply(self,stamp,rows,*,labels=True,silk=False,table=None,back=False):
        from kipy import board_types as types
        from kipy.geometry import Vector2
        from kipy.proto.board.board_types_pb2 import BL_F_SilkS,BL_B_SilkS
        current,records,footprints=self.snapshot()
        if current!=stamp:raise RuntimeError('Board changed since preview. Refresh and review again.')
        valid=[r for r in rows if not r['reason']]
        if not valid:raise ValueError('No valid reviewed test points.')
        before=[];changed=[]
        for row in valid:
            fp=footprints[row['id']]
            if labels:
                before.append(types.FootprintInstance(proto=fp.proto))
                fp.value_field.text.value=row['proposed']
                if silk:
                    fp.value_field.visible=True
                    fp.value_field.text.layer=BL_B_SilkS if back else BL_F_SilkS
                    fp.value_field.text.attributes.mirrored=back
                changed.append(fp)
        additions=[]
        for cell in table or []:
            item=types.BoardText();item.value=cell['text'];item.layer=BL_B_SilkS if back else BL_F_SilkS
            item.position=Vector2.from_xy(round(cell['x_mm']*1e6),round(cell['y_mm']*1e6))
            item.attributes.size=Vector2.from_xy(round(cell['size_mm']*1e6),round(cell['size_mm']*1e6))
            item.attributes.stroke_width=round(cell['size_mm']*.15*1e6);item.attributes.mirrored=back
            from kipy.proto.common.types.enums_pb2 import HA_LEFT,VA_TOP
            item.attributes.horizontal_alignment=HA_LEFT;item.attributes.vertical_alignment=VA_TOP
            additions.append(item)
        transaction=self.raw.begin_commit();created=[]
        try:
            if changed:
                result=self.raw.update_items(changed)
                if {r.id.value for r in result}!={r.id.value for r in changed}:raise RuntimeError('Editor did not acknowledge all label updates.')
            if additions:
                created=self.raw.create_items(additions)
                if len(created)!=len(additions):raise RuntimeError('Editor did not create the complete table.')
            self.raw.push_commit(transaction,'WayriCAD test point labels and table')
        except Exception:
            self.raw.drop_commit(transaction);raise
        after,_,_=self.snapshot();self.undo_state=(after,before,created)
        return len(changed),len(created)

    def undo(self):
        if self.undo_state is None:raise ValueError('No test point operation to undo.')
        stamp,before,created=self.undo_state
        current,_,_=self.snapshot()
        if current!=stamp:raise RuntimeError('Board changed after applying. Use KiCad Undo, or review the intervening edits first.')
        transaction=self.raw.begin_commit()
        try:
            if before:self.raw.update_items(before)
            if created:self.raw.remove_items(created)
            self.raw.push_commit(transaction,'Undo WayriCAD test point labels and table')
        except Exception:
            self.raw.drop_commit(transaction);raise
        self.undo_state=None

