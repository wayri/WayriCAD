"""Offline help data/search and safe asset routing. No wx or network dependency."""
from html.parser import HTMLParser
from pathlib import Path
import html,json,re

HELP_ROOT=Path(__file__).resolve().parent/'help'
PAGE_TOPICS={
 'Workspace':'workspace','Detailed rule':'rule-editor','Matrices':'matrices',
 'Netclasses':'netclasses','Board settings':'board-settings','Sets & timing':'profiles',
 'DRC evidence':'drc-evidence','Review & export':'review-export','Help':'help-centre',
 'Engineering & team':'managed-regions',
 'Constraint sets':'profiles','Timing budget & stackup':'timing-budget',
 'Local review history':'local-review','Managed regions':'managed-regions',
 'Shared catalog':'catalogs','Signed reviews':'signed-reviews','Signal paths':'signal-paths',
 '2-D line solver':'field-solver','Native inspection':'native-inspection',
 'Constraint worksheet':'workspace','Layout scope preview':'layout-preview',
}

class _Text(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[]
    def handle_data(self,data):self.parts.append(data)
    def handle_starttag(self,tag,attrs):
        if tag in ('p','h1','h2','h3','tr','li','br','pre','blockquote'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('p','h1','h2','h3','tr','li','pre','blockquote'):self.parts.append('\n')
        elif tag in ('td','th'):self.parts.append(' | ')

def plain_text(markup):
    p=_Text();p.feed(str(markup));return re.sub(r'\n[ \t]*\n[ \t]*\n+','\n\n',''.join(p.parts)).strip()

def topic_for_page(title,subpage=''):
    return PAGE_TOPICS.get(subpage,PAGE_TOPICS.get(title,'start'))

class HelpLibrary:
    def __init__(self,root=None):
        self.root=Path(root or HELP_ROOT)
        data=json.loads((self.root/'topics.json').read_text('utf-8'))
        if data.get('schema')!=1:raise ValueError('Unsupported offline-help schema')
        self.version=str(data['version']);self.counts=data['counts'];self.topics=data['topics']
        self.by_id={t['id']:t for t in self.topics}
        if len(self.by_id)!=len(self.topics):raise ValueError('Duplicate offline-help topic')
        self._search={t['id']:' '.join([t['title'],t['summary'],t.get('keywords',''),plain_text(t['html'])]).casefold() for t in self.topics}
    def topic(self,id):return self.by_id.get(id,self.by_id['start'])
    def search(self,query='',section=''):
        words=re.findall(r'[\w.-]+',query.casefold())
        rows=[]
        for idx,t in enumerate(self.topics):
            if section and t['section']!=section:continue
            text=self._search[t['id']]
            if words and not all(w in text for w in words):continue
            title=t['title'].casefold();key=t.get('keywords','').casefold()
            score=sum(10*(w in title)+4*(w in key) for w in words)
            rows.append((-score,idx,t))
        return [t for _,_,t in sorted(rows,key=lambda x:(x[0],x[1]))]
    def asset_path(self,name):
        # No arbitrary local-file access via a help link.
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:png|jpg|jpeg)',name):raise ValueError('Invalid help image link')
        root=(self.root/'images').resolve();p=(root/name).resolve()
        if p.parent!=root or not p.is_file():raise ValueError('Packaged help image is missing')
        return p
    def body(self,id,width=720):
        t=self.topic(id);body=t['html']
        def image(m):
            try:return 'src="'+self.asset_path(m[1]).as_uri()+'"'
            except ValueError:return 'src=""'
        body=re.sub(r'src="images/([^"]+)"',image,body)
        body=re.sub(r'(<img\b[^>]*?)width="\d+"',lambda m:m[1]+'width="'+str(max(240,min(720,int(width))))+'"',body)
        links=' · '.join('<a href="help:'+k+'">'+html.escape(self.by_id[k]['title'])+'</a>' for k in t.get('related',[]) if k in self.by_id)
        route='<p><b>Open:</b> '+html.escape(t['route'])+'</p>' if t.get('route') else ''
        return '<html><body bgcolor="#FFFFFF" text="#17253C"><p><small>CONSTRAINT STUDIO '+html.escape(self.version)+' · '+html.escape(t['section'])+'</small></p><h1>'+html.escape(t['title'])+'</h1><p><b>'+html.escape(t['summary'])+'</b></p>'+route+body+'<hr><h2>Related help</h2><p>'+links+'</p><p><small>Development build. Source-derived renders are not native acceptance evidence.</small></p></body></html>'

class HelpHistory:
    def __init__(self):self.items=[];self.position=-1
    @property
    def can_back(self):return self.position>0
    @property
    def can_forward(self):return self.position+1<len(self.items)
    def visit(self,id):
        if self.position>=0 and self.items[self.position]==id:return
        self.items=self.items[:self.position+1]+[id];self.position=len(self.items)-1
    def back(self):
        if self.can_back:self.position-=1
        return self.items[self.position] if self.position>=0 else 'start'
    def forward(self):
        if self.can_forward:self.position+=1
        return self.items[self.position] if self.position>=0 else 'start'

# Wording explains side effects/limits rather than only repeating the label.
TOOLTIPS={
 'Open board…':'Load a saved snapshot. Save the PCB and Board Setup first; opening does not write the live board.',
 'BGA / IC wizard…':'Create a local component exception. Review both-object containment and global manufacturing floors.',
 'BGA / component exception':'Create a footprint/area exception; crossing items are not split automatically.',
 'Review & export…':'Inspect lint, native rules and file diffs, then export a separate review copy.',
 'New scoped rule':'Create a rule from the declared scope selection; check its condition before staging.',
 'Edit selected rule':'Open the selected worksheet rule in the detailed form.',
 'Focus worksheet / restore':'Hide or restore side panes for more editing space.',
 'Refresh':'Refresh this view from the workspace; this is not a reload of external source edits.',
 'Include disabled':'Show preserved disabled rules. Ignore severity is different from disabling.',
 'Fill selected rows':'Change one supported bound across selected rows. Check units and min/opt/max ordering.',
 'Copy rows':'Copy selected worksheet rows as tabular text; this does not apply changes.',
 'Paste min / opt / max':'Paste exactly three tab-separated value columns into selected rows.',
 'Export CSV':'Export this table, not a complete project bundle. Use review export for geometry/settings.',
 'Higher priority':'Move selected rule toward the highest-priority end; native-file order is reversed.',
 'Lower priority':'Reduce the selected rule priority. The strictest numeric value does not automatically win.',
 'Find matches':'Evaluate supported offline predicates; unknown is not a proven non-match.',
 'Cross-probe matches':'Request selection in the matching native board when the bridge supports it.',
 'Use KiCad selection':'Import real native A/B selection when available; preview flags may not be native selection.',
 'Explain priority':'Show a conservative offline trace, not a complete native winning-rule query.',
 'Build scope visually…':'Build explicit A/B property/function conditions with nested AND, OR and NOT.',
 'Selected component':'Select footprint children. Nearby escape tracks are not children or an implicit area.',
 'All objects':'Clear the scope condition. Check that a global rule is actually intended.',
 'Add constraint…':'Choose a catalog form. F1 opens its field-specific reference.',
 'Stage this rule':'Commit form values to the plugin workspace only; no live project write.',
 'Enable / disable':'Change active emission while preserving the rule for later restoration.',
 'Stage / replace this rule set':'Generate pair rules. Modified managed rules block silent replacement.',
 'Build / reset grid':'Rebuild the matrix labels/grid; preserve current cell data before resetting.',
 'Use project netclasses':'Initialize matrix labels from the loaded saved project.',
 'Fill all cells':'Set all symmetric pair cells. Blank means inherit; zero is explicit.',
 'Load saved matrix':'Restore the editable matrix definition stored in project metadata.',
 'Preview generated rules / diff':'Inspect output before staging; preview alone makes no project changes.',
 'Stage set':'Instantiate/update this profile after validating required bindings and migration consent.',
 'Ungroup instance':'Remove management metadata but retain generated rules for manual editing.',
 'Create set from selected rules':'Capture selected rule blocks and choose typed parameters to expose.',
 'Calculate PCB allocation':'Subtract supplied package/connector/margin terms; no routed-delay extraction.',
 'Read saved stackup':'Read saved stackup data; material permittivity is not automatically effective permittivity.',
 'Record local review':'Record a content-bound self-attested note; not an authenticated signature.',
 'Inspect managed scopes':'Check managed-region status against saved/staged geometry and ownership guards.',
 'Regenerate eligible scopes':'Stage safe saved-snapshot updates; refuse independently edited managed content.',
 'Check versions':'Explicitly read the selected catalog. No automatic background polling.',
 'Import selected version':'Import/pin a definition; existing instances are not silently migrated.',
 'Publish local definition':'Write one chosen definition to the shared folder after confirmation; never the board.',
 'Create encrypted signing key':'Requires cryptography. Save the private key outside the project; share only its public companion.',
 'Create / add trusted public key':'Administrator action: independently verify the public fingerprint before assigning an approver.',
 'Sign current content':'Bind a decision to the current staged content. This does not perform native DRC.',
 'Verify signed reviews':'Verify against the supplied external registry and threshold; stale/rejected content can fail.',
 'Preview logical path':'Resolve declared component pad pass-throughs, not arbitrary routed copper.',
 'Stage per-net rules':'Create separate native fromTo rules using explicit per-segment budgets.',
 'Solve coarse + refined grids':'Run the ideal 2-D solver with mesh/domain checks. Does not change constraints.',
 'Cancel calculation':'Request cancellation of the active field calculation.',
 'Save numeric report':'Save the actual completed solver result and assumptions, not an acceptance certificate.',
 'Open native clearance resolution':'Select two items directly in KiCad; this inspects current open-board rules only.',
 'Open native constraint resolution':'Select one item directly in KiCad; staged plugin rules are not applied first.',
 'Copy native rules':'Rules only: does not apply project settings and refuses staged area geometry.',
 'Export review bundle…':'Write a separate review snapshot into a new empty folder outside the source project.',
 'Run native DRC on export':'Validate the latest exported copy with kicad-cli; unavailable/failed is not passed.',
 'Refresh lint & diff':'Collect form edits and refresh local checks/diffs, not a native geometry run.',
 'Local copper clearance':'Different-net copper minimum inside the chosen scope; global floors still apply.',
 'Local track width (optional)':'Leave blank to omit. A crossing segment is not automatically split at the area boundary.',
 'Boundary policy':'Strict enclosure, intersection and component-child membership have different boundary effects.',
 'Minimum':'An explicit lower bound where supported. Blank is unspecified, not zero.',
 'Preferred / tuning target':'A preferred native routing/tuning value, not a hard minimum or maximum.',
 'Maximum':'An explicit upper bound where supported. Keep all bounds in one unit domain.',
 'Relative permittivity':'Bulk relative permittivity for this simplified field geometry; not an automatic stackup extraction.',
 'Differential edge gap (blank = single)':'Edge-to-edge gap in mm; blank selects the single-conductor calculation.',
 'Required independent approvals':'Number of distinct trusted approver identities required; a current rejection blocks approval.',
}
def tooltip_for(label):
    key=str(label).split('\t')[0].strip()
    if key in TOOLTIPS:return TOOLTIPS[key]
    for prefix in ('Minimum','Preferred / tuning target','Maximum'):
        if key.startswith(prefix):return TOOLTIPS[prefix]+' Units: '+key.rsplit('(',1)[-1].rstrip(')') if '(' in key else TOOLTIPS[prefix]
    return ''
