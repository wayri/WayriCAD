"""Native wxPython GUI. Runs in KiCad 10's Python; no webview/server or implicit network connection.
Host acceptance is required: pure-core tests cannot certify wx/pcbnew execution.
"""
import ast, copy, json, pathlib, re, threading, traceback
import wx
import wx.grid as gridlib
import wx.html
import wx.aui as aui
import wx.lib.scrolledpanel as scrolled
from .catalog import CATALOG, SPECS, CATEGORIES, FUNCTIONS, FUNCTION_MAP, PROPERTY_TYPES, TYPES, LAYERS, SEVERITIES
from .model import Rule, Constraint, RuleDocument
from .expressions import Expr, parse_expression, property_test, function_test
from .profiles import bga_rules, matrix_rules, replace_generated, profile_rules
from .workspace import Workspace, atomic_write, get_path, set_path, parse_scalar
from .board import stage_courtyard_area, courtyard_polygon, refresh_copied_area
from .validation import native_drc
from .help_system import tooltip_for, topic_for_page
from .help_ui import HelpPanel, bind_dialog_help

TITLE='Constraint Studio 0.3.1 · KiCad 10'
BG='#F4F6FA'; PANEL='#FFFFFF'; INK='#17253C'; MUTED='#53647A'; ACCENT='#2155AD'

def error(parent,exc):
    wx.MessageBox(str(exc),'Constraint Studio',wx.OK|wx.ICON_ERROR,parent)

def info(parent,text):wx.MessageBox(text,'Constraint Studio',wx.OK|wx.ICON_INFORMATION,parent)

def label(parent,text,bold=False,size=None):
    w=wx.StaticText(parent,label=text)
    f=w.GetFont()
    if bold:f.SetWeight(wx.FONTWEIGHT_BOLD)
    if size:f.SetPointSize(size)
    w.SetFont(f);return w

def button(parent,text,handler):
    b=wx.Button(parent,label=text);b.Bind(wx.EVT_BUTTON,handler)
    tip=tooltip_for(text)
    if tip:b.SetToolTip(tip)
    return b

def row(parent,sizer,title,control):
    tip=tooltip_for(title)
    if tip:control.SetToolTip(tip)
    sizer.Add(label(parent,title),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,12)
    sizer.Add(control,1,wx.EXPAND)
    return control

def mono(control):
    control.SetFont(wx.Font(10,wx.FONTFAMILY_TELETYPE,wx.FONTSTYLE_NORMAL,wx.FONTWEIGHT_NORMAL))

def choices(parent,items,value='',editable=True):
    w=wx.ComboBox(parent,choices=list(items),style=wx.CB_DROPDOWN if editable else wx.CB_READONLY)
    if value:w.SetValue(value)
    elif items:w.SetSelection(0)
    return w

def text_value(v):return 'null' if v is None else str(v).lower() if isinstance(v,bool) else str(v)


class ClauseDialog(wx.Dialog):
    """One property test/function call; compound logic lives in the tree editor."""
    def __init__(self,parent,context=None,netclasses=(),initial=''):
        super().__init__(parent,title='Add or edit a condition',size=(780,590),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.result=None;self.context=context;self.netclasses=netclasses
        bind_dialog_help(self,lambda: ("function-"+self.fn.GetValue()) if self.book.GetSelection()==1 else "scope-builder")
        root=wx.BoxSizer(wx.VERTICAL);self.SetSizer(root)
        root.Add(label(self,'Describe which object should match this rule',True,13),0,wx.ALL,16)
        self.book=wx.Notebook(self);root.Add(self.book,1,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        prop=wx.Panel(self.book);func=wx.Panel(self.book);advanced=wx.Panel(self.book)
        self.book.AddPage(prop,'Property comparison');self.book.AddPage(func,'Function');self.book.AddPage(advanced,'Advanced / preserved')
        s=wx.FlexGridSizer(cols=2,vgap=14,hgap=12);s.AddGrowableCol(1,1)
        ps=wx.BoxSizer(wx.VERTICAL);ps.Add(s,0,wx.EXPAND|wx.ALL,16);prop.SetSizer(ps)
        self.obj=row(prop,s,'Object',choices(prop,['A','B'],editable=False))
        self.prop=row(prop,s,'Property',choices(prop,sorted(PROPERTY_TYPES),'NetName'))
        self.op=row(prop,s,'Comparison',choices(prop,['==','!=','<','<=','>','>=','is true','is false'],'==',False))
        self.typ=row(prop,s,'Value type',choices(prop,['string','dimension','number','integer','angle','boolean','null'],'string',False))
        suggestions=(context.nets if context else [])+list(netclasses)+[f.reference for f in context.footprints] if context else list(netclasses)
        self.value=row(prop,s,'Value',choices(prop,suggestions));self.value.SetValue('')
        ps.Add(label(prop,'Strings are quoted automatically. Use units such as 0.15mm for dimensions.\nBoolean properties use “is true / is false”, not true/false text literals.'),0,wx.ALL,16)
        self.prop.Bind(wx.EVT_COMBOBOX,self.on_property)
        fs=wx.BoxSizer(wx.VERTICAL);func.SetSizer(fs);g=wx.FlexGridSizer(cols=2,vgap=14,hgap=12);g.AddGrowableCol(1,1);fs.Add(g,0,wx.EXPAND|wx.ALL,16)
        self.fobj=row(func,g,'Object',choices(func,['A','B','AB'],'A',False))
        self.fn=row(func,g,'Function',choices(func,[f[0] for f in FUNCTIONS],'enclosedByArea',False))
        self.arg1=row(func,g,'Argument 1',choices(func,[]));self.arg2=row(func,g,'Argument 2',choices(func,[]))
        self.fcompare=row(func,g,'Field comparison',choices(func,['No comparison','==','!='],'No comparison',False))
        self.fvalue=row(func,g,'Field value',wx.TextCtrl(func))
        self.negate=wx.CheckBox(func,label='NOT: invert the function result');fs.Add(self.negate,0,wx.LEFT|wx.BOTTOM,16)
        self.fhelp=label(func,'');fs.Add(self.fhelp,0,wx.ALL|wx.EXPAND,16)
        self.fn.Bind(wx.EVT_COMBOBOX,self.on_function);self.on_function(None)
        ass=wx.BoxSizer(wx.VERTICAL);advanced.SetSizer(ass)
        ass.Add(label(advanced,'Unrecognized expressions are preserved, not guessed or silently simplified.\nThis escape hatch also accepts version-specific native syntax.'),0,wx.ALL,16)
        self.raw=wx.TextCtrl(advanced,value=initial,style=wx.TE_MULTILINE);mono(self.raw);ass.Add(self.raw,1,wx.EXPAND|wx.ALL,16)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK|wx.CANCEL|wx.HELP),0,wx.EXPAND|wx.ALL,16)
        self.Bind(wx.EVT_BUTTON,self.on_ok,id=wx.ID_OK)
        if initial:self.populate(initial)
        self.SetMinSize((640,500));self.CenterOnParent()
    def on_property(self,event):
        self.typ.SetValue(PROPERTY_TYPES.get(self.prop.GetValue(),'string'))
        if self.typ.GetValue()=='boolean':self.op.SetValue('is true')
    def on_function(self,event):
        name=self.fn.GetValue();_,count,receiver,helptext=FUNCTION_MAP[name]
        self.arg1.Enable(count>=1);self.arg2.Enable(count>=2);self.fobj.SetValue('AB' if receiver=='AB' else 'A')
        self.fcompare.Enable(name=='getField');self.fvalue.Enable(name=='getField')
        if name!='getField':self.fcompare.SetValue('No comparison')
        vals=[];c=self.context
        if c:
            if 'Area' in name:vals=[a['name'] for a in c.areas]
            elif 'Courtyard' in name or name=='memberOfFootprint':vals=[f.reference for f in c.footprints]
            elif name=='existsOnLayer':vals=c.layers
            elif name in ('hasNetclass','hasExactNetclass'):vals=list(self.netclasses)
            elif name=='memberOfGroup':vals=c.groups
            elif name=='inDiffPair':vals=c.nets
            elif name=='fromTo':vals=[f.reference for f in c.footprints]
        old=self.arg1.GetValue();self.arg1.SetItems(vals);self.arg1.SetValue(old)
        self.fhelp.SetLabel(helptext);self.fhelp.Wrap(650);self.Layout()
    def populate(self,expr):
        self.book.SetSelection(2)
        # Only convert expressions we can round-trip conservatively into a form.
        m=re.fullmatch(r'([AB])\.([A-Za-z_][\w%\-]*)\s*(==|!=|<=|>=|<|>)\s*(.+)',expr.strip())
        if m:
            obj,prop,op,value=m.groups();self.obj.SetValue(obj);self.prop.SetValue(prop);self.op.SetValue(op)
            typ=PROPERTY_TYPES.get(prop,'string')
            if value in ('null',):typ='null'
            elif value[:1] in ('\"',"'"):
                try:value=ast.literal_eval(value);typ='string'
                except (ValueError,SyntaxError):return
            self.typ.SetValue(typ);self.value.SetValue(str(value));self.book.SetSelection(0);return
        m=re.fullmatch(r'([AB])\.([A-Za-z_][\w%\-]*)',expr.strip())
        if m:
            self.obj.SetValue(m[1]);self.prop.SetValue(m[2]);self.typ.SetValue('boolean');self.op.SetValue('is true');self.book.SetSelection(0);return
        m=re.fullmatch(r'(A|B|AB)\.(\w+)\((.*?)\)(?:\s*(==|!=)\s*(.+))?',expr.strip())
        if m and m[2] in FUNCTION_MAP:
            try:args=ast.literal_eval('['+m[3]+']');cv=ast.literal_eval(m[5]) if m[5] else ''
            except (ValueError,SyntaxError):return
            if any(not isinstance(a,str) for a in args):return
            self.fn.SetValue(m[2]);self.on_function(None);self.fobj.SetValue(m[1])
            if args:self.arg1.SetValue(args[0])
            if len(args)>1:self.arg2.SetValue(args[1])
            self.fcompare.SetValue(m[4] or 'No comparison');self.fvalue.SetValue(cv);self.book.SetSelection(1)
    def on_ok(self,event):
        try:
            tab=self.book.GetSelection()
            if tab==0:self.result=property_test(self.obj.GetValue(),self.prop.GetValue(),self.op.GetValue(),self.value.GetValue(),self.typ.GetValue())
            elif tab==1:
                n=FUNCTION_MAP[self.fn.GetValue()][1];args=[self.arg1.GetValue(),self.arg2.GetValue()][:n]
                comp=(self.fcompare.GetValue(),self.fvalue.GetValue()) if self.fcompare.GetValue()!='No comparison' else None
                self.result=function_test(self.fobj.GetValue(),self.fn.GetValue(),args,self.negate.GetValue(),comp)
            else:
                self.result=parse_expression(self.raw.GetValue())
                if not self.result.emit():raise ValueError('Condition cannot be blank here; use Match everything in the main builder')
            self.EndModal(wx.ID_OK)
        except Exception as e:error(self,e)


class ConditionDialog(wx.Dialog):
    def __init__(self,parent,expression='',context=None,netclasses=()):
        super().__init__(parent,title='Visual scope builder — A / B objects',size=(930,690),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.context=context;self.netclasses=netclasses;self.result=expression
        bind_dialog_help(self,"scope-builder")
        try:self.expr=parse_expression(expression)
        except ValueError:self.expr=Expr('leaf',expression)
        self.empty=not expression.strip()
        s=wx.BoxSizer(wx.VERTICAL);self.SetSizer(s)
        s.Add(label(self,'Build explicit nested groups. No hidden operator precedence.',True,13),0,wx.ALL,16)
        s.Add(label(self,'A and B are the objects being checked. Single-item rules normally use A only.'),0,wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        self.tree=wx.TreeCtrl(self,style=wx.TR_HAS_BUTTONS|wx.TR_LINES_AT_ROOT|wx.TR_SINGLE);s.Add(self.tree,1,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        bar=wx.WrapSizer();s.Add(bar,0,wx.EXPAND|wx.ALL,12)
        for title,handler in [('Add condition',self.add_leaf),('AND group',lambda e:self.group('and')),('OR group',lambda e:self.group('or')),('NOT',lambda e:self.group('not')),('Edit',self.edit),('Remove',self.remove),('Match everything',self.clear)]:bar.Add(button(self,title,handler),0,wx.RIGHT|wx.BOTTOM,6)
        self.preview=wx.TextCtrl(self,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,100));mono(self.preview);s.Add(self.preview,0,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        s.Add(self.CreateSeparatedButtonSizer(wx.OK|wx.CANCEL|wx.HELP),0,wx.EXPAND|wx.ALL,16)
        self.Bind(wx.EVT_BUTTON,self.ok,id=wx.ID_OK);self.tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED,self.edit)
        self.render();self.SetMinSize((720,580));self.CenterOnParent()
    def render(self):
        self.tree.DeleteAllItems()
        def add(node,parent=None):
            text={'and':'ALL of the following (AND)','or':'ANY of the following (OR)','not':'NOT the following'}.get(node.op,node.text or 'Match everything')
            item=self.tree.AddRoot(text) if parent is None else self.tree.AppendItem(parent,text)
            self.tree.SetItemData(item,node)
            for c in node.children:add(c,item)
            return item
        item=add(self.expr);self.tree.ExpandAll();self.tree.SelectItem(item)
        try:self.preview.ChangeValue(self.expr.emit() or '(No condition: all objects)')
        except ValueError as e:self.preview.ChangeValue(str(e))
    def selected(self):
        item=self.tree.GetSelection();return self.tree.GetItemData(item) if item.IsOk() else self.expr
    def replace(self,target,new):
        if self.expr is target:self.expr=new;return
        def walk(n):
            for i,c in enumerate(n.children):
                if c is target:n.children[i]=new;return True
                if walk(c):return True
            return False
        walk(self.expr)
    def add_leaf(self,event):
        with ClauseDialog(self,self.context,self.netclasses) as d:
            if d.ShowModal()!=wx.ID_OK:return
            selected=self.selected()
            if not self.expr.emit():self.expr=d.result
            elif selected.op in ('and','or'):selected.children.append(d.result)
            else:self.replace(selected,Expr('and',children=[selected,d.result]))
            self.render()
    def group(self,op):
        if not self.expr.emit():info(self,'Add a condition before grouping it.');return
        selected=self.selected()
        if op=='not' and selected.op=='not':self.replace(selected,selected.children[0])
        elif selected.op in ('and','or') and op in ('and','or'):selected.op=op
        else:self.replace(selected,Expr(op,children=[selected]))
        self.render()
    def edit(self,event):
        selected=self.selected()
        if selected.op!='leaf':return
        with ClauseDialog(self,self.context,self.netclasses,selected.text) as d:
            if d.ShowModal()==wx.ID_OK:self.replace(selected,d.result);self.render()
    def remove(self,event):
        target=self.selected()
        if target is self.expr:self.clear(event);return
        def prune(n):
            n.children=[c for c in n.children if c is not target]
            for c in n.children:prune(c)
            if not n.children and n.op!='leaf':n.op='leaf';n.text=''
        prune(self.expr)
        def clean(n):
            n.children=[clean(c) for c in n.children if c.op!='leaf' or c.text.strip()]
            if n.op in ('and','or') and len(n.children)==1:return n.children[0]
            if n.op!='leaf' and not n.children:return Expr()
            return n
        self.expr=clean(self.expr);self.render()
    def clear(self,event):self.expr=Expr();self.render()
    def ok(self,event):
        try:self.result=self.expr.emit();parse_expression(self.result);self.EndModal(wx.ID_OK)
        except Exception as e:error(self,e)


class ConstraintDialog(wx.Dialog):
    def __init__(self,parent,current=None,context=None,netclasses=()):
        super().__init__(parent,title='Constraint value editor',size=(780,590),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.current=copy.deepcopy(current);self.result=None;self.context=context;self.netclasses=netclasses
        bind_dialog_help(self,lambda: "constraint-"+self.kind() if self.kind() in CATALOG else "native-rules")
        s=wx.BoxSizer(wx.VERTICAL);self.SetSizer(s)
        self.selector=choices(self,[f'{x.category} / {x.label} [{x.key}]' for x in SPECS],editable=False)
        s.Add(self.selector,0,wx.EXPAND|wx.ALL,16)
        self.help=label(self,'');s.Add(self.help,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        self.body=wx.Panel(self);self.form=wx.BoxSizer(wx.VERTICAL);self.body.SetSizer(self.form);s.Add(self.body,1,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        s.Add(self.CreateSeparatedButtonSizer(wx.OK|wx.CANCEL|wx.HELP),0,wx.EXPAND|wx.ALL,16)
        self.selector.Bind(wx.EVT_COMBOBOX,self.rebuild);self.Bind(wx.EVT_BUTTON,self.ok,id=wx.ID_OK)
        if current and current.kind in CATALOG:self.selector.SetSelection(list(CATALOG).index(current.kind))
        elif current:
            self.selector.Append('Unrecognized native constraint ['+current.kind+']');self.selector.SetSelection(len(SPECS))
        self.rebuild(None);self.SetMinSize((640,490));self.CenterOnParent()
    def kind(self):return self.current.kind if self.selector.GetSelection()>=len(SPECS) else SPECS[self.selector.GetSelection()].key
    def rebuild(self,event):
        self.form.Clear(True);self.fields={};self.arg=None;self.spokes=None;self.disallow=None;self.assertion=None;self.within=None
        kind=self.kind();spec=CATALOG.get(kind);old=self.current if self.current and self.current.kind==kind else Constraint(kind)
        self.help.SetLabel((spec.help if spec else 'Opaque native syntax is preserved. Verify this type in your host version.') or 'Blank fields inherit. Values may contain units or project variables.');self.help.Wrap(700)
        if not spec:
            self.raw=wx.TextCtrl(self.body,value=old.emit(),style=wx.TE_MULTILINE);mono(self.raw);self.form.Add(self.raw,1,wx.EXPAND)
        else:
            g=wx.FlexGridSizer(cols=2,vgap=12,hgap=12);g.AddGrowableCol(1,1);self.form.Add(g,0,wx.EXPAND)
            for field in spec.fields:
                t=wx.TextCtrl(self.body,value=str(old.values.get(field,'')));self.fields[field]=row(self.body,g,{'min':'Minimum','opt':'Preferred / tuning target','max':'Maximum'}[field]+f' ({"mm or ps" if spec.unit=="length_or_time" else spec.unit or "native"})',t)
            if kind=='disallow':
                self.disallow=wx.CheckListBox(self.body,choices=list(spec.choices));self.form.Add(self.disallow,1,wx.EXPAND)
                for i,x in enumerate(spec.choices):self.disallow.Check(i,x in old.argument.split())
            elif kind in ('zone_connection','min_resolved_spokes'):
                self.arg=choices(self.body,spec.choices,old.argument or spec.choices[0],False);row(self.body,g,'Selection',self.arg)
            elif kind=='assertion':
                self.assertion=wx.TextCtrl(self.body,value=old.argument,style=wx.TE_MULTILINE|wx.TE_READONLY);mono(self.assertion);self.form.Add(self.assertion,1,wx.EXPAND)
                self.form.Add(button(self.body,'Build assertion visually…',self.build_assertion),0,wx.TOP,12)
            elif not spec.fields:self.form.Add(label(self.body,'This check has no numeric arguments. Set severity on its parent rule.'),0,wx.TOP,16)
            if kind=='skew':
                self.within=wx.CheckBox(self.body,label='Evaluate within each differential pair');self.within.SetValue(old.within_diff_pairs);self.form.Add(self.within,0,wx.TOP,16)
            if old.extras or any(k not in spec.fields for k in old.values):self.form.Add(label(self.body,'Additional imported fields/clauses will be preserved.'),0,wx.TOP,16)
        self.Layout()
    def build_assertion(self,event):
        with ConditionDialog(self,self.assertion.GetValue(),self.context,self.netclasses) as d:
            if d.ShowModal()==wx.ID_OK:self.assertion.ChangeValue(d.result)
    def ok(self,event):
        try:
            kind=self.kind();spec=CATALOG.get(kind)
            if not spec:
                doc=RuleDocument.load('(version 1)\n(rule "probe" '+self.raw.GetValue()+')')
                if len(doc.rules[0].constraints)!=1:raise ValueError('Exactly one constraint is required')
                self.result=doc.rules[0].constraints[0]
            else:
                old=self.current if self.current and self.current.kind==kind else Constraint(kind)
                vals={k:v for k,v in old.values.items() if k not in spec.fields}
                vals.update({k:w.GetValue().strip() for k,w in self.fields.items() if w.GetValue().strip()})
                arg=old.argument
                if self.arg:arg=self.arg.GetValue()
                if self.disallow:arg=' '.join(spec.choices[i] for i in self.disallow.GetCheckedItems())
                if self.assertion:arg=self.assertion.GetValue()
                self.result=Constraint(kind,vals,arg,self.within.GetValue() if self.within else old.within_diff_pairs,copy.deepcopy(old.extras))
                from .model import lint
                errors=[x.message for x in lint(RuleDocument(rules=[Rule('Constraint',constraints=[self.result])])) if x.severity=='error']
                if errors:raise ValueError('\n'.join(errors))
            self.EndModal(wx.ID_OK)
        except Exception as e:error(self,e)


class CourtyardCanvas(wx.Panel):
    """Exact staged polygon preview, explicitly not a DRC/match simulator."""
    def __init__(self,parent):
        super().__init__(parent,size=(-1,170));self.polygon=[];self.caption='Saved-geometry preview';self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT,self.paint)
    def update(self,poly,caption):self.polygon=poly;self.caption=caption;self.Refresh()
    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self) if hasattr(wx,'AutoBufferedPaintDC') else wx.BufferedPaintDC(self)
        dc.SetBackground(wx.Brush('#F0F4FA'));dc.Clear();dc.SetTextForeground(INK);dc.DrawText(self.caption,12,10)
        if not self.polygon:return
        loops=self.polygon if isinstance(self.polygon[0],list) else [self.polygon]
        allpts=[p for loop in loops for p in loop]
        if not allpts:return
        w,h=self.GetClientSize();xs=[p[0] for p in allpts];ys=[p[1] for p in allpts]
        dx=max(xs)-min(xs);dy=max(ys)-min(ys)
        scale=min(max(1,w-80)/max(dx,.1),max(1,h-65)/max(dy,.1))
        dc.SetPen(wx.Pen(ACCENT,2));dc.SetBrush(wx.TRANSPARENT_BRUSH)
        for loop in loops:
            points=[wx.Point(round((x-min(xs))*scale+(w-dx*scale)/2),round((y-min(ys))*scale+40)) for x,y in loop]
            if len(points)>2:dc.DrawPolygon(points)


class BGADialog(wx.Dialog):
    def __init__(self,parent,workspace,selected_ref=''):
        super().__init__(parent,title='Component escape / courtyard rules',size=(900,790),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.w=workspace;self.result=None
        bind_dialog_help(self,"bga")
        outer=wx.BoxSizer(wx.VERTICAL);self.SetSizer(outer)
        body=scrolled.ScrolledPanel(self);s=wx.BoxSizer(wx.VERTICAL);body.SetSizer(s);outer.Add(body,1,wx.EXPAND)
        s.Add(label(body,'Local manufacturing exception — without relaxing the whole board',True,13),0,wx.ALL,16)
        g=wx.FlexGridSizer(cols=2,vgap=10,hgap=12);g.AddGrowableCol(1,1);s.Add(g,0,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        refs=[f.reference for f in workspace.context.footprints]
        self.ref=row(body,g,'Component',choices(body,refs,selected_ref or (refs[0] if refs else 'U1')))
        self.mode=row(body,g,'Boundary policy',choices(body,['Strict: existing named rule area','Strict: copy saved front courtyard','Dynamic courtyard intersection (NOT strict)','Component children only (NOT an area)','Strict: attach courtyard area to footprint'],editable=False))
        from .linked_areas import all_areas
        self.mode.SetSelection(4)
        self.area=row(body,g,'Rule area / new area name',choices(body,[a['name'] for a in all_areas(workspace.context) if a['rule_area']]))
        self.area.SetValue('')
        self.layer=row(body,g,'Copper layer',choices(body,[l for l in workspace.context.layers if l.endswith('.Cu')] or ['F.Cu'],workspace.context.footprint(self.ref.GetValue()).layer if refs else 'F.Cu',False))
        self.clearance=row(body,g,'Local copper clearance',wx.TextCtrl(body))
        self.width=row(body,g,'Local track width (optional)',wx.TextCtrl(body))
        self.via=row(body,g,'Local via diameter (optional)',wx.TextCtrl(body))
        self.hole=row(body,g,'Local drill size (optional)',wx.TextCtrl(body))
        self.explain=label(body,'');s.Add(self.explain,0,wx.EXPAND|wx.ALL,16)
        self.canvas=CourtyardCanvas(body);s.Add(self.canvas,0,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        self.auto_sync=wx.CheckBox(body,label='Regenerate this managed scope on review/export after saved courtyard edits (refuse independent rule/area edits).');s.Add(self.auto_sync,0,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        self.ack=wx.CheckBox(body,label='I reviewed the scope, board-wide manufacturing floors, and saved-geometry limitations.');s.Add(self.ack,0,wx.ALL,16)
        outer.Add(self.CreateSeparatedButtonSizer(wx.OK|wx.CANCEL|wx.HELP),0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        self.mode.Bind(wx.EVT_COMBOBOX,self.refresh);self.ref.Bind(wx.EVT_COMBOBOX,self.refresh);self.Bind(wx.EVT_BUTTON,self.ok,id=wx.ID_OK)
        self.refresh(None);body.SetupScrolling(scroll_x=False);self.SetMinSize((720,480))
        area=wx.GetClientDisplayRect();self.SetSize((min(900,area.width-24),min(790,area.height-48)));self.CenterOnParent()
    def refresh(self,event):
        i=self.mode.GetSelection();self.area.Enable(i<2 or i==4)
        if event and event.GetEventObject() is self.ref and i==4:
            self.layer.SetValue(self.w.context.footprint(self.ref.GetValue()).layer)
        if i==1 and not self.area.GetValue():self.area.SetValue('CS_'+self.ref.GetValue()+'_COURTYARD')
        if i==4:
            msg='STRICT whole-item containment in a native footprint-owned area. The area uses the component local coordinates rather than a frozen board snapshot. Supports lines, arcs, circles and disjoint/nested contours on either side. Hole intersections are excluded. Exact arc serialization requires native acceptance. Generated rules have no fixed layer clause so the area layer controls scope. Native move/flip validation is required.'
        elif i<2:
            msg='Both A AND B must be entirely enclosed for clearance; routing dimensions use A only. Boundary-crossing segments keep stricter outside rules. No automatic trace splitting.'
            if i==1:msg+=' A simple FRONT courtyard is copied to a board-level area in the REVIEW COPY. It does NOT follow later footprint movement. Arcs, back-side parts, holes and multiple contours are rejected.'
        elif i==2:msg='WARNING: this tracks the native courtyard dynamically, but any intersecting object is matched in its entirety. A track crossing the courtyard may be relaxed outside it. This is NOT strict containment.'
        else:msg='Only children of this footprint are matched. Nearby escape tracks are not footprint children. This is not a spatial escape-area scope.'
        if self.w.floors:msg+=' Board floor: clearance '+str(self.w.floors.get('min_clearance','unknown'))+' mm; track '+str(self.w.floors.get('min_track_width','unknown'))+' mm.'
        self.explain.SetLabel(msg);self.explain.Wrap(max(400,self.GetClientSize().width-64))
        try:
            from .linked_areas import world_polygon
            from .courtyards import courtyard_contours,contour_points
            loops,_=courtyard_contours(self.w.context,self.ref.GetValue())
            poly=[world_polygon(self.w.context.footprint(self.ref.GetValue()),contour_points(loop)) for loop in loops];caption='Saved courtyard contours (curves sampled for preview only) — not DRC'
        except Exception as e:poly=[];caption=str(e)
        self.canvas.update(poly,caption);self.Layout()
    def ok(self,event):
        try:
            if not self.ack.GetValue():raise ValueError('Review and acknowledge the scope limitations first')
            ref=self.ref.GetValue();self.w.context.footprint(ref)
            i=self.mode.GetSelection();area=self.area.GetValue().strip();board_text=None;guard=None
            if i==0:
                from .linked_areas import all_areas
                found=[x for x in all_areas(self.w.context) if x['name']==area and x['rule_area']]
                if len(found)!=1:raise ValueError('Choose a unique native named rule area. This strict workflow does not use copper zones.')
            elif i==1:board_text,guard=stage_courtyard_area(self.w.context,ref,area,(self.layer.GetValue(),))
            elif i==4:
                from .courtyards import stage_regions
                board_text,guard=stage_regions(self.w.context,ref,area,(self.layer.GetValue(),),self.auto_sync.GetValue());area=guard['name']
            rules=bga_rules(ref,self.clearance.GetValue(),self.width.GetValue(),self.via.GetValue(),self.hole.GetValue(),
                mode='area' if i<2 or i==4 else 'intersection' if i==2 else 'pads',area=area,layer='' if i==4 else self.layer.GetValue())
            if i==4:
                from .courtyards import scope_for_regions,pair_scope
                aa,bb=scope_for_regions(guard['regions'],'A'),scope_for_regions(guard['regions'],'B')
                for r in rules:r.condition=pair_scope(guard['regions']) if any(c.kind=='clearance' for c in r.constraints) else aa
            from .model import lint
            errors=[x.message for x in lint(RuleDocument(rules=rules),self.w.floors) if x.severity=='error']
            if errors:raise ValueError('\n'.join(errors))
            if guard:
                guard['rule_names']=[r.name for r in rules]
                if i==4:guard['rule_states']=[r.state() for r in rules]
            self.result=(rules,board_text,guard);self.EndModal(wx.ID_OK)
        except Exception as e:error(self,e)


class StudioFrame(wx.Frame):
    def __init__(self,parent=None,board_path='',selected_ref='',native_select=None,native_probe=None,native_selection=None):
        super().__init__(parent,title=TITLE+' — development build',size=(1560,960),style=wx.DEFAULT_FRAME_STYLE)
        self.SetMinSize((900,580));self.SetBackgroundColour(BG)
        self.w=Workspace();self.w.saved_state=self.w.state();self.selected_ref=selected_ref;self.native_select=native_select
        self.native_probe=native_probe;self.native_selection=native_selection
        self.index=None;self.editing=None;self.rule_rows=[];self.setting_rows=[];self.loading=False;self.last_export=None
        self.undo_stack=[];self.redo_stack=[];self.worker=None
        self.CreateStatusBar(2);self.SetStatusWidths([-1,280])
        self.SetStatusText('Offline native GUI • staged edits • no live project writes')
        self.SetStatusText('Local lint ≠ native DRC',1)
        root=wx.BoxSizer(wx.VERTICAL);self.SetSizer(root)
        header=wx.Panel(self);header.SetBackgroundColour(INK);hs=wx.WrapSizer(wx.HORIZONTAL,flags=wx.REMOVE_LEADING_SPACES);header.SetSizer(hs)
        title=label(header,'CONSTRAINT STUDIO',True,18);title.SetForegroundColour('white');hs.Add(title,0,wx.ALL|wx.ALIGN_CENTER_VERTICAL,18)
        self.project_label=label(header,'Open a saved board');self.project_label.SetForegroundColour('#D5DFF0');hs.Add(self.project_label,0,wx.LEFT|wx.ALIGN_CENTER_VERTICAL,12)
        for text,fn in [('Open board…',self.open_board),('BGA / IC wizard…',self.bga),('Review & export…',self.show_review)]:hs.Add(button(header,text,fn),0,wx.ALL|wx.ALIGN_CENTER_VERTICAL,8)
        root.Add(header,0,wx.EXPAND)
        note=label(self,'DEVELOPMENT BUILD  ·  Save your board and Board Setup first. Changes stay in this workspace until you export and review them.')
        root.Add(note,0,wx.EXPAND|wx.ALL,12)
        self.book=aui.AuiNotebook(self,style=aui.AUI_NB_TOP|aui.AUI_NB_SCROLL_BUTTONS|aui.AUI_NB_TAB_MOVE);root.Add(self.book,1,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.rule_page=wx.Panel(self.book);self.matrix_page=wx.Panel(self.book);self.settings_page=wx.Panel(self.book);self.netclass_page=wx.Panel(self.book);self.review_page=wx.Panel(self.book);self.help_page=wx.Panel(self.book)
        for p,t in [(self.rule_page,'Detailed rule'),(self.matrix_page,'Matrices'),(self.netclass_page,'Netclasses'),(self.settings_page,'Board settings'),(self.review_page,'Review & export'),(self.help_page,'Help')]:self.book.AddPage(p,t)
        self.build_rules();self.build_matrix();self.build_netclasses();self.build_settings();self.build_review();self.build_help();self.build_menu()
        from .workbench_ui import WorkspacePanel, ProfilesPanel, ReportsPanel
        self.workbench=WorkspacePanel(self.book,self);self.book.InsertPage(0,self.workbench,'Workspace',True)
        self.profile_panel=ProfilesPanel(self.book,self);self.book.InsertPage(5,self.profile_panel,'Sets & timing')
        self.reports_panel=ReportsPanel(self.book,self);self.book.InsertPage(6,self.reports_panel,'DRC evidence')
        from .advanced_ui import AdvancedPanel
        self.advanced_panel=AdvancedPanel(self.book,self);self.book.AddPage(self.advanced_panel,'Engineering & team')
        self.book.Bind(aui.EVT_AUINOTEBOOK_PAGE_CHANGED,self.page_changed);self.Bind(wx.EVT_CLOSE,self.on_close)
        self.refresh_rules()
        if board_path:
            try:self.load(board_path)
            except Exception as e:error(self,e)
        self.Center()
    def select_page(self,page):
        for i in range(self.book.GetPageCount()):
            if self.book.GetPage(i) is page:self.book.SetSelection(i);return
    def build_menu(self):
        menu=wx.MenuBar();file=wx.Menu();edit=wx.Menu()
        for title,fn in [('Open board…\tCtrl+O',self.open_board),('Import native rule profile…',self.import_rules),('Export native rules only…',self.export_rules),('Export review bundle…\tCtrl+S',self.export),('Reload saved source',self.reload),('Rebuild managed courtyard areas…',self.rebuild_courtyards),('Close',lambda e:self.Close())]:
            item=file.Append(wx.ID_ANY,title);self.Bind(wx.EVT_MENU,fn,item)
        for title,fn in [('Undo workspace action\tCtrl+Z',self.undo),('Redo workspace action\tCtrl+Y',self.redo),('Duplicate rule\tCtrl+D',self.duplicate),('Copy generated native rules',self.copy_rules)]:
            item=edit.Append(wx.ID_ANY,title);self.Bind(wx.EVT_MENU,fn,item)
        menu.Append(file,'File');menu.Append(edit,'Edit')
        help_menu=wx.Menu()
        for title,topic in [('Help on this page\tF1',None),('Help centre','help-centre'),('Getting started','start'),('Constraint reference','constraint-reference'),('Function and property reference','function-reference'),('UI gallery','ui-gallery'),('Troubleshooting','troubleshooting'),('Release status / limitations','limitations')]:
            item=help_menu.Append(wx.ID_ANY,title)
            self.Bind(wx.EVT_MENU,lambda event,t=topic:self.open_help(t),item)
        menu.Append(help_menu,'Help');self.SetMenuBar(menu)
        self.Bind(wx.EVT_CHAR_HOOK,self.help_key)
    def build_rules(self):
        s=wx.BoxSizer(wx.VERTICAL);self.rule_page.SetSizer(s)
        split=wx.SplitterWindow(self.rule_page,style=wx.SP_LIVE_UPDATE);s.Add(split,1,wx.EXPAND|wx.ALL,10)
        left=wx.Panel(split);right=wx.ScrolledWindow(split);right.SetScrollRate(0,12);left.SetBackgroundColour(PANEL);right.SetBackgroundColour(PANEL)
        ls=wx.BoxSizer(wx.VERTICAL);left.SetSizer(ls)
        ls.Add(label(left,'RULE PRIORITY',True,12),0,wx.ALL,12)
        ls.Add(label(left,'Highest priority first • later in native file'),0,wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.search=wx.SearchCtrl(left);self.search.ShowCancelButton(True);ls.Add(self.search,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.rules=wx.ListCtrl(left,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        self.rules.InsertColumn(0,'On',width=44);self.rules.InsertColumn(1,'Rule name',width=260);self.rules.InsertColumn(2,'Severity',width=85)
        ls.Add(self.rules,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        bar=wx.WrapSizer();ls.Add(bar,0,wx.EXPAND|wx.ALL,10)
        for title,fn in [('New',self.new_rule),('Copy',self.duplicate),('Remove',self.remove_rule),('↑ Priority',lambda e:self.move_rule(1)),('↓ Priority',lambda e:self.move_rule(-1)),('Enable / disable',self.toggle_rule)]:bar.Add(button(left,title,fn),0,wx.RIGHT|wx.BOTTOM,5)
        self.search.Bind(wx.EVT_TEXT,lambda e:self.refresh_rules());self.rules.Bind(wx.EVT_LIST_ITEM_SELECTED,self.select_rule)
        rs=wx.BoxSizer(wx.VERTICAL);right.SetSizer(rs)
        g=wx.FlexGridSizer(cols=2,vgap=10,hgap=10);g.AddGrowableCol(1,1);rs.Add(g,0,wx.EXPAND|wx.ALL,14)
        self.name=row(right,g,'Rule name',wx.TextCtrl(right))
        rr=wx.Panel(right);rrs=wx.BoxSizer(wx.HORIZONTAL);rr.SetSizer(rrs)
        self.enabled=wx.CheckBox(rr,label='Enabled');self.enabled.SetValue(True)
        self.severity=choices(rr,['Inherit']+SEVERITIES,'error',False);self.layer=choices(rr,LAYERS,'Any')
        rrs.Add(self.enabled,0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,14);rrs.Add(label(rr,'Severity'),0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,7);rrs.Add(self.severity,0,wx.RIGHT,14)
        rrs.Add(label(rr,'Layer'),0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,7);rrs.Add(self.layer,1,wx.EXPAND)
        row(right,g,'Rule options',rr)
        rs.Add(label(right,'Scope: which objects does this rule affect?',True),0,wx.LEFT|wx.RIGHT,14)
        self.condition=wx.TextCtrl(right,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,78));mono(self.condition);rs.Add(self.condition,0,wx.EXPAND|wx.ALL,14)
        actions=wx.WrapSizer();rs.Add(actions,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,14)
        for title,fn in [('Build scope visually…',self.build_scope),('Selected component',self.scope_component),('Highlight component',self.highlight),('All objects',self.scope_all)]:actions.Add(button(right,title,fn),0,wx.RIGHT|wx.BOTTOM,5)
        rs.Add(label(right,'CONSTRAINTS',True),0,wx.LEFT|wx.RIGHT|wx.BOTTOM,14)
        self.constraints=wx.ListCtrl(right,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        self.constraints.InsertColumn(0,'Constraint',width=240);self.constraints.InsertColumn(1,'Values / selection',width=350)
        rs.Add(self.constraints,1,wx.EXPAND|wx.LEFT|wx.RIGHT,14)
        self.constraints.Bind(wx.EVT_LIST_ITEM_ACTIVATED,self.edit_constraint)
        cb=wx.BoxSizer(wx.HORIZONTAL);rs.Add(cb,0,wx.ALL,14)
        for title,fn in [('Add constraint…',self.add_constraint),('Edit…',self.edit_constraint),('Remove',self.remove_constraint)]:cb.Add(button(right,title,fn),0,wx.RIGHT,8)
        rs.Add(label(right,'Notes / rationale (kept as native-file comments)'),0,wx.LEFT|wx.RIGHT,14)
        self.notes=wx.TextCtrl(right,style=wx.TE_MULTILINE,size=(-1,65));rs.Add(self.notes,0,wx.EXPAND|wx.ALL,14)
        tail=wx.BoxSizer(wx.HORIZONTAL);rs.Add(tail,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,14)
        tail.Add(button(right,'Stage this rule',self.stage_rule),0,wx.RIGHT,10);tail.Add(button(right,'Validate / review',self.show_review),0)
        right.FitInside();right.Bind(wx.EVT_SIZE,lambda e:(right.FitInside(),e.Skip()))
        split.SetMinimumPaneSize(320);split.SplitVertically(left,right,430)
    def checkpoint(self):
        self.undo_stack.append(self.w.clone());self.undo_stack=self.undo_stack[-30:];self.redo_stack.clear()
    def collect(self):
        if self.loading or self.editing is None or self.index is None or self.index>=len(self.w.document.rules):return
        r=self.editing;r.name=self.name.GetValue();r.enabled=self.enabled.GetValue();r.severity='' if self.severity.GetValue()=='Inherit' else self.severity.GetValue()
        r.layer='' if self.layer.GetValue()=='Any' else self.layer.GetValue();r.condition=self.condition.GetValue();r.notes=self.notes.GetValue()
        if r.state()!=self.w.document.rules[self.index].state():
            self.checkpoint();self.w.document.rules[self.index]=copy.deepcopy(r)
    def refresh_rules(self,select_index=None):
        self.loading=True
        self.rules.DeleteAllItems();self.rule_rows=[];q=self.search.GetValue().lower()
        for i in reversed(range(len(self.w.document.rules))):
            r=self.w.document.rules[i]
            if q and q not in (r.name+' '+r.condition+' '+' '.join(c.kind for c in r.constraints)).lower():continue
            n=self.rules.InsertItem(self.rules.GetItemCount(),'✓' if r.enabled else '—');self.rules.SetItem(n,1,r.name);self.rules.SetItem(n,2,r.severity or 'inherit');self.rule_rows.append(i)
            if not r.enabled:self.rules.SetItemTextColour(n,MUTED)
        self.loading=False
        idx=self.index if select_index is None else select_index
        if idx in self.rule_rows:
            n=self.rule_rows.index(idx);self.rules.Select(n);self.rules.EnsureVisible(n)
        elif self.rule_rows:
            self.index=None;self.editing=None;self.rules.Select(0);self.load_rule(self.rule_rows[0])
        else:self.index=None;self.editing=None;self.clear_form()
        self.SetStatusText(f'{len(self.w.document.rules)} rules • highest priority shown first • source files untouched')
    def clear_form(self):
        self.name.ChangeValue('');self.notes.ChangeValue('');self.condition.ChangeValue('');self.constraints.DeleteAllItems()
    def select_rule(self,event):
        if self.loading:return
        n=event.GetIndex()
        if not (0<=n<len(self.rule_rows)):return
        idx=self.rule_rows[n]
        if idx==self.index:return
        self.collect();self.load_rule(idx)
    def load_rule(self,index):
        self.loading=True;self.index=index;self.editing=copy.deepcopy(self.w.document.rules[index]);r=self.editing
        self.name.ChangeValue(r.name);self.enabled.SetValue(r.enabled);self.severity.SetValue(r.severity or 'Inherit');self.layer.SetValue(r.layer or 'Any')
        self.condition.ChangeValue(r.condition);self.notes.ChangeValue(r.notes);self.refresh_constraints();self.loading=False
    def refresh_constraints(self):
        self.constraints.DeleteAllItems()
        if not self.editing:return
        for c in self.editing.constraints:
            spec=CATALOG.get(c.kind);i=self.constraints.InsertItem(self.constraints.GetItemCount(),spec.label if spec else c.kind)
            summary=', '.join(f'{k}: {v}' for k,v in c.values.items()) or c.argument or 'No numeric arguments'
            if c.within_diff_pairs:summary+=' • within each differential pair'
            self.constraints.SetItem(i,1,summary)
    def new_rule(self,event):
        self.collect();self.checkpoint();self.w.document.append(Rule('New rule',severity='error'))
        idx=len(self.w.document.rules)-1;self.load_rule(idx);self.refresh_rules(idx);self.select_page(self.rule_page);self.name.SetFocus();self.name.SelectAll()
    def duplicate(self,event):
        if self.index is None:return
        self.collect();self.checkpoint();self.w.document.append(self.w.document.rules[self.index].clone());self.load_rule(len(self.w.document.rules)-1);self.refresh_rules()
    def remove_rule(self,event):
        if self.index is None:return
        if wx.MessageBox('Remove this rule from the staged workspace?','Remove rule',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION,self)!=wx.YES:return
        self.collect();self.checkpoint();del self.w.document.rules[self.index];self.index=None;self.editing=None;self.refresh_rules()
    def move_rule(self,delta):
        if self.index is None:return
        self.collect();self.checkpoint();idx=self.w.document.move(self.index,delta);self.load_rule(idx);self.refresh_rules(idx)
    def toggle_rule(self,event):
        if self.index is None:return
        self.collect();self.checkpoint();r=self.w.document.rules[self.index];r.enabled=not r.enabled;self.load_rule(self.index);self.refresh_rules()
    def stage_rule(self,event):self.collect();self.refresh_rules();self.SetStatusText('Rule staged in workspace. Native project not modified.')
    def build_scope(self,event):
        if self.editing is None:return
        with ConditionDialog(self,self.condition.GetValue(),self.w.context,self.w.netclasses) as d:
            if d.ShowModal()==wx.ID_OK:self.condition.ChangeValue(d.result)
    def scope_all(self,event):self.condition.ChangeValue('')
    def scope_component(self,event):
        if self.editing is None:return
        refs=[f.reference for f in self.w.context.footprints]
        if not refs:info(self,'Open a saved board first.');return
        with wx.SingleChoiceDialog(self,'Choose a footprint. This matches its children, not the nearby escape tracks.','Component scope',refs) as d:
            if self.selected_ref in refs:d.SetSelection(refs.index(self.selected_ref))
            if d.ShowModal()==wx.ID_OK:self.selected_ref=d.GetStringSelection();self.condition.ChangeValue(function_test('A','memberOfFootprint',[self.selected_ref]).emit())
    def highlight(self,event):
        if not self.native_select:info(self,'Native selection is available only when launched from KiCad. This is not a general rule-match evaluator.');return
        if not self.selected_ref:self.scope_component(event)
        if self.selected_ref:
            try:self.native_select(self.selected_ref)
            except Exception as e:error(self,e)
    def add_constraint(self,event):
        if self.editing is None:self.new_rule(event)
        with ConstraintDialog(self,context=self.w.context,netclasses=self.w.netclasses) as d:
            if d.ShowModal()==wx.ID_OK:self.editing.constraints.append(d.result);self.refresh_constraints()
    def edit_constraint(self,event):
        if self.editing is None:return
        idx=self.constraints.GetFirstSelected()
        if idx<0:return
        with ConstraintDialog(self,self.editing.constraints[idx],self.w.context,self.w.netclasses) as d:
            if d.ShowModal()==wx.ID_OK:self.editing.constraints[idx]=d.result;self.refresh_constraints()
    def remove_constraint(self,event):
        idx=self.constraints.GetFirstSelected()
        if idx>=0 and self.editing:del self.editing.constraints[idx];self.refresh_constraints()
    def bga(self,event):
        self.collect()
        if not self.w.board_path:info(self,'Open a saved board first.');return
        with BGADialog(self,self.w,self.selected_ref) as d:
            if d.ShowModal()!=wx.ID_OK:return
            rules,board_text,guard=d.result;self.checkpoint()
            for r in rules:self.w.document.append(r)
            if board_text:self.w.board_text=board_text;self.w.refresh_board_context()
            if guard:self.w.guards.append(guard)
            self.load_rule(len(self.w.document.rules)-1);self.refresh_rules();self.select_page(self.rule_page)
            self.SetStatusText('Component rules staged. '+('A copied area is staged ONLY in the review board.' if guard else 'No geometry changed.'))

    def rebuild_courtyards(self,event):
        self.collect()
        if not self.w.guards:info(self,'This project has no Constraint Studio-managed courtyard areas.');return
        text='Rebuild these managed areas from the CURRENT SAVED footprint courtyard?\n\n'+'\n'.join(g['reference']+' → '+g['name'] for g in self.w.guards)+'\n\nNew managed scopes refuse independent area/rule edits; legacy scopes retain their rebuild behavior. Snapshot references and attached-area owner UUIDs must still match.'
        if wx.MessageBox(text,'Rebuild managed courtyard areas',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING,self)!=wx.YES:return
        try:
            trial=self.w.clone()
            from .courtyards import sync_workspace
            sync_workspace(trial,explicit=True)
            for i,g in enumerate(trial.guards):
                if g.get('mode')=='footprint-owned-contours-v1':continue
                if g.get('mode')=='footprint-owned-linear-courtyard':
                    from .linked_areas import rebuild_attached_area
                    trial.board_text,new=rebuild_attached_area(trial.context,g)
                else:trial.board_text,new=refresh_copied_area(trial.context,g)
                trial.guards[i]=new;trial.refresh_board_context()
            self.checkpoint();self.w=trial;self.show_review(None)
        except Exception as e:error(self,e)

    def build_matrix(self):
        p=self.matrix_page;s=wx.BoxSizer(wx.VERTICAL);p.SetSizer(s)
        s.Add(label(p,'Pairwise spacing, like a constraint-manager spreadsheet',True,14),0,wx.ALL,16)
        s.Add(label(p,'Blank = inherit. Diagonal = same class/type, not necessarily same net. Clearance checks different nets; physical clearance also checks same-net objects.'),0,wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        bar=wx.WrapSizer();s.Add(bar,0,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        self.mx_scope=choices(p,['netclass','component_class','type','net'],'netclass',False)
        self.mx_kind=choices(p,['clearance','physical_clearance','creepage','courtyard_clearance','hole_clearance','physical_hole_clearance','hole_to_hole','silk_clearance'],'clearance',False)
        self.mx_layer=choices(p,LAYERS,'Any');self.mx_group=wx.TextCtrl(p,value='Main');self.mx_region=choices(p,[])
        for title,c in [('Scope',self.mx_scope),('Constraint',self.mx_kind),('Layer',self.mx_layer),('Set name',self.mx_group),('Inside area (optional)',self.mx_region)]:bar.Add(label(p,title),0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,8);bar.Add(c,0,wx.RIGHT|wx.BOTTOM,15)
        controls=wx.BoxSizer(wx.HORIZONTAL);s.Add(controls,0,wx.EXPAND|wx.ALL,16)
        self.mx_labels=wx.TextCtrl(p,value='Default, Power, HighSpeed');controls.Add(self.mx_labels,1,wx.RIGHT,12)
        controls.Add(button(p,'Build / reset grid',self.reset_matrix),0,wx.RIGHT,8);controls.Add(button(p,'Use project netclasses',self.project_matrix),0)
        self.matrix=gridlib.Grid(p);self.matrix.CreateGrid(3,3);self.matrix.SetDefaultColSize(160);self.matrix.SetRowLabelSize(180)
        self.matrix.Bind(gridlib.EVT_GRID_CELL_CHANGED,self.matrix_changed);s.Add(self.matrix,1,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        bottom=wx.BoxSizer(wx.HORIZONTAL);s.Add(bottom,0,wx.ALL,16)
        bottom.Add(button(p,'Stage / replace this rule set',self.stage_matrix),0,wx.RIGHT,12)
        bottom.Add(label(p,'Existing unrelated rules are kept. Review precedence after generating a matrix.'),0,wx.ALIGN_CENTER_VERTICAL)
        actions=wx.WrapSizer();s.Add(actions,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        for title,fn in [('Import CSV',self.matrix_import_csv),('Export CSV',self.matrix_export_csv),('Load saved matrix',self.matrix_load_saved),('Fill all cells',self.matrix_fill)]:actions.Add(button(p,title,fn),0,wx.RIGHT|wx.BOTTOM,6)
        self.mx_names=['Default','Power','HighSpeed'];self._matrix_busy=False;self.reset_matrix(None)
    def reset_matrix(self,event):
        try:
            names=[x.strip() for x in self.mx_labels.GetValue().split(',') if x.strip()]
            if not names or len(names)>80 or len(set(names))!=len(names):raise ValueError('Use 1–80 unique comma-separated labels')
            n=len(names);g=self.matrix
            if g.GetNumberRows():g.DeleteRows(0,g.GetNumberRows())
            if g.GetNumberCols():g.DeleteCols(0,g.GetNumberCols())
            g.AppendRows(n);g.AppendCols(n);self.mx_names=names
            for i,name in enumerate(names):
                g.SetRowLabelValue(i,name);g.SetColLabelValue(i,name)
                for j in range(n):g.SetReadOnly(i,j,j<i)
            self.mx_scope.SetToolTip('Type names use native capitalization such as Pad, Track, Via. Class labels must exist in the project.')
        except Exception as e:error(self,e)
    def project_matrix(self,event):
        self.mx_scope.SetValue('netclass');self.mx_labels.ChangeValue(', '.join(self.w.netclasses or ['Default']));self.reset_matrix(event)
    def matrix_changed(self,event):
        if self._matrix_busy:return
        i,j=event.GetRow(),event.GetCol();self._matrix_busy=True
        if i!=j:self.matrix.SetCellValue(j,i,self.matrix.GetCellValue(i,j))
        self._matrix_busy=False;event.Skip()
    def stage_matrix(self,event):
        try:
            self.collect();self.matrix.SaveEditControlValue();self.matrix.HideCellEditControl()
            cells={(i,j):self.matrix.GetCellValue(i,j) for i in range(len(self.mx_names)) for j in range(len(self.mx_names))}
            group=self.mx_group.GetValue().strip()
            if not group or '\n' in group:raise ValueError('Enter a nonempty matrix set name')
            layer=self.mx_layer.GetValue();layer='' if layer=='Any' else layer
            region=self.mx_region.GetValue().strip()
            from .linked_areas import all_areas
            if region and not any(a['name']==region and a['rule_area'] for a in all_areas(self.w.context)):raise ValueError('The optional region must be an existing named rule area; reload after creating it in KiCad')
            rules=matrix_rules(self.mx_names,cells,self.mx_kind.GetValue(),self.mx_scope.GetValue(),layer,group,region)
            if not rules and wx.MessageBox('All cells inherit. Remove this managed matrix rule set?', 'Clear matrix constraints',wx.YES_NO|wx.NO_DEFAULT,self)!=wx.YES:return
            from .engineering import rules_fingerprint
            old=self.w.metadata.get('matrices',{}).get(group)
            existing=[r for r in self.w.document.rules if 'CS-MATRIX '+group in r.notes.splitlines()]
            if old and old.get('rules_hash') and rules_fingerprint(existing)!=old['rules_hash']:
                raise ValueError('Matrix rules were edited manually. Use a new matrix set name or restore the managed rules before replacing them.')
            self.checkpoint();replace_generated(self.w.document,rules,'CS-MATRIX '+group)
            self.w.metadata.setdefault('matrices',{})[group]={'labels':self.mx_names[:],'cells':[[cells[i,j] for j in range(len(self.mx_names))] for i in range(len(self.mx_names))],'scope':self.mx_scope.GetValue(),'kind':self.mx_kind.GetValue(),'layer':layer,'region':region,'rules_hash':rules_fingerprint(rules)}
            self.index=None;self.editing=None;self.refresh_rules()
            info(self,f'{len(rules)} pair rules staged. Matrix set {group!r} was replaced in place where present; inspect other overlapping rule priorities.')
        except Exception as e:error(self,e)

    def matrix_import_csv(self,event):
        from .engineering import matrix_from_csv
        with wx.FileDialog(self,'Import a symmetric matrix',wildcard='CSV (*.csv)|*.csv',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()!=wx.ID_OK:return
            try:
                names,cells=matrix_from_csv(pathlib.Path(d.GetPath()).read_text('utf-8-sig'))
                if any(',' in n for n in names):raise ValueError('This GUI uses comma-separated labels; rename labels containing commas before importing')
                self.mx_labels.SetValue(', '.join(names));self.reset_matrix(None)
                for (i,j),v in cells.items():self.matrix.SetCellValue(i,j,v)
            except Exception as e:error(self,e)
    def matrix_export_csv(self,event):
        from .engineering import matrix_to_csv
        self.matrix.SaveEditControlValue();self.matrix.HideCellEditControl()
        with wx.FileDialog(self,'Export spacing matrix',wildcard='CSV (*.csv)|*.csv',defaultFile='clearance-matrix.csv',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()!=wx.ID_OK:return
            try:atomic_write(d.GetPath(),matrix_to_csv(self.mx_names,{(i,j):self.matrix.GetCellValue(i,j) for i in range(len(self.mx_names)) for j in range(len(self.mx_names))}).encode('utf-8-sig'))
            except Exception as e:error(self,e)
    def matrix_load_saved(self,event):
        saved=self.w.metadata.get('matrices',{});names=list(saved)
        if not names:info(self,'No managed matrix definitions are saved in this project. Existing native rule blocks remain editable in the rule worksheet.');return
        with wx.SingleChoiceDialog(self,'Choose a matrix','Load matrix',names) as d:
            if d.ShowModal()!=wx.ID_OK:return
            name=names[d.GetSelection()];m=saved[name];self.mx_group.SetValue(name);self.mx_labels.SetValue(', '.join(m['labels']));self.reset_matrix(None)
            self.mx_scope.SetValue(m['scope']);self.mx_kind.SetValue(m['kind']);self.mx_layer.SetValue(m['layer'] or 'Any');self.mx_region.SetValue(m['region'])
            for i,row in enumerate(m['cells']):
                for j,v in enumerate(row):self.matrix.SetCellValue(i,j,v)
    def matrix_fill(self,event):
        with wx.TextEntryDialog(self,'Fill all pair cells. Blank means inherit.','Fill matrix') as d:
            if d.ShowModal()!=wx.ID_OK:return
            try:
                v=d.GetValue().strip()
                if v:
                    from .model import numeric
                    numeric(v)
                for i in range(len(self.mx_names)):
                    for j in range(len(self.mx_names)):self.matrix.SetCellValue(i,j,v)
            except Exception as e:error(self,e)

    def build_settings(self):
        p=self.settings_page;s=wx.BoxSizer(wx.VERTICAL);p.SetSizer(s)
        s.Add(label(p,'Native board settings — inspect and stage existing fields',True,14),0,wx.ALL,16)
        s.Add(label(p,'Board-wide minimums are HARD floors. This editor never automatically lowers them. Existing JSON fields retain their native types and units.\nChanging a setting affects the staged .kicad_pro only; review/reopen the project to apply. Collection structure is preserved; this grid edits existing scalar values.'),0,wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        self.settings_search=wx.SearchCtrl(p);s.Add(self.settings_search,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        self.settings=gridlib.Grid(p);self.settings.CreateGrid(0,3);self.settings.SetColLabelValue(0,'Native setting path');self.settings.SetColLabelValue(1,'Type');self.settings.SetColLabelValue(2,'Staged value')
        self.settings.SetColSize(0,650);self.settings.SetColSize(1,110);self.settings.SetColSize(2,240);self.settings.SetRowLabelSize(45)
        s.Add(self.settings,1,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        self.settings_search.Bind(wx.EVT_TEXT,lambda e:self.refresh_settings());self.settings.Bind(gridlib.EVT_GRID_CELL_CHANGED,self.setting_changed)
    def refresh_settings(self):
        g=self.settings
        if g.GetNumberRows():g.DeleteRows(0,g.GetNumberRows())
        q=self.settings_search.GetValue().lower();self.setting_rows=[(path,v) for path,v in self.w.settings_rows() if q in '.'.join(map(str,path)).lower()]
        if self.setting_rows:g.AppendRows(len(self.setting_rows))
        for i,(path,v) in enumerate(self.setting_rows):
            g.SetCellValue(i,0,'.'.join(map(str,path)));g.SetCellValue(i,1,type(v).__name__ if v is not None else 'inherit / null');g.SetCellValue(i,2,text_value(v));g.SetReadOnly(i,0);g.SetReadOnly(i,1)
            # Class identities are not ordinary scalar values: renaming needs a
            # project-wide reference migration, which this release does not do.
            if tuple(path[:2])==('net_settings','classes') and path[-1]=='name':g.SetReadOnly(i,2)
            if isinstance(v,bool):g.SetCellEditor(i,2,gridlib.GridCellChoiceEditor(['true','false'],False))
    def setting_changed(self,event):
        i=event.GetRow()
        if not 0<=i<len(self.setting_rows):return
        path,_=self.setting_rows[i];old=get_path(self.w.project,path)
        try:
            new=parse_scalar(self.settings.GetCellValue(i,2),old);self.collect();self.checkpoint();set_path(self.w.project,path,new)
            self.setting_rows[i]=(path,new);self.refresh_netclasses();self.SetStatusText('Native project field staged; source project unchanged.')
        except Exception as e:self.settings.SetCellValue(i,2,text_value(old));error(self,e)

    NC_FIELDS=['name','clearance','track_width','via_diameter','via_drill','microvia_diameter','microvia_drill','diff_pair_width','diff_pair_gap','diff_pair_via_gap']
    def build_netclasses(self):
        p=self.netclass_page;s=wx.BoxSizer(wx.VERTICAL);p.SetSizer(s)
        s.Add(label(p,'Netclass constraints & pattern assignments',True,14),0,wx.ALL,16)
        s.Add(label(p,'Numeric dimensions are millimetres; null means inherited. Unknown class fields are preserved. Class order is retained; overlapping assignments need native priority review.'),0,wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        self.nc=gridlib.Grid(p);self.nc.CreateGrid(0,len(self.NC_FIELDS));self.nc.SetDefaultColSize(125);self.nc.SetColSize(0,180)
        for i,f in enumerate(self.NC_FIELDS):self.nc.SetColLabelValue(i,f.replace('_',' '))
        s.Add(self.nc,1,wx.EXPAND|wx.LEFT|wx.RIGHT,16);self.nc.Bind(gridlib.EVT_GRID_CELL_CHANGED,self.nc_changed)
        bar=wx.BoxSizer(wx.HORIZONTAL);s.Add(bar,0,wx.ALL,16)
        for title,fn in [('Add netclass',self.nc_add),('Remove selected netclass',self.nc_remove)]:bar.Add(button(p,title,fn),0,wx.RIGHT,10)
        s.Add(label(p,'Pattern assignments — native wildcard netname patterns',True),0,wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        self.patterns=gridlib.Grid(p);self.patterns.CreateGrid(0,2);self.patterns.SetColLabelValue(0,'Netclass');self.patterns.SetColLabelValue(1,'Pattern');self.patterns.SetColSize(0,230);self.patterns.SetColSize(1,550)
        s.Add(self.patterns,1,wx.EXPAND|wx.LEFT|wx.RIGHT,16);self.patterns.Bind(gridlib.EVT_GRID_CELL_CHANGED,self.pattern_changed)
        bar2=wx.BoxSizer(wx.HORIZONTAL);s.Add(bar2,0,wx.ALL,16)
        bar2.Add(button(p,'Add assignment',self.pattern_add),0,wx.RIGHT,10);bar2.Add(button(p,'Remove selected assignment',self.pattern_remove),0)
    def classes(self):return self.w.project.get('net_settings',{}).get('classes',[])
    def assignments(self):return self.w.project.get('net_settings',{}).get('netclass_patterns',[])
    def refresh_netclasses(self):
        for g in (self.nc,self.patterns):
            if g.GetNumberRows():g.DeleteRows(0,g.GetNumberRows())
        cls=self.classes();pa=self.assignments()
        if cls:self.nc.AppendRows(len(cls))
        for i,item in enumerate(cls):
            for j,key in enumerate(self.NC_FIELDS):self.nc.SetCellValue(i,j,text_value(item.get(key)))
        if pa:self.patterns.AppendRows(len(pa))
        for i,item in enumerate(pa):self.patterns.SetCellValue(i,0,item.get('netclass',''));self.patterns.SetCellValue(i,1,item.get('pattern',''))
    def nc_changed(self,event):
        i,j=event.GetRow(),event.GetCol();key=self.NC_FIELDS[j];old=self.classes()[i].get(key)
        try:
            text=self.nc.GetCellValue(i,j).strip()
            if key=='name':
                if old=='Default' and text!=old:raise ValueError('Do not rename Default')
                if not text or text!=old and text in self.w.netclasses:raise ValueError('Netclass names must be unique and nonempty')
                if text!=old:raise ValueError('Renaming requires updating every native reference and rule. Create a new class and migrate explicitly in Board Setup.')
                new=text
            else:
                new=None if text.lower()=='null' else float(text)
                import math
                if new is not None and (new<0 or not math.isfinite(new)):raise ValueError('Use a finite nonnegative dimension in mm, or null')
            self.collect();self.checkpoint();self.classes()[i][key]=new;self.refresh_settings()
        except Exception as e:self.nc.SetCellValue(i,j,text_value(old));error(self,e)
    def nc_add(self,event):
        if 'net_settings' not in self.w.project:info(self,'Open a project with native netclass settings first.');return
        with wx.TextEntryDialog(self,'Name for the new class. Numeric fields initially inherit.','Add netclass') as d:
            if d.ShowModal()!=wx.ID_OK:return
            name=d.GetValue().strip()
            if not name or name in self.w.netclasses:error(self,'Choose a unique nonempty class name');return
            self.collect();self.checkpoint();self.classes().append({'name':name,**{k:None for k in self.NC_FIELDS[1:]}});self.refresh_netclasses();self.refresh_settings()
    def nc_remove(self,event):
        i=self.nc.GetGridCursorRow()
        if not 0<=i<len(self.classes()):return
        name=self.classes()[i].get('name')
        if name=='Default':error(self,'Default cannot be removed');return
        if any(p.get('netclass')==name for p in self.assignments()) or name in self.w.document.emit():error(self,'Class is referenced by an assignment or a custom rule. Migrate those references first.');return
        if wx.MessageBox('Remove class '+name+'? Review explicit netclass assignments in Board Setup as well.','Remove netclass',wx.YES_NO|wx.NO_DEFAULT,self)!=wx.YES:return
        self.collect();self.checkpoint();self.classes().pop(i);self.refresh_netclasses();self.refresh_settings()
    def pattern_changed(self,event):
        i,j=event.GetRow(),event.GetCol();key='netclass' if j==0 else 'pattern';old=self.assignments()[i].get(key,'');new=self.patterns.GetCellValue(i,j).strip()
        if not new or (j==0 and new not in self.w.netclasses):self.patterns.SetCellValue(i,j,old);error(self,'Enter a pattern and an existing netclass name');return
        self.collect();self.checkpoint();self.assignments()[i][key]=new;self.refresh_settings()
    def pattern_add(self,event):
        if not self.w.netclasses:info(self,'Open a native project with netclasses first.');return
        with wx.SingleChoiceDialog(self,'Choose a netclass','Pattern assignment',self.w.netclasses) as d:
            if d.ShowModal()!=wx.ID_OK:return
            name=d.GetStringSelection()
        with wx.TextEntryDialog(self,'Enter a net name or wildcard pattern.','Pattern assignment') as d:
            if d.ShowModal()!=wx.ID_OK or not d.GetValue().strip():return
            self.collect();self.checkpoint();self.w.project['net_settings'].setdefault('netclass_patterns',[]).append({'netclass':name,'pattern':d.GetValue().strip()});self.refresh_netclasses();self.refresh_settings()
    def pattern_remove(self,event):
        i=self.patterns.GetGridCursorRow()
        if 0<=i<len(self.assignments()):self.collect();self.checkpoint();self.assignments().pop(i);self.refresh_netclasses();self.refresh_settings()

    def build_review(self):
        p=self.review_page;s=wx.BoxSizer(wx.VERTICAL);p.SetSizer(s)
        s.Add(label(p,'Review staged changes, then ask KiCad to validate them',True,14),0,wx.ALL,16)
        s.Add(label(p,'KiCad 10 does not expose a supported IPC rule setter. This build exports review files; it does not hot-write an open project.\nUse the supplied offline apply tool only after closing every source-project editor. Clipboard transfer is available for rules-only changes.'),0,wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        actions=wx.WrapSizer();s.Add(actions,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        for title,fn in [('Refresh lint & diff',self.show_review),('Copy native rules',self.copy_rules),('Export review bundle…',self.export),('Run native DRC on export',self.run_native)]:actions.Add(button(p,title,fn),0,wx.RIGHT|wx.BOTTOM,8)
        clirow=wx.BoxSizer(wx.HORIZONTAL);s.Add(clirow,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        clirow.Add(label(p,'kicad-cli path (optional)'),0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,12);self.cli_path=wx.TextCtrl(p);clirow.Add(self.cli_path,1,wx.RIGHT,8);clirow.Add(button(p,'Browse…',self.browse_cli),0)
        self.review_book=wx.Notebook(p);s.Add(self.review_book,1,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        self.issues=wx.TextCtrl(self.review_book,style=wx.TE_MULTILINE|wx.TE_READONLY);self.diff=wx.TextCtrl(self.review_book,style=wx.TE_MULTILINE|wx.TE_READONLY);self.native_text=wx.TextCtrl(self.review_book,style=wx.TE_MULTILINE|wx.TE_READONLY);self.rules_text=wx.TextCtrl(self.review_book,style=wx.TE_MULTILINE|wx.TE_READONLY)
        for ctrl,title in [(self.issues,'Local lint'),(self.diff,'File diff'),(self.rules_text,'Generated native rules'),(self.native_text,'Native DRC report')]:mono(ctrl);self.review_book.AddPage(ctrl,title)
        self.native_text.ChangeValue('Native DRC has NOT been run. A successful local lint result is not a geometry or syntax sign-off.')
    def show_review(self,event):
        self.collect()
        try:
            issues=self.w.issues();self.issues.ChangeValue('\n\n'.join(f'{i.severity.upper()}  |  {i.rule}\n{i.message}' for i in issues) or 'No local issues detected. Native KiCad syntax and geometry checking are still required.')
            self.diff.ChangeValue(self.w.review());self.rules_text.ChangeValue(self.w.document.emit());self.select_page(self.review_page)
        except Exception as e:error(self,e)
    def browse_cli(self,event):
        with wx.FileDialog(self,'Locate kicad-cli executable',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()==wx.ID_OK:self.cli_path.ChangeValue(d.GetPath())
    def copy_rules(self,event):
        self.collect()
        if any(x.severity=='error' for x in self.w.issues()):error(self,'Fix local lint errors before copying generated rules. See Review.');return
        if self.w.board_text and self.w.board_text!=((self.w.originals.get('.kicad_pcb') or b'').decode('utf-8-sig')):
            error(self,'This workspace contains staged geometry changes. Rules-only clipboard transfer would omit the required area. Export the full review bundle.');return
        if wx.TheClipboard.Open():
            try:wx.TheClipboard.SetData(wx.TextDataObject(self.w.document.emit()));wx.TheClipboard.Flush()
            finally:wx.TheClipboard.Close()
            info(self,'Generated rules copied. In KiCad Board Setup → Custom Rules, paste into the native editor, run its syntax check, inspect the changes, and accept. This does not apply staged .kicad_pro settings.')
        else:error(self,'Clipboard is in use')
    def export(self,event):
        self.collect()
        if not self.w.board_path:info(self,'Open a saved board before exporting a project review bundle.');return
        try:
            self.w.verify_originals()
            from .courtyards import sync_workspace
            trial=self.w.clone();names=sync_workspace(trial)
            if names:self.checkpoint();self.w=trial;self.index=None;self.editing=None;self.refresh_rules()
        except Exception as e:error(self,e);return
        if any(x.severity=='error' for x in self.w.issues()):
            if wx.MessageBox('Local lint contains errors. Export a REVIEW-ONLY bundle? The offline apply tool will refuse it.','Export with errors',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING,self)!=wx.YES:return
        with wx.DirDialog(self,'Choose an EMPTY review folder outside the source project',style=wx.DD_DEFAULT_STYLE) as d:
            if d.ShowModal()!=wx.ID_OK:return
            try:self.last_export=self.w.export_bundle(d.GetPath());self.SetStatusText('Review bundle exported: '+str(self.last_export));info(self,'Review bundle exported; source files were NOT changed.\n\nOpen its board in KiCad, verify scope and settings, and run native DRC. The source release includes the offline apply tool with fingerprint checks and backups.')
            except Exception as e:error(self,e)
    def run_native(self,event):
        self.collect()
        if self.worker and self.worker.is_alive():info(self,'A native validation process is already running.');return
        if not self.last_export:info(self,'Export a review bundle first. Native DRC runs only on that exported copy.');return
        manifest=json.loads((self.last_export/'constraint-studio-manifest.json').read_text('utf-8'))
        # A changed workspace must not be attributed to an older exported validation.
        if self.w.dirty:error(self,'Workspace changed since export. Export a new bundle before validation.');return
        export_dir=self.last_export
        validation_snapshot=self.w.state()
        board=export_dir/self.w.board_path.name;cli=self.cli_path.GetValue().strip()
        self.native_text.ChangeValue('Running native KiCad DRC on the exported board. Zones are refilled in memory; source and export geometry are not saved by this command.\n')
        self.review_book.SetSelection(3)
        def work():
            try:
                result=native_drc(board,cli)
                text=json.dumps(result,indent=2,ensure_ascii=False)
                atomic_write(export_dir/'constraint-studio-validation-log.json',text.encode())
            except Exception as e:result=None;text='NATIVE VALIDATION FAILED / UNAVAILABLE\n'+str(e)
            wx.CallAfter(finish,text,result)
        def finish(text,result):
            if self and not self.IsBeingDeleted():
                self.native_text.ChangeValue(('STALE FOR CURRENT WORKSPACE — this report belongs to the earlier exported snapshot.\n\n' if self.w.state()!=validation_snapshot else '')+text);self.SetStatusText('Native validation finished. Read the report; an exit code alone is not certification.')
                if result and isinstance(result.get('data'),dict):
                    try:self.reports_panel.load_data(result['data'],'Native DRC on exported review: '+str(export_dir))
                    except Exception as e:self.SetStatusText('Report available in Review; evidence-table import: '+str(e))
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()
    def import_rules(self,event):
        self.collect()
        with wx.FileDialog(self,'Import native rule profile',wildcard='KiCad rules (*.kicad_dru)|*.kicad_dru|All files|*.*',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()!=wx.ID_OK:return
            try:
                incoming=RuleDocument.load(pathlib.Path(d.GetPath()).read_text('utf-8-sig'))
                self.checkpoint()
                # Append the imported rules at higher priority; this is not whole-file replacement.
                for r in incoming.rules:self.w.document.append(copy.deepcopy(r))
                self.index=None;self.editing=None;self.refresh_rules();info(self,f'{len(incoming.rules)} rules appended at higher priority. Review overlap and project-specific names.')
            except Exception as e:error(self,e)
    def export_rules(self,event):
        self.collect()
        with wx.FileDialog(self,'Export native rules (not a project apply)',wildcard='KiCad rules (*.kicad_dru)|*.kicad_dru',defaultFile='constraint-profile.kicad_dru',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()!=wx.ID_OK:return
            p=pathlib.Path(d.GetPath()).resolve()
            if self.w.board_path and p==self.w.board_path.with_suffix('.kicad_dru'):error(self,'Do not hot-write the source rules. Export to a separate file or use native clipboard transfer.');return
            try:atomic_write(p,self.w.document.emit().encode());info(self,'Rule profile exported. Board settings and staged geometry are not included in this rules-only file.')
            except Exception as e:error(self,e)
    def build_help(self):
        s=wx.BoxSizer(wx.VERTICAL);self.help_page.SetSizer(s)
        try:
            self.help_panel=HelpPanel(self.help_page);s.Add(self.help_panel,1,wx.EXPAND)
            self.help_html=self.help_panel.content
        except Exception as exc:
            self.help_panel=None
            text=wx.StaticText(self.help_page,label='Offline help is unavailable. Reinstall the complete matching PCM package.\n'+str(exc))
            text.Wrap(760);s.Add(text,0,wx.ALL,20)
    def open_help(self,topic=None):
        if topic is None:
            page=self.book.GetCurrentPage();title=self.book.GetPageText(self.book.GetSelection());sub=''
            nested=getattr(page,'book',None)
            if nested is not None and nested.GetSelection()>=0:sub=nested.GetPageText(nested.GetSelection())
            if page is getattr(self,'workbench',None):
                nested=page.midbook;sub=nested.GetPageText(nested.GetSelection())
            topic=topic_for_page(title,sub)
        self.select_page(self.help_page)
        if self.help_panel:self.help_panel.navigate(topic)
    def help_key(self,event):
        if event.GetKeyCode()==wx.WXK_F1:self.open_help()
        else:event.Skip()
    def load(self,path):
        self.w=Workspace.load(path);self.index=None;self.editing=None;self.undo_stack=[];self.redo_stack=[];self.last_export=None
        self.project_label.SetLabel(self.w.board_path.name);self.SetTitle(TITLE+' — '+self.w.board_path.name)
        self.refresh_rules();self.refresh_settings();self.refresh_netclasses();self.project_matrix(None)
        from .linked_areas import all_areas
        self.mx_region.SetItems([a['name'] for a in all_areas(self.w.context) if a['rule_area']]);self.mx_region.SetValue('')
        if hasattr(self,'workbench'):self.workbench.refresh();self.profile_panel.refresh()
    def confirm_discard(self):
        self.collect()
        if not self.w.dirty:return True
        return wx.MessageBox('Discard unexported staged changes? Source files have not been modified.','Unexported changes',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING,self)==wx.YES
    def open_board(self,event):
        if not self.confirm_discard():return
        with wx.FileDialog(self,'Open saved KiCad PCB',wildcard='KiCad board (*.kicad_pcb)|*.kicad_pcb',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()==wx.ID_OK:
                try:self.load(d.GetPath())
                except Exception as e:error(self,e)
    def reload(self,event):
        if self.w.board_path and self.confirm_discard():
            try:self.load(self.w.board_path)
            except Exception as e:error(self,e)
    def undo(self,event):
        self.collect()
        if not self.undo_stack:return
        self.redo_stack.append(self.w.clone());self.w=self.undo_stack.pop();self.index=None;self.editing=None;self.refresh_rules();self.refresh_settings();self.refresh_netclasses()
        if hasattr(self,'workbench'):self.workbench.refresh();self.profile_panel.refresh_review()
    def redo(self,event):
        if not self.redo_stack:return
        self.undo_stack.append(self.w.clone());self.w=self.redo_stack.pop();self.index=None;self.editing=None;self.refresh_rules();self.refresh_settings();self.refresh_netclasses()
        if hasattr(self,'workbench'):self.workbench.refresh();self.profile_panel.refresh_review()
    def page_changed(self,event):
        if event.GetEventObject() is not self.book:event.Skip();return
        if hasattr(self,'name'):self.collect()
        if hasattr(self,'workbench') and self.book.GetCurrentPage() is self.workbench:self.workbench.refresh()
        if hasattr(self,'profile_panel') and self.book.GetCurrentPage() is self.profile_panel:self.profile_panel.refresh_review()
        event.Skip()
    def on_close(self,event):
        if self.worker and self.worker.is_alive():
            info(self,'Native validation is still running. Close this window after it finishes.');event.Veto();return
        if not self.confirm_discard():event.Veto();return
        self.Destroy()


def launch(board_path='',selected_ref='',parent=None,native_select=None,native_probe=None,native_selection=None):
    frame=StudioFrame(parent,board_path,selected_ref,native_select,native_probe,native_selection)
    area=wx.GetClientDisplayRect();frame.SetSize((min(1560,area.width-32),min(960,area.height-48)))
    frame.Center();frame.Show();return frame
