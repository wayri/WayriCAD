# diagram_generator.py
"""
Self-contained SVG diagram generator for signal flow visualization.
No external dependencies required - generates pure SVG using Python strings.

@author - Wayri (Yawar)
@version - 2.0.0
"""

from typing import Dict, List, Any, Tuple, Optional
import html


class SVGDiagramGenerator:
    """
    Generates SVG block diagrams for signal flow visualization.
    Completely self-contained - no external libraries needed.
    """

    # Default styling
    DEFAULT_STYLES = {
        'background': '#1a1a2e',
        'component_fill': '#16213e',
        'component_stroke': '#0f3460',
        'connector_fill': '#1a5f7a',
        'connector_stroke': '#57c5b6',
        'ic_fill': '#2d4059',
        'ic_stroke': '#ea5455',
        'passive_fill': '#3d3d3d',
        'passive_stroke': '#888888',
        'signal_line': '#00d9ff',
        'power_line': '#ff6b6b',
        'ground_line': '#4ecdc4',
        'text_color': '#ffffff',
        'pin_text': '#aaaaaa',
        'net_text': '#ffdd57',
        'font_family': 'Consolas, Monaco, monospace',
        'title_font_size': 18,
        'label_font_size': 12,
        'pin_font_size': 10,
    }

    def __init__(self, styles: Dict[str, Any] = None):
        """
        Initialize the diagram generator.
        
        Args:
            styles: Optional custom styles dictionary
        """
        self.styles = {**self.DEFAULT_STYLES, **(styles or {})}

    def _escape(self, text: str) -> str:
        """Escape text for SVG/XML."""
        return html.escape(str(text))

    def _get_component_color(self, ref: str, comp_type: str = "") -> Tuple[str, str]:
        """Get fill and stroke colors based on component type."""
        ref_upper = ref.upper()
        
        if ref_upper.startswith('J') or 'connector' in comp_type.lower():
            return self.styles['connector_fill'], self.styles['connector_stroke']
        elif ref_upper.startswith('U') or ref_upper.startswith('IC'):
            return self.styles['ic_fill'], self.styles['ic_stroke']
        elif ref_upper.startswith(('R', 'C', 'L')):
            return self.styles['passive_fill'], self.styles['passive_stroke']
        else:
            return self.styles['component_fill'], self.styles['component_stroke']

    def _get_line_color(self, net_type: str) -> str:
        """Get line color based on net type."""
        if net_type == 'ground':
            return self.styles['ground_line']
        elif net_type in ('supply', 'power'):
            return self.styles['power_line']
        else:
            return self.styles['signal_line']

    def generate_ic_signal_chart(
        self,
        ic_ref: str,
        ic_value: str,
        connections: List[Dict[str, Any]],
        title: str = None,
        width: int = 1200,
        height: int = None
    ) -> str:
        """
        Generate an SVG signal chart for an IC showing all its pin connections.
        
        Args:
            ic_ref: IC reference designator
            ic_value: IC value/part number
            connections: List of connection dictionaries from SignalFlowAnalyzer
            title: Optional title for the diagram
            width: SVG width in pixels
            height: SVG height (auto-calculated if None)
        
        Returns:
            SVG string
        """
        if not connections:
            return self._generate_empty_diagram("No connections found")

        # Group by pin for layout
        pins_data = {}
        for conn in connections:
            pin = conn.get('IC Pin', '')
            if pin not in pins_data:
                pins_data[pin] = []
            pins_data[pin].append(conn)

        # Calculate dimensions
        pin_count = len(pins_data)
        row_height = 40
        ic_box_width = 200
        ic_box_height = max(200, pin_count * row_height + 60)
        dest_box_width = 180
        margin = 50
        
        if height is None:
            height = ic_box_height + 150

        # Start SVG
        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
            f'<rect width="100%" height="100%" fill="{self.styles["background"]}"/>',
            '<style>',
            f'.title {{ font-family: {self.styles["font_family"]}; font-size: {self.styles["title_font_size"]}px; fill: {self.styles["text_color"]}; font-weight: bold; }}',
            f'.label {{ font-family: {self.styles["font_family"]}; font-size: {self.styles["label_font_size"]}px; fill: {self.styles["text_color"]}; }}',
            f'.pin {{ font-family: {self.styles["font_family"]}; font-size: {self.styles["pin_font_size"]}px; fill: {self.styles["pin_text"]}; }}',
            f'.net {{ font-family: {self.styles["font_family"]}; font-size: {self.styles["pin_font_size"]}px; fill: {self.styles["net_text"]}; }}',
            '</style>',
        ]

        # Title
        title_text = title or f"Signal Chart: {ic_ref} ({ic_value})"
        svg_parts.append(f'<text x="{width // 2}" y="30" class="title" text-anchor="middle">{self._escape(title_text)}</text>')

        # Draw IC box (center-left)
        ic_x = margin + 100
        ic_y = 60
        fill, stroke = self._get_component_color(ic_ref)
        
        svg_parts.append(f'<rect x="{ic_x}" y="{ic_y}" width="{ic_box_width}" height="{ic_box_height}" fill="{fill}" stroke="{stroke}" stroke-width="2" rx="5"/>')
        svg_parts.append(f'<text x="{ic_x + ic_box_width // 2}" y="{ic_y + 25}" class="label" text-anchor="middle" font-weight="bold">{self._escape(ic_ref)}</text>')
        svg_parts.append(f'<text x="{ic_x + ic_box_width // 2}" y="{ic_y + 42}" class="pin" text-anchor="middle">{self._escape(ic_value)}</text>')

        # Draw pins and connections
        pin_y_start = ic_y + 60
        sorted_pins = sorted(pins_data.keys(), key=lambda p: (
            0 if any(c.get('Is Power Net') == 'No' for c in pins_data[p]) else 1,
            self._natural_sort_key(p)
        ))

        dest_groups = {}  # Group destinations to avoid overlap
        
        for i, pin in enumerate(sorted_pins):
            pin_conns = pins_data[pin]
            pin_y = pin_y_start + i * row_height
            
            # Pin label on IC
            svg_parts.append(f'<text x="{ic_x + ic_box_width - 10}" y="{pin_y + 5}" class="pin" text-anchor="end">{self._escape(pin)}</text>')
            
            # Pin connection point
            conn_x = ic_x + ic_box_width
            svg_parts.append(f'<circle cx="{conn_x}" cy="{pin_y}" r="4" fill="{stroke}"/>')
            
            # Draw connections to destinations
            for j, conn in enumerate(pin_conns):
                net_name = conn.get('Net Name', '')
                dest_ref = conn.get('Destination Reference', 'N/C')
                dest_pin = conn.get('Destination Pin', '')
                is_power = conn.get('Is Power Net', 'No') == 'Yes'
                
                # Determine net type for coloring
                net_type = 'power' if is_power else 'signal'
                if 'gnd' in net_name.lower() or 'vss' in net_name.lower():
                    net_type = 'ground'
                elif is_power:
                    net_type = 'supply'
                
                line_color = self._get_line_color(net_type)
                
                # Calculate destination position
                dest_x = width - margin - dest_box_width
                dest_key = dest_ref
                if dest_key not in dest_groups:
                    dest_groups[dest_key] = len(dest_groups)
                
                dest_y_offset = dest_groups[dest_key] * 50
                dest_y = ic_y + 20 + dest_y_offset
                
                # Draw connection line with curve
                mid_x = (conn_x + dest_x) // 2 + (j * 20)
                path = f'M {conn_x} {pin_y} C {mid_x} {pin_y}, {mid_x} {dest_y + 15}, {dest_x} {dest_y + 15}'
                svg_parts.append(f'<path d="{path}" fill="none" stroke="{line_color}" stroke-width="2" opacity="0.8"/>')
                
                # Net name label on the line
                label_x = (conn_x + dest_x) // 2
                label_y = (pin_y + dest_y + 15) // 2 - 5
                svg_parts.append(f'<text x="{label_x}" y="{label_y}" class="net" text-anchor="middle" font-size="9">{self._escape(net_name[:20])}</text>')

        # Draw destination boxes
        for dest_ref, idx in dest_groups.items():
            dest_y = ic_y + idx * 50
            dest_x = width - margin - dest_box_width
            
            # Find component info
            dest_value = ""
            dest_pins = []
            for conn in connections:
                if conn.get('Destination Reference') == dest_ref:
                    dest_value = conn.get('Destination Value', '')
                    dest_pins.append(conn.get('Destination Pin', ''))
            
            fill, stroke = self._get_component_color(dest_ref)
            box_height = max(40, len(set(dest_pins)) * 15 + 30)
            
            svg_parts.append(f'<rect x="{dest_x}" y="{dest_y}" width="{dest_box_width}" height="{box_height}" fill="{fill}" stroke="{stroke}" stroke-width="2" rx="5"/>')
            svg_parts.append(f'<text x="{dest_x + 10}" y="{dest_y + 18}" class="label" font-weight="bold">{self._escape(dest_ref)}</text>')
            svg_parts.append(f'<text x="{dest_x + 10}" y="{dest_y + 32}" class="pin">{self._escape(dest_value[:15])}</text>')
            
            # List pins
            for k, dp in enumerate(sorted(set(dest_pins))[:3]):
                svg_parts.append(f'<text x="{dest_x + dest_box_width - 10}" y="{dest_y + 18 + k * 12}" class="pin" text-anchor="end">Pin {self._escape(dp)}</text>')

        # Legend
        legend_y = height - 40
        svg_parts.append(f'<text x="{margin}" y="{legend_y}" class="pin">Legend:</text>')
        svg_parts.append(f'<line x1="{margin + 60}" y1="{legend_y - 5}" x2="{margin + 100}" y2="{legend_y - 5}" stroke="{self.styles["signal_line"]}" stroke-width="2"/>')
        svg_parts.append(f'<text x="{margin + 105}" y="{legend_y}" class="pin">Signal</text>')
        svg_parts.append(f'<line x1="{margin + 160}" y1="{legend_y - 5}" x2="{margin + 200}" y2="{legend_y - 5}" stroke="{self.styles["power_line"]}" stroke-width="2"/>')
        svg_parts.append(f'<text x="{margin + 205}" y="{legend_y}" class="pin">Power</text>')
        svg_parts.append(f'<line x1="{margin + 260}" y1="{legend_y - 5}" x2="{margin + 300}" y2="{legend_y - 5}" stroke="{self.styles["ground_line"]}" stroke-width="2"/>')
        svg_parts.append(f'<text x="{margin + 305}" y="{legend_y}" class="pin">Ground</text>')

        svg_parts.append('</svg>')
        return '\n'.join(svg_parts)

    def generate_signal_flow_diagram(
        self,
        flow_data: List[Dict[str, Any]],
        title: str = "Signal Flow Diagram",
        width: int = 1400,
        height: int = None
    ) -> str:
        """
        Generate an SVG block diagram showing signal flow between components.
        
        Args:
            flow_data: List of signal flow dictionaries from SignalFlowAnalyzer
            title: Diagram title
            width: SVG width in pixels
            height: SVG height (auto-calculated if None)
        
        Returns:
            SVG string
        """
        if not flow_data:
            return self._generate_empty_diagram("No signal flow data")

        # Collect unique sources and destinations
        sources = {}
        destinations = {}
        connections = []

        for entry in flow_data:
            src_ref = entry.get('Source Reference', '')
            src_val = entry.get('Source Value', '')
            dst_ref = entry.get('Destination Reference', '')
            dst_val = entry.get('Destination Value', '')
            net = entry.get('Net Name', '')
            src_pin = entry.get('Source Pin', '')
            dst_pin = entry.get('Destination Pin', '')

            if src_ref and src_ref not in sources:
                sources[src_ref] = {'value': src_val, 'pins': set(), 'type': entry.get('Source Type', '')}
            if src_ref:
                sources[src_ref]['pins'].add(src_pin)

            if dst_ref and dst_ref not in destinations:
                destinations[dst_ref] = {'value': dst_val, 'pins': set(), 'type': entry.get('Destination Type', '')}
            if dst_ref:
                destinations[dst_ref]['pins'].add(dst_pin)

            connections.append({
                'src': src_ref, 'src_pin': src_pin,
                'dst': dst_ref, 'dst_pin': dst_pin,
                'net': net
            })

        # Calculate layout
        src_count = len(sources)
        dst_count = len(destinations)
        box_height = 80
        box_width = 160
        margin = 60
        spacing = 20

        if height is None:
            height = max(src_count, dst_count) * (box_height + spacing) + 150

        # Start SVG
        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
            f'<rect width="100%" height="100%" fill="{self.styles["background"]}"/>',
            '<style>',
            f'.title {{ font-family: {self.styles["font_family"]}; font-size: {self.styles["title_font_size"]}px; fill: {self.styles["text_color"]}; font-weight: bold; }}',
            f'.label {{ font-family: {self.styles["font_family"]}; font-size: {self.styles["label_font_size"]}px; fill: {self.styles["text_color"]}; }}',
            f'.pin {{ font-family: {self.styles["font_family"]}; font-size: {self.styles["pin_font_size"]}px; fill: {self.styles["pin_text"]}; }}',
            f'.net {{ font-family: {self.styles["font_family"]}; font-size: 9px; fill: {self.styles["net_text"]}; }}',
            '</style>',
        ]

        # Title
        svg_parts.append(f'<text x="{width // 2}" y="35" class="title" text-anchor="middle">{self._escape(title)}</text>')

        # Column headers
        svg_parts.append(f'<text x="{margin + box_width // 2}" y="65" class="label" text-anchor="middle" font-weight="bold">Sources</text>')
        svg_parts.append(f'<text x="{width - margin - box_width // 2}" y="65" class="label" text-anchor="middle" font-weight="bold">Destinations</text>')

        # Draw source boxes
        src_positions = {}
        for i, (ref, data) in enumerate(sorted(sources.items())):
            x = margin
            y = 80 + i * (box_height + spacing)
            src_positions[ref] = (x + box_width, y + box_height // 2)
            
            fill, stroke = self._get_component_color(ref, data['type'])
            svg_parts.append(f'<rect x="{x}" y="{y}" width="{box_width}" height="{box_height}" fill="{fill}" stroke="{stroke}" stroke-width="2" rx="5"/>')
            svg_parts.append(f'<text x="{x + 10}" y="{y + 25}" class="label" font-weight="bold">{self._escape(ref)}</text>')
            svg_parts.append(f'<text x="{x + 10}" y="{y + 42}" class="pin">{self._escape(data["value"][:18])}</text>')
            
            # Show pin count
            pin_count = len(data['pins'])
            svg_parts.append(f'<text x="{x + 10}" y="{y + 58}" class="pin">{pin_count} pin(s) connected</text>')
            
            # Connection point
            svg_parts.append(f'<circle cx="{x + box_width}" cy="{y + box_height // 2}" r="5" fill="{stroke}"/>')

        # Draw destination boxes
        dst_positions = {}
        for i, (ref, data) in enumerate(sorted(destinations.items())):
            x = width - margin - box_width
            y = 80 + i * (box_height + spacing)
            dst_positions[ref] = (x, y + box_height // 2)
            
            fill, stroke = self._get_component_color(ref, data['type'])
            svg_parts.append(f'<rect x="{x}" y="{y}" width="{box_width}" height="{box_height}" fill="{fill}" stroke="{stroke}" stroke-width="2" rx="5"/>')
            svg_parts.append(f'<text x="{x + 10}" y="{y + 25}" class="label" font-weight="bold">{self._escape(ref)}</text>')
            svg_parts.append(f'<text x="{x + 10}" y="{y + 42}" class="pin">{self._escape(data["value"][:18])}</text>')
            
            # Show pin count
            pin_count = len(data['pins'])
            svg_parts.append(f'<text x="{x + 10}" y="{y + 58}" class="pin">{pin_count} pin(s) connected</text>')
            
            # Connection point
            svg_parts.append(f'<circle cx="{x}" cy="{y + box_height // 2}" r="5" fill="{stroke}"/>')

        # Draw connections
        drawn_connections = set()
        for conn in connections:
            src_ref = conn['src']
            dst_ref = conn['dst']
            conn_key = (src_ref, dst_ref)
            
            if conn_key in drawn_connections or src_ref not in src_positions or dst_ref not in dst_positions:
                continue
            drawn_connections.add(conn_key)
            
            src_x, src_y = src_positions[src_ref]
            dst_x, dst_y = dst_positions[dst_ref]
            
            # Determine line color based on net name
            net = conn['net']
            net_lower = net.lower()
            if 'gnd' in net_lower or 'vss' in net_lower:
                line_color = self.styles['ground_line']
            elif any(p in net_lower for p in ['vcc', 'vdd', '3v3', '5v', 'pwr']):
                line_color = self.styles['power_line']
            else:
                line_color = self.styles['signal_line']
            
            # Draw curved connection
            mid_x = (src_x + dst_x) // 2
            offset = (list(drawn_connections).index(conn_key) % 5 - 2) * 15
            
            path = f'M {src_x} {src_y} C {mid_x} {src_y + offset}, {mid_x} {dst_y + offset}, {dst_x} {dst_y}'
            svg_parts.append(f'<path d="{path}" fill="none" stroke="{line_color}" stroke-width="2" opacity="0.7"/>')
            
            # Arrow head
            svg_parts.append(f'<polygon points="{dst_x},{dst_y} {dst_x - 10},{dst_y - 5} {dst_x - 10},{dst_y + 5}" fill="{line_color}"/>')

        # Connection count summary
        svg_parts.append(f'<text x="{width // 2}" y="{height - 20}" class="pin" text-anchor="middle">{len(connections)} signal connection(s) between {len(sources)} source(s) and {len(destinations)} destination(s)</text>')

        svg_parts.append('</svg>')
        return '\n'.join(svg_parts)

    def generate_rich_signal_flow_diagram(
        self,
        flow_data: List[Dict[str, Any]],
        title: str = "Signal Flow",
        width: int = 1680,
        height: Optional[int] = None,
    ) -> str:
        """Render a readable source -> path -> destination diagram.

        Unlike the original two-column renderer, this keeps intermediate
        components visible and draws one labeled edge per unique path/net.
        """
        if not flow_data:
            return self._generate_empty_diagram("No signal flow data")
        rows = []
        sources: Dict[str, Dict[str, Any]] = {}
        intermediates: Dict[str, Dict[str, Any]] = {}
        destinations: Dict[str, Dict[str, Any]] = {}
        for entry in flow_data:
            src = str(entry.get("Source Reference", "")); dst = str(entry.get("Destination Reference", ""))
            if not src or not dst or dst == "N/C": continue
            path_text = str(entry.get("Intermediates", ""))
            path_refs = [part.split(":", 1)[0].strip() for part in path_text.split(";") if part.strip()]
            net = str(entry.get("Net Name", ""))
            row = {"src": src, "dst": dst, "path": path_refs, "net": net, "src_pin": entry.get("Source Pin", ""), "dst_pin": entry.get("Destination Pin", ""), "protocol": entry.get("Protocol", "")}
            rows.append(row)
            sources.setdefault(src, {"value": entry.get("Source Value", ""), "type": entry.get("Source Type", "")})
            destinations.setdefault(dst, {"value": entry.get("Destination Value", ""), "type": entry.get("Destination Type", "")})
            for ref in path_refs:
                intermediates.setdefault(ref, {"value": "", "type": "passive"})
        if not rows: return self._generate_empty_diagram("No complete signal paths")
        box_w, box_h, margin, gap = 230, 76, 55, 28
        src_count = max(len(sources), 1); mid_count = max(len(intermediates), 1); dst_count = max(len(destinations), 1)
        height = height or max(src_count, mid_count, dst_count) * (box_h + gap) + 150
        cols = {"src": margin, "mid": (width - box_w) // 2, "dst": width - margin - box_w}
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">', f'<rect width="100%" height="100%" fill="{self.styles["background"]}"/>', '<style>', f'.title{{font:700 {self.styles["title_font_size"]}px {self.styles["font_family"]};fill:{self.styles["text_color"]}}}', f'.label{{font:700 13px {self.styles["font_family"]};fill:{self.styles["text_color"]}}}', f'.small{{font:11px {self.styles["font_family"]};fill:{self.styles["pin_text"]}}}', f'.net{{font:10px {self.styles["font_family"]};fill:{self.styles["net_text"]}}}', '</style>']
        svg.append(f'<text x="{width // 2}" y="30" class="title" text-anchor="middle">{self._escape(title)}</text>')
        for key, label in (("src", "Sources"), ("mid", "Pass-through / Intermediates"), ("dst", "Destinations")):
            svg.append(f'<text x="{cols[key] + box_w // 2}" y="60" class="label" text-anchor="middle">{self._escape(label)}</text>')

        def draw_column(items: Dict[str, Dict[str, Any]], column: str) -> Dict[str, Any]:
            positions = {}
            for idx, (ref, data) in enumerate(sorted(items.items(), key=lambda item: self._natural_sort_key(item[0]))):
                y = 78 + idx * (box_h + gap); fill, stroke = self._get_component_color(ref, data.get("type", "")); x = cols[column]
                svg.append(f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
                svg.append(f'<text x="{x + 12}" y="{y + 25}" class="label">{self._escape(ref)}</text>')
                svg.append(f'<text x="{x + 12}" y="{y + 45}" class="small">{self._escape(str(data.get("value", ""))[:28])}</text>')
                if column == "mid":
                    positions[ref] = ((x, y + box_h // 2), (x + box_w, y + box_h // 2))
                else:
                    positions[ref] = ((x + box_w) if column != "dst" else x, y + box_h // 2)
            return positions

        src_pos = draw_column(sources, "src"); mid_pos = draw_column(intermediates, "mid"); dst_pos = draw_column(destinations, "dst")

        def port(ref: str, direction: str) -> Optional[Tuple[int, int]]:
            if ref in mid_pos:
                left, right = mid_pos[ref]
                return left if direction == "in" else right
            if ref in src_pos:
                return src_pos[ref] if direction == "out" else None
            if ref in dst_pos:
                return dst_pos[ref] if direction == "in" else None
            return None

        for row_idx, row in enumerate(rows):
            path = [row["src"]] + row["path"] + [row["dst"]]
            positions = {**src_pos, **mid_pos, **dst_pos}
            color = self._flow_color(row["net"], row.get("protocol", ""))
            for left, right in zip(path, path[1:]):
                start = port(left, "out")
                end = port(right, "in")
                if start is None or end is None: continue
                sx, sy = start; ex, ey = end
                direction = 1 if ex >= sx else -1
                midx = (sx + ex) / 2
                svg.append(f'<path d="M {sx} {sy} C {midx} {sy}, {midx} {ey}, {ex} {ey}" fill="none" stroke="{color}" stroke-width="2" opacity="0.85"/>')
                svg.append(f'<polygon points="{ex},{ey} {ex - 9 * direction},{ey - 5} {ex - 9 * direction},{ey + 5}" fill="{color}"/>')
            if row["src"] in src_pos and row["dst"] in dst_pos:
                sx, sy = src_pos[row["src"]]; ex, ey = dst_pos[row["dst"]]
                svg.append(f'<text x="{(sx + ex) // 2}" y="{min(sy, ey) - 6}" class="net" text-anchor="middle">{self._escape(row["net"][:34])}</text>')
        svg.append(f'<text x="{width // 2}" y="{height - 18}" class="small" text-anchor="middle">{len(rows)} paths | {len(sources)} sources | {len(intermediates)} intermediates | {len(destinations)} destinations</text></svg>')
        return '\n'.join(svg)

    def generate_interface_block_diagram(self, interfaces: Dict[str, Dict[str, Any]], title: str = "KiWay Interface Map", width: int = 1500) -> str:
        """Render board/interface maps as a left-to-right block diagram."""
        if not interfaces: return self._generate_empty_diagram("No interfaces found")
        box_w, box_h, gap, margin = 245, 78, 26, 55
        rows = list(sorted(interfaces.items()))
        height = max(170, len(rows) * (box_h + gap) + 100)
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">', f'<rect width="100%" height="100%" fill="{self.styles["background"]}"/>', f'<style>.title{{font:700 18px {self.styles["font_family"]};fill:{self.styles["text_color"]}}}.label{{font:700 13px {self.styles["font_family"]};fill:{self.styles["text_color"]}}}.small{{font:11px {self.styles["font_family"]};fill:{self.styles["pin_text"]}}}.net{{font:10px {self.styles["font_family"]};fill:{self.styles["net_text"]}}}</style>', f'<text x="{width // 2}" y="30" class="title" text-anchor="middle">{self._escape(title)}</text>']
        for idx, (name, iface) in enumerate(rows):
            y = 55 + idx * (box_h + gap); src = iface.get("source_board") or "Source / MCU"; dst = iface.get("destination_board") or "Peripheral"; x1 = margin; x2 = width - margin - box_w
            for x, text, color in ((x1, src, "#274b70"), (x2, dst, "#5c4b2a")):
                svg.append(f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="8" fill="{color}" stroke="#67c4c9" stroke-width="2"/>')
                svg.append(f'<text x="{x + 12}" y="{y + 28}" class="label">{self._escape(str(text)[:28])}</text>')
                svg.append(f'<text x="{x + 12}" y="{y + 51}" class="small">{self._escape(name)} | {len(iface.get("nets", []))} nets</text>')
            sx = x1 + box_w; ex = x2; sy = y + box_h // 2
            svg.append(f'<path d="M {sx} {sy} C {(sx + ex) // 2} {sy - 18}, {(sx + ex) // 2} {sy + 18}, {ex} {sy}" fill="none" stroke="#58d1df" stroke-width="3"/>')
            svg.append(f'<polygon points="{ex},{sy} {ex - 12},{sy - 6} {ex - 12},{sy + 6}" fill="#58d1df"/>')
            types = ", ".join(iface.get("tm_tc_types", [])) or ", ".join(iface.get("protocols", []))
            svg.append(f'<text x="{width // 2}" y="{sy - 7}" class="net" text-anchor="middle">{self._escape(types or "Signal interface")}</text>')
        svg.append('</svg>')
        return '\n'.join(svg)

    def _flow_color(self, net_name: str, protocol: str = "") -> str:
        if protocol in ("TM", "TA", "TD"): return "#70d6ff"
        if protocol in ("TC", "CA", "CD"): return "#ff9f68"
        lower = net_name.lower()
        if any(token in lower for token in ("gnd", "vss")): return self.styles['ground_line']
        if any(token in lower for token in ("vcc", "vdd", "pwr", "3v3", "5v")): return self.styles['power_line']
        return self.styles['signal_line']

    def generate_component_block(
        self,
        ref: str,
        value: str,
        pins: List[Dict[str, str]],
        width: int = 300,
        title: str = None
    ) -> str:
        """
        Generate an SVG block diagram for a single component with all its pins.
        
        Args:
            ref: Component reference designator
            value: Component value
            pins: List of pin dictionaries with 'Pad Name/Number', 'Net Name', 'Net Type'
            width: SVG width
            title: Optional title
        
        Returns:
            SVG string
        """
        pin_row_height = 24
        header_height = 60
        margin = 20
        height = header_height + len(pins) * pin_row_height + margin * 2

        fill, stroke = self._get_component_color(ref)

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
            f'<rect width="100%" height="100%" fill="{self.styles["background"]}"/>',
            '<style>',
            f'.label {{ font-family: {self.styles["font_family"]}; font-size: {self.styles["label_font_size"]}px; fill: {self.styles["text_color"]}; }}',
            f'.pin {{ font-family: {self.styles["font_family"]}; font-size: {self.styles["pin_font_size"]}px; fill: {self.styles["pin_text"]}; }}',
            f'.net {{ font-family: {self.styles["font_family"]}; font-size: {self.styles["pin_font_size"]}px; }}',
            '</style>',
        ]

        # Component box
        box_x = margin
        box_y = margin
        box_width = width - margin * 2
        box_height = height - margin * 2

        svg_parts.append(f'<rect x="{box_x}" y="{box_y}" width="{box_width}" height="{box_height}" fill="{fill}" stroke="{stroke}" stroke-width="2" rx="5"/>')
        
        # Header
        svg_parts.append(f'<text x="{width // 2}" y="{box_y + 25}" class="label" text-anchor="middle" font-weight="bold">{self._escape(ref)}</text>')
        svg_parts.append(f'<text x="{width // 2}" y="{box_y + 45}" class="pin" text-anchor="middle">{self._escape(value)}</text>')
        svg_parts.append(f'<line x1="{box_x + 10}" y1="{box_y + 55}" x2="{box_x + box_width - 10}" y2="{box_y + 55}" stroke="{stroke}" stroke-width="1"/>')

        # Pins
        for i, pin in enumerate(pins):
            y = box_y + header_height + i * pin_row_height + 15
            pad_name = pin.get('Pad Name/Number', '')
            net_name = pin.get('Net Name', '')
            net_type = pin.get('Net Type', 'signal')
            
            # Get color based on net type
            net_color = self._get_line_color(net_type)
            
            svg_parts.append(f'<text x="{box_x + 15}" y="{y}" class="pin">{self._escape(pad_name)}</text>')
            svg_parts.append(f'<text x="{box_x + box_width - 15}" y="{y}" class="net" text-anchor="end" fill="{net_color}">{self._escape(net_name[:25])}</text>')

        svg_parts.append('</svg>')
        return '\n'.join(svg_parts)

    def _generate_empty_diagram(self, message: str) -> str:
        """Generate an empty diagram with a message."""
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 100" width="400" height="100">
<rect width="100%" height="100%" fill="{self.styles['background']}"/>
<text x="200" y="55" font-family="{self.styles['font_family']}" font-size="14" fill="{self.styles['text_color']}" text-anchor="middle">{self._escape(message)}</text>
</svg>'''

    @staticmethod
    def _natural_sort_key(text: str) -> list:
        """Helper for natural sorting."""
        import re
        return [int(s) if s.isdigit() else s.lower() for s in re.split('([0-9]+)', str(text))]
