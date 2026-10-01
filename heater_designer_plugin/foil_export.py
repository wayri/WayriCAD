"""Positive conductor artwork in physical millimetres, without a board write."""
from dataclasses import asdict
import json
from xml.etree import ElementTree as ET


def export_svg(result):
    """Export round-ended conductor strips; no kerf/tool compensation implied."""
    spec=result.spec
    root=ET.Element('svg',xmlns='http://www.w3.org/2000/svg',
                    width=f'{spec.width_mm:g}mm',height=f'{spec.height_mm:g}mm',
                    viewBox=f'0 0 {spec.width_mm:g} {spec.height_mm:g}')
    ET.SubElement(root,'title').text='WayriCAD heater conductor artwork'
    ET.SubElement(root,'metadata').text=json.dumps({
        'spec':asdict(spec),'resistance_ohm':result.resistance_ohm,
        'convention':'Positive conductor; round strip joins; units mm; not a compensated cutting toolpath',
        'terminals_mm':[(result.segments[0].x1_mm,result.segments[0].y1_mm),
                        (result.segments[-1].x2_mm,result.segments[-1].y2_mm)]})
    for layer in sorted({s.layer for s in result.segments}):
        group=ET.SubElement(root,'g',id=f'conductor-layer-{layer}',fill='none',
                            stroke='black',transform=f'translate(0 {spec.height_mm:g}) scale(1 -1)',
                            attrib={'stroke-linecap':'round','stroke-linejoin':'round'})
        for segment in result.segments:
            ET.SubElement(group,'path',d=f'M {segment.x1_mm:.9g} {segment.y1_mm:.9g} L {segment.x2_mm:.9g} {segment.y2_mm:.9g}',
                          attrib={'stroke-width':f'{segment.width_mm:.9g}'})
    return ET.tostring(root,encoding='unicode',xml_declaration=True)
