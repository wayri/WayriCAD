"""KiCad 10 documented rule vocabulary; no network or KiCad imports required.
Source references are recorded in docs/RESEARCH.md. Not a replacement DRC engine.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    category: str
    fields: tuple = ()
    unit: str = 'mm'
    choices: tuple = ()
    help: str = ''
    pair: bool = False

# One entry per constraint in the KiCad 10 custom-rule reference.
SPECS = [
 Spec('clearance','Copper clearance','Electrical',('min',),help='Different-net copper spacing. A local rule cannot lower the board manufacturing floor.',pair=True),
 Spec('physical_clearance','Physical clearance (including same net)','Electrical',('min',),help='Same-layer physical spacing, including same-net objects. More expensive than electrical clearance.',pair=True),
 Spec('creepage','Surface creepage','Electrical',('min',),help='Surface path between conductors. This is not an automatic safety-standard qualification.',pair=True),
 Spec('edge_clearance','Copper / object to board edge','Electrical',('min',)),
 Spec('hole_clearance','Different-net copper to hole','Electrical',('min',),pair=True),
 Spec('physical_hole_clearance','Physical hole clearance','Electrical',('min',),pair=True),
 Spec('courtyard_clearance','Courtyard-to-courtyard spacing','Placement',('min',),help='Spacing BETWEEN component courtyards; not copper clearance WITHIN a courtyard.',pair=True),
 Spec('connection_width','Pad-to-zone connection width','Zones & thermals',('min',)),
 Spec('annular_width','Annular ring width','Manufacturing',('min','max')),
 Spec('hole_size','Drill / hole size','Manufacturing',('min','opt','max')),
 Spec('hole_to_hole','Mechanical hole-to-hole spacing','Manufacturing',('min',),pair=True),
 Spec('via_diameter','Via copper diameter','Routing',('min','opt','max')),
 Spec('track_width','Track width','Routing',('min','opt','max')),
 Spec('track_angle','Connected track angle','Routing',('min','max'),'deg',help='Angle between connected segments, not absolute orientation.'),
 Spec('track_segment_length','Individual track / arc length','Routing',('min','max')),
 Spec('length','Path length / propagation delay','High speed',('min','opt','max'),'length_or_time',help='Length (mm/mil/in) or native propagation delay (ps). Do not mix domains. Verify stackup and host build.'),
 Spec('skew','Length mismatch / skew','High speed',('min','opt','max'),'length_or_time',help='Length mismatch or time skew in ps. Optional within_diff_pairs. Native timing requires verified stackup.'),
 Spec('diff_pair_gap','Differential-pair gap','High speed',('min','opt','max'),help='Parallel coupled sections; opt informs the router.',pair=True),
 Spec('diff_pair_uncoupled','Differential-pair uncoupled length','High speed',('max',)),
 Spec('via_count','Vias per net','High speed',('min','max'),'count'),
 Spec('via_dangling','Dangling-via check','Routing',help='No numeric arguments. Severity controls reporting; Ignore still participates in priority.'),
 Spec('text_height','Text height','Manufacturing',('min','max')),
 Spec('text_thickness','Text stroke thickness','Manufacturing',('min','max')),
 Spec('silk_clearance','Silkscreen clearance','Manufacturing',('min',),pair=True),
 Spec('bridged_mask','Solder-mask bridging check','Mask & paste',help='No numeric arguments; combine with severity and scope.',pair=True),
 Spec('solder_mask_expansion','Solder-mask expansion','Mask & paste',('opt',)),
 Spec('solder_paste_abs_margin','Absolute solder-paste margin','Mask & paste',('opt',),help='Negative values inset the aperture. Adds to relative margin.'),
 Spec('solder_paste_rel_margin','Relative solder-paste margin','Mask & paste',('opt',),'ratio',help='Enter the native KiCad rule value. No automatic percent conversion; verify the aperture result in KiCad.'),
 Spec('thermal_relief_gap','Thermal-relief gap','Zones & thermals',('min',)),
 Spec('thermal_spoke_width','Thermal-spoke width','Zones & thermals',('opt',)),
 Spec('min_resolved_spokes','Minimum resolved thermal spokes','Zones & thermals',(),'count',('0','1','2','3','4')),
 Spec('zone_connection','Pad-to-zone connection style','Zones & thermals',(),'',('solid','thermal_reliefs','none')),
 Spec('disallow','Disallow object types','Restrictions',(),'',('track','via','through_via','micro_via','blind_via','buried_via','pad','zone','text','graphic','hole','footprint')),
 Spec('assertion','Property / expression assertion','Restrictions',(),'',help='The expression must be true for matched objects. Use the visual condition builder to construct it.'),
]
CATALOG = {s.key:s for s in SPECS}
CATEGORIES = list(dict.fromkeys(s.category for s in SPECS))
SEVERITIES = ['error','warning','ignore','exclusion']
TYPES = ['Bitmap','Dimension','Footprint','Graphic','Group','Leader','Pad','Target','Text','Text Box','Track','Via','Zone']
# (function, argument count, object selector, explanation)
FUNCTIONS = [
 ('enclosedByArea',1,'A/B','The WHOLE item lies inside a named area. Conservative boundary scope.'),
 ('intersectsArea',1,'A/B','ANY part intersects a named rule area / filled copper region.'),
 ('intersectsCourtyard',1,'A/B','ANY part intersects either courtyard. Not strict containment.'),
 ('intersectsFrontCourtyard',1,'A/B','ANY part intersects the front courtyard.'),
 ('intersectsBackCourtyard',1,'A/B','ANY part intersects the back courtyard.'),
 ('existsOnLayer',1,'A/B','Item exists on this layer, including multilayer items.'),
 ('fromTo',2,'A/B','Path between endpoint patterns, such as U1-A1 and U2-B1. Host-version syntax check required.'),
 ('getField',1,'A/B','Footprint field value; compare the result with a string.'),
 ('hasComponentClass',1,'A/B','Footprint or parent belongs to the component class.'),
 ('hasNetclass',1,'A/B','Membership in a netclass, including composite classes.'),
 ('hasExactNetclass',1,'A/B','Exact set of netclasses.'),
 ('inDiffPair',1,'A/B','Differential-pair base name, allowing wildcard patterns.'),
 ('isCoupledDiffPair',0,'AB','The two items are opposite polarities of the same pair.'),
 ('isBlindVia',0,'A/B','Blind via.'),('isBuriedVia',0,'A/B','Buried via.'),
 ('isBlindBuriedVia',0,'A/B','Blind or buried via.'),('isMicroVia',0,'A/B','Microvia.'),
 ('isPlated',0,'A/B','Plated pad/via hole.'),
 ('memberOfGroup',1,'A/B','Named PCB group membership.'),
 ('memberOfFootprint',1,'A/B','Child of a footprint reference/library/class pattern.'),
 ('memberOfSheet',1,'A/B','Exact schematic-sheet pattern, excluding descendants.'),
 ('memberOfSheetOrChildren',1,'A/B','Sheet or descendants.'),
 # Preserved legacy aliases are offered with explicit deprecation notes.
 ('insideArea',1,'A/B','Deprecated intersection alias; not strict containment.'),
 ('insideCourtyard',1,'A/B','Deprecated intersection alias; not strict containment.'),
 ('insideFrontCourtyard',1,'A/B','Deprecated front-courtyard intersection alias.'),
 ('insideBackCourtyard',1,'A/B','Deprecated back-courtyard intersection alias.'),
 ('memberOf',1,'A/B','Deprecated group-membership alias.'),
]
FUNCTION_MAP = {x[0]:x for x in FUNCTIONS}
# Common documented properties plus an editable name control for version extensions.
PROPERTY_TYPES = {
 'Type':'string','Layer':'string','Locked':'boolean','Parent':'string',
 'Position_X':'dimension','Position_Y':'dimension','Net':'integer','NetName':'string','NetClass':'string',
 'Reference':'string','Value':'string','Component_Class':'string','Library_Link':'string',
 'Orientation':'angle','Clearance_Override':'dimension','Do_not_populate':'boolean',
 'Exclude_from_bom':'boolean','Exclude_from_pos_files':'boolean',
 'Pad_Number':'string','Pad_Type':'string','Pad_Shape':'string',
 'Hole_Size_X':'dimension','Hole_Size_Y':'dimension','Size_X':'dimension','Size_Y':'dimension',
 'Via_Type':'string','Diameter':'dimension','Width':'dimension','Length':'dimension',
 'Soldermask_Margin_Override':'dimension','Solderpaste_Margin_Override':'dimension',
 'Solderpaste_Margin_Ratio_Override':'number','Thermal_Relief_Gap':'dimension',
 'Thermal_Spoke_Width':'dimension','Zone_Connection':'string',
 'Name':'string','Text':'string','Thickness':'dimension','Height':'dimension',
 'Visible':'boolean','Italic':'boolean','Bold':'boolean','Mirrored':'boolean',
 'Horizontal_Justification':'string','Vertical_Justification':'string',
 'Curved_Edges':'boolean','Enable_Teardrops':'boolean','Prefer_Zone_Connections':'boolean',
 'Allow_Teardrops_To_Span_Two_Tracks':'boolean','Best_Length_Ratio':'number','Best_Width_Ratio':'number',
 'Max_Length':'dimension','Max_Width':'dimension','Max_Width_Ratio':'number',
}
LAYERS = ['Any','outer','inner','F.Cu'] + [f'In{i}.Cu' for i in range(1,31)] + [
 'B.Cu','F.Silkscreen','B.Silkscreen','F.Mask','B.Mask','F.Paste','B.Paste','F.Courtyard','B.Courtyard','Edge.Cuts']
# Exact spellings from the KiCad 10 reference; remove historical/inferred aliases.
for _key in ('Do_not_populate','Exclude_from_bom','Exclude_from_pos_files','Thermal_Spoke_Width','Zone_Connection','Length'):
    PROPERTY_TYPES.pop(_key,None)
PROPERTY_TYPES.update({
 'Do_not_Populate':'boolean','Exclude_From_Position_Files':'boolean',
 'Exclude_From_Bill_of_Materials':'boolean','Exempt_From_Courtyard_Requirement':'boolean',
 'Keywords':'string','Library_Description':'string','Not_in_Schematic':'boolean',
 'Thermal_Relief_Width':'dimension','Zone_Connection_Style':'string',
 'Fabrication_Property':'string','Pad_To_Die_Length':'dimension','Pin_Name':'string','Pin_Type':'string',
 'Corner_Radius_Ratio':'number','Thermal_Relief_Spoke_Angle':'angle','Thermal_Relief_Spoke_Width':'dimension',
 'Origin_X':'dimension','Origin_Y':'dimension','End_X':'dimension','End_Y':'dimension',
 'Hole':'dimension','Layer_Bottom':'string','Layer_Top':'string',
 'Min_Amplitude':'dimension','Max_Amplitude':'dimension','Tuning_Mode':'string','Initial_Side':'string',
 'Min_Spacing':'dimension','Corner_Radius_%':'integer','Target_Length':'dimension','Target_Skew':'dimension',
 'Override_Custom_Rules':'boolean','Single-sided':'boolean','Rounded':'boolean',
 'Hatch_Gap':'dimension','Hatch_Minimum_Hole_Ratio':'number','Hatch_Orientation':'integer',
 'Hatch_Width':'dimension','Min_Width':'dimension','Pad_Connections':'string','Priority':'integer',
 'Angle':'angle','Filled':'boolean','Line_Width':'dimension','Line_Style':'string','Shape':'string',
 'Start_X':'dimension','Start_Y':'dimension','Knockout':'boolean',
})
