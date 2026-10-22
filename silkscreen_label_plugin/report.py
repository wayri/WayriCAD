"""Self-contained, offline HTML review reports for read-only previews."""
from html import escape
import math


def _mm_point(point, api):
    return [api.ToMM(point[0]), api.ToMM(point[1])]


def _poly_paths(polyset, api):
    result=[]
    for index in range(polyset.OutlineCount()):
        chains=[polyset.COutline(index)]
        chains.extend(polyset.CHole(index,hole) for hole in range(polyset.HoleCount(index)))
        for chain in chains:
            points=[_mm_point((chain.CPoint(i).x,chain.CPoint(i).y),api) for i in range(chain.PointCount())]
            if points:result.append(dict(points=points,closed=True))
    return result


def _box_path(box, api):
    left,top,right,bottom=(api.ToMM(value) for value in
        (box.GetLeft(),box.GetTop(),box.GetRight(),box.GetBottom()))
    return dict(points=[[left,top],[right,top],[right,bottom],[left,bottom]],closed=True)


def _gap(first,second,api):
    dx=max(first.GetLeft()-second.GetRight(),second.GetLeft()-first.GetRight(),0)
    dy=max(first.GetTop()-second.GetBottom(),second.GetTop()-first.GetBottom(),0)
    return api.ToMM(math.hypot(dx,dy))


def capture_geometry(board, preview, api):
    """Capture native two-dimensional review geometry without editing the board."""
    from .placement import _state, _texts, item_id, text_geometry

    edge_box=board.GetBoardEdgesBoundingBox()
    bounds=[api.ToMM(edge_box.GetLeft()),api.ToMM(edge_box.GetTop()),
            api.ToMM(edge_box.GetWidth()),api.ToMM(edge_box.GetHeight())]
    features=[]
    def add(kind,side,label,paths):
        if paths:features.append(dict(kind=kind,side=side,label=label,paths=paths))
    outline=api.SHAPE_POLY_SET()
    if board.GetBoardPolygonOutlines(outline,False):add('board','both','Board outline',_poly_paths(outline,api))

    footprints={item_id(fp):fp for fp in board.GetFootprints()}
    bodies={}
    for fp in footprints.values():
        ref=fp.GetReference();side='bottom' if fp.IsFlipped() else 'top'
        hull=fp.GetBoundingHull()
        if hull.OutlineCount():
            hull_box=hull.BBox();bodies[item_id(fp)]=hull_box
            add('body',side,f'{ref} footprint hull (body proxy)',_poly_paths(hull,api))
        else:
            hull_box=fp.GetBoundingBox(False);bodies[item_id(fp)]=hull_box
            add('body',side,f'{ref} footprint bounds (body proxy)',[_box_path(hull_box,api)])
        for pad in fp.Pads():
            for face,mask in (('top',api.F_Mask),('bottom',api.B_Mask)):
                if pad.IsOnLayer(mask) or pad.GetDrillSize().x or pad.GetDrillSize().y:
                    add('pad',face,f'{ref} pad bounds',[_box_path(pad.GetBoundingBox(),api)])
        for face,layer in (('top',api.F_CrtYd),('bottom',api.B_CrtYd)):
            court=fp.GetCourtyard(layer)
            paths=_poly_paths(court,api)
            if paths:
                add('courtyard',face,f'{ref} native courtyard outline',paths)
                continue
            for graphic in fp.GraphicalItems():
                if graphic.GetLayer()!=layer:continue
                if hasattr(graphic,'GetStart') and hasattr(graphic,'GetEnd'):
                    first,second=graphic.GetStart(),graphic.GetEnd()
                    add('courtyard',face,f'{ref} drawn courtyard segments',
                        [dict(points=[_mm_point((first.x,first.y),api),_mm_point((second.x,second.y),api)],closed=False)])
                else:add('courtyard',face,f'{ref} drawn courtyard bounds',[_box_path(graphic.GetBoundingBox(),api)])

    changed={item_id(change.item):change for change in preview.changes}
    outcome_by_id={row['id']:row for row in preview.outcomes}
    rows={}
    suppressed_after={key for change in preview.changes for key in change.suppressed_item_ids}
    suppressed_before={item_id(change.annotation.text) for change in preview.changes
                       if change.annotation and change.annotation.remove}
    # The board iterator contains only attached source objects. Annotation
    # changes also have prospective detached objects, so project those below.
    projected_ids=set()
    for text,fp,_kind in _texts(board,api):
        key=item_id(text);change=changed.get(key)
        layer=text.GetLayer()
        if layer not in (api.F_SilkS,api.B_SilkS):continue
        side='bottom' if layer==api.B_SilkS else 'top'
        outcome=outcome_by_id.get(key)
        if change and change.annotation:
            # Annotation restore changes are keyed by the original reference,
            # while their before view is the generated net label.
            action=change.annotation
            before_item=action.text if action.remove else (action.text if not action.create else action.reference)
            after_item=change.preview_item or change.item
            before_visible=bool(before_item.IsVisible())
            after_visible=bool(after_item.IsVisible())
            before_state=_state(before_item)
            after_state=change.after
            if before_visible:
                _clone,glyphs=text_geometry(before_item,before_state,api)
                add('glyph-before',side, before_item.GetShownText(False),_poly_paths(glyphs,api))
            if after_visible:
                _clone,glyphs=text_geometry(after_item,after_state,api)
                add('glyph-after',side, after_item.GetShownText(False),_poly_paths(glyphs,api))
            projected_ids.add(key)
        elif outcome is not None:
            before_state=change.before if change else _state(text)
            after_item=(change.preview_item or text) if change else text
            after_state=change.after if change else before_state
            if text.IsVisible():
                _clone,glyphs=text_geometry(text,before_state,api)
                add('glyph-before',side,text.GetShownText(False),_poly_paths(glyphs,api))
            if after_item.IsVisible():
                _clone,glyphs=text_geometry(after_item,after_state,api)
                add('glyph-after',side,after_item.GetShownText(False),_poly_paths(glyphs,api))
            projected_ids.add(key)
        else:
            if text.IsVisible():
                _clone,glyphs=text_geometry(text,_state(text),api)
                if key in suppressed_before:
                    add('glyph-before',side,text.GetShownText(False),_poly_paths(glyphs,api))
                elif key in suppressed_after:
                    add('context-before',side,'Preserved visible text',_poly_paths(glyphs,api))
                else:add('context-glyph',side,'Preserved visible text',_poly_paths(glyphs,api))
        if outcome is None:continue
        row=dict(outcome,side=side)
        rows[key]=row
    for change in preview.changes:
        if not change.annotation:continue
        key=item_id(change.item)
        if key in projected_ids:continue
        outcome=outcome_by_id.get(key)
        if outcome is None:continue
        action=change.annotation
        before_item=action.text if not action.create else action.reference
        after_item=change.preview_item or change.item
        side='bottom' if after_item.GetLayer()==api.B_SilkS else 'top'
        if before_item.IsVisible():
            _clone,glyphs=text_geometry(before_item,_state(before_item),api)
            add('glyph-before',side,before_item.GetShownText(False),_poly_paths(glyphs,api))
        if after_item.IsVisible():
            _clone,glyphs=text_geometry(after_item,change.after,api)
            add('glyph-after',side,after_item.GetShownText(False),_poly_paths(glyphs,api))
        rows[key]=dict(outcome,side=side)
    for change in preview.changes:
        side='bottom' if change.item.GetLayer()==api.B_SilkS else 'top'
        for _group,shapes in change.previous_guides:
            for shape in shapes:
                first,second=shape.GetStart(),shape.GetEnd()
                add('guide-before',side,change.label,[dict(points=[_mm_point((first.x,first.y),api),
                    _mm_point((second.x,second.y),api)],closed=False)])
        if change.leader_path:
            add('guide-after',side,change.label,[dict(points=[_mm_point(point,api) for point in change.leader_path],closed=False)])
        if change.sightline:
            add('sightline-after',side,change.label,[dict(points=[_mm_point(point,api) for point in change.sightline],closed=False)])
    return dict(board_mm=bounds,features=features,outcomes=[rows.get(row['id'],dict(row,side='unknown')) for row in preview.outcomes])


def _svg(geometry,side,state):
    x,y,width,height=geometry['board_mm']
    width=max(width,0.1);height=max(height,0.1)
    pieces=[f'<svg class="board" viewBox="{x:.4f} {y:.4f} {width:.4f} {height:.4f}" role="img" aria-label="{side} side {state} placement geometry">']
    if side=='bottom':pieces.append(f'<g transform="translate({2*x+width:.4f} 0) scale(-1 1)">')
    for feature in geometry['features']:
        if feature['side'] not in (side,'both'):continue
        kind=feature['kind']
        if kind.endswith(('-before','-after')) and not kind.endswith('-'+state):continue
        subpaths=[]
        for path in feature['paths']:
            points=path['points']
            if not points:continue
            subpaths.append('M '+' L '.join(f'{p[0]:.4f} {p[1]:.4f}' for p in points)+(' Z' if path['closed'] else ''))
        # Outer and hole rings must share one compound path. Filling each ring
        # separately would close counters in letters such as R, P, B and O.
        if subpaths:pieces.append(f'<path class="{escape(kind,quote=True)}" fill-rule="evenodd" d="{" ".join(subpaths)}"/>')
    if side=='bottom':pieces.append('</g>')
    pieces.append('</svg>')
    return ''.join(pieces)


def render_report(payload):
    """Render a self-contained, escaped, sortable HTML review report."""
    geometry=payload.get('review_geometry')
    if not isinstance(geometry,dict):raise ValueError('Preview does not contain native review geometry.')
    table_rows=[]
    for row in geometry.get('outcomes',[]):
        values=(row.get('side'),row.get('label'),row.get('status'),row.get('candidate_checks'),
                row.get('before_courtyard_gap_mm'),row.get('courtyard_gap_mm'),
                row.get('before_body_hull_gap_mm'),row.get('body_hull_gap_mm'),
                row.get('body_distance_source'),row.get('before_pad_gap_mm'),row.get('after_pad_gap_mm'),
                ' '.join(filter(None,(
                    'Before: '+row['before_association_warning'] if row.get('before_association_warning') else '',
                    'After: '+row['association_warning'] if row.get('association_warning') else row.get('reason','')))))
        cells=[]
        for value in values:
            rendered='—' if value is None else f'{value:.3f}' if isinstance(value,float) else str(value)
            cells.append('<td>'+escape(rendered)+'</td>')
        table_rows.append('<tr>'+''.join(cells)+'</tr>')
    stats=payload.get('stats',{});warnings=[]
    for row in geometry.get('outcomes',[]):
        if row.get('status')=='UNRESOLVED':warnings.append(f"{row.get('label','')} remains unresolved.")
        warning=row.get('association_warning')
        if warning:warnings.append(str(warning))
    for label,reason in payload.get('rejected',[]):warnings.append(f'{label}: {reason}')
    for label,reason in payload.get('skipped',[]):warnings.append(f'{label}: {reason}')
    warning_html=''.join('<li>'+escape(str(warning))+'</li>' for warning in warnings) or '<li>No unresolved or exception warnings were returned by the planner.</li>'
    outcomes=geometry.get('outcomes',[])
    top_count=sum(row.get('side')=='top' for row in outcomes);bottom_count=sum(row.get('side')=='bottom' for row in outcomes)
    coverage=f"{stats.get('placed','?')} placed / {stats.get('eligible','?')} eligible; {stats.get('changed','?')} changed; {stats.get('unresolved','?')} unresolved; {stats.get('reviewed','?')} reviewed (top {top_count}, bottom {bottom_count})."
    if 'guides' in stats:coverage+=f" {stats['guides']} printed guides."
    if stats.get('guide_budget_limited'):coverage+=f" {stats['guide_budget_limited']} unresolved labels encountered the guide-count allowance."
    if stats.get('guide_length_limited'):coverage+=f" {stats['guide_length_limited']} unresolved labels encountered the guide-length limit."
    title='WayriCAD Silkscreen Placement Review'
    sections=[]
    for side in ('top','bottom'):
        caption='Before/after native rendered glyphs and board geometry. Courtyard gaps measure native glyph polygons against native courtyard geometry; missing courtyard geometry is unknown. Footprint hull distance is shown separately as a two-dimensional body proxy and may include pads. Physical 3D body clearance is not computed.'
        sections.append(f'<section><h3>{side.title()} side</h3><div class="views"><figure><figcaption>Before — {escape(caption)}</figcaption>{_svg(geometry,side,"before")}</figure><figure><figcaption>After — proposed only; {escape(caption)}</figcaption>{_svg(geometry,side,"after")}</figure></div></section>')
    rows=''.join(table_rows)
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>
body{{font:15px system-ui,sans-serif;max-width:1500px;margin:24px auto;padding:0 18px;color:#19313b}}h1,h2,h3{{color:#113b46}}.notice{{padding:12px;background:#fff7df;border-left:4px solid #c98b00}}.views{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}figure{{margin:0;border:1px solid #b9c7cb;padding:8px}}figcaption{{min-height:3em;font-size:13px}}svg.board{{width:100%;height:360px;background:#f7fafb;border:1px solid #d6e0e3}}path{{fill:none;stroke-width:.08;vector-effect:non-scaling-stroke}}.board{{stroke:#233b45}}.body{{stroke:#83949a;stroke-dasharray:.4 .3}}.courtyard{{stroke:#478d71;stroke-dasharray:.25 .15}}.pad{{stroke:#b78632;fill:#efd9a3;fill-opacity:.3}}.glyph-before,.glyph-after{{stroke:#006e67;fill:#008a7d;fill-opacity:.35}}.context-glyph{{stroke:#8d999d;fill:#8d999d;fill-opacity:.2}}.guide-before{{stroke:#82969d;stroke-width:.1}}.guide-after{{stroke:#008a7d;stroke-width:.12}}.sightline-after{{stroke:#5d7c98;stroke-dasharray:.2 .15}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}th,td{{border:1px solid #c8d2d5;padding:6px;text-align:left}}th{{background:#e9f0f2;cursor:pointer}}tr:nth-child(even){{background:#f7fafb}}@media(max-width:850px){{.views{{grid-template-columns:1fr}}}}
</style><body><h1>{title}</h1><p class="notice">Read-only preview. Proposed labels are not applied and native KiCad DRC was <strong>NOT RUN</strong>. Review the board in KiCad and run DRC before saving.</p><p><strong>Coverage:</strong> {escape(coverage)}</p><p><strong>Source SHA-256:</strong> <code>{escape(str(payload.get('source_sha256','unavailable')))}</code></p><p>Views show the full board outline; label/table rows cover both board faces. Pad marks are native pad bounding boxes. Courtyard gaps use native rendered glyph polygons against native courtyard geometry; missing courtyard distance is unknown. Native 2D footprint-hull proxy distance is listed separately from courtyard and envelope gaps. Hulls may include pads and do not establish physical package-body measurements.</p>{''.join(sections)}<h2>Outcomes and distances</h2><table id="outcomes"><thead><tr>{''.join('<th>'+name+'</th>' for name in ('Side','Reference / label','Outcome','Candidate checks','Before courtyard gap (mm)','After courtyard gap (mm)','Before footprint-hull gap (mm)','After footprint-hull gap (mm)','Footprint-hull metric source','Before pad gap (mm)','After pad gap (mm)','Warnings'))}</tr></thead><tbody>{rows}</tbody></table><h2>Ambiguities and exceptions</h2><ul>{warning_html}</ul><p><strong>DRC:</strong> NOT RUN. The placement envelope checks do not establish native design-rule acceptance or physical 3D body clearance.</p><script>document.querySelectorAll('#outcomes th').forEach((th,i)=>th.addEventListener('click',()=>{{const body=th.closest('table').tBodies[0],rows=[...body.rows];rows.sort((a,b)=>a.cells[i].textContent.localeCompare(b.cells[i].textContent,undefined,{{numeric:true}}));rows.forEach(row=>body.appendChild(row))}}))</script></body></html>'''
