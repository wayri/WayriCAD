# formatters.py
"""
Output formatters for KiWay Extract Pins Plugin.
Provides clean, well-structured output in multiple formats.

@author - Wayri (Yawar)
@version - 2.0.0
"""

import csv
import json
from io import StringIO
from typing import Dict, List, Any, Optional
from abc import ABC, abstractmethod


class BaseFormatter(ABC):
    """Abstract base class for output formatters."""
    
    @abstractmethod
    def format_component_data(
        self,
        data: Dict[str, Dict[str, Any]],
        include_properties: List[str] = None,
        include_pins: bool = True
    ) -> str:
        """Format extracted component data."""
        pass

    @abstractmethod
    def format_signal_flow(
        self,
        data: List[Dict[str, Any]]
    ) -> str:
        """Format signal flow data."""
        pass

    @abstractmethod
    def format_unique_nets(
        self,
        nets: List[str]
    ) -> str:
        """Format unique nets list."""
        pass


class MarkdownFormatter(BaseFormatter):
    """Formats data as clean Markdown tables."""
    
    def __init__(self, highlight_nets: bool = False):
        """
        Initialize Markdown formatter.
        
        Args:
            highlight_nets: Apply color highlighting to net names
        """
        self.highlight_nets = highlight_nets
        self.color_palette = [
            "#FF0000", "#008000", "#0000FF", "#FFA500", "#800080",
            "#00FFFF", "#FFC0CB", "#00FF7F", "#8B4513", "#A52A2A",
            "#6A5ACD", "#D2691E", "#4682B4", "#BDB76B", "#FFD700"
        ]
        self.net_colors = {}
        self.color_index = 0

    def _get_net_color(self, net_name: str) -> str:
        """Get or assign a color for a net name."""
        if net_name not in self.net_colors:
            self.net_colors[net_name] = self.color_palette[
                self.color_index % len(self.color_palette)
            ]
            self.color_index += 1
        return self.net_colors[net_name]

    def _format_net_name(self, net_name: str) -> str:
        """Format net name with optional highlighting."""
        if self.highlight_nets and net_name and net_name != "N/A":
            color = self._get_net_color(net_name)
            return f'<span style="color: {color};">{net_name}</span>'
        return net_name

    def format_component_data(
        self,
        data: Dict[str, Dict[str, Any]],
        include_properties: List[str] = None,
        include_pins: bool = True
    ) -> str:
        """Format component data as Markdown."""
        if include_properties is None:
            include_properties = [
                "Reference", "Value", "Footprint Name", "Description",
                "Layer", "Position", "Rotation", "Connector Type"
            ]
        
        lines = ["# Extracted Component Data", ""]
        
        for ref, comp_data in data.items():
            props = comp_data.get("general_properties", {})
            pins = comp_data.get("pins", [])
            
            lines.append(f"## {ref}")
            lines.append("")
            
            # Properties table
            prop_headers = [p for p in include_properties if p in props]
            if prop_headers:
                lines.append("### Properties")
                lines.append("")
                lines.append("| " + " | ".join(prop_headers) + " |")
                lines.append("|" + "|".join(["---"] * len(prop_headers)) + "|")
                
                row = [str(props.get(h, "N/A")) for h in prop_headers]
                lines.append("| " + " | ".join(row) + " |")
                lines.append("")
            
            # Pins table
            if include_pins and pins:
                lines.append("### Pin Details")
                lines.append("")
                lines.append("| Pin | Net Name |")
                lines.append("|-----|----------|")
                
                for pin in pins:
                    pad = pin.get("Pad Name/Number", "")
                    net = self._format_net_name(pin.get("Net Name", ""))
                    lines.append(f"| {pad} | {net} |")
                lines.append("")
        
        return "\n".join(lines)

    def format_signal_flow(
        self,
        data: List[Dict[str, Any]]
    ) -> str:
        """Format signal flow data as Markdown table."""
        if not data:
            return "# Signal Flow\n\nNo signal connections found."
        
        lines = ["# Signal Flow Table", ""]
        
        # Determine headers from first entry
        headers = list(data[0].keys())
        
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        
        for entry in data:
            row = []
            for h in headers:
                val = str(entry.get(h, ""))
                if "Net" in h:
                    val = self._format_net_name(val)
                row.append(val)
            lines.append("| " + " | ".join(row) + " |")
        
        lines.append("")
        return "\n".join(lines)

    def format_unique_nets(
        self,
        nets: List[str]
    ) -> str:
        """Format unique nets as Markdown list."""
        lines = ["# Unique Net Names", "", f"Total: {len(nets)} nets", ""]
        
        for net in nets:
            lines.append(f"- {self._format_net_name(net)}")
        
        lines.append("")
        return "\n".join(lines)


class CSVFormatter(BaseFormatter):
    """Formats data as clean CSV."""
    
    def format_component_data(
        self,
        data: Dict[str, Dict[str, Any]],
        include_properties: List[str] = None,
        include_pins: bool = True
    ) -> str:
        """Format component data as CSV with one row per pin."""
        if include_properties is None:
            include_properties = [
                "Reference", "Value", "Description", "Layer",
                "Position", "Rotation", "Connector Type", "Sheet", "Sheet Path"
            ]
        
        # Build rows list first, then join with newlines
        rows = []
        
        # Build header row
        headers = include_properties.copy()
        if include_pins:
            headers.extend(["Pin", "Net Name"])
        
        rows.append(",".join(f'"{h}"' for h in headers))
        
        for ref, comp_data in data.items():
            props = comp_data.get("general_properties", {})
            pins = comp_data.get("pins", [])
            
            # Build base row with properties
            base_values = []
            for h in include_properties:
                val = str(props.get(h, "")).replace('"', '""')  # Escape quotes
                base_values.append(f'"{val}"')
            
            if include_pins and pins:
                # One row per pin - only include pins that have data
                for pin in pins:
                    pad_name = pin.get("Pad Name/Number", "")
                    net_name = pin.get("Net Name", "")
                    
                    # Skip completely empty pins
                    if not pad_name and not net_name:
                        continue
                    
                    row_values = base_values.copy()
                    row_values.append(f'"{pad_name}"')
                    row_values.append(f'"{net_name}"')
                    rows.append(",".join(row_values))
            else:
                # Single row for component without pins
                if include_pins:
                    base_values.extend(['""', '""'])
                rows.append(",".join(base_values))
        
        return "\n".join(rows)

    def format_signal_flow(
        self,
        data: List[Dict[str, Any]]
    ) -> str:
        """Format signal flow data as CSV."""
        if not data:
            return ""
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Headers from first entry
        headers = list(data[0].keys())
        writer.writerow(headers)
        
        for entry in data:
            row = [str(entry.get(h, "")) for h in headers]
            writer.writerow(row)
        
        return output.getvalue().strip()

    def format_unique_nets(
        self,
        nets: List[str]
    ) -> str:
        """Format unique nets as single-column CSV."""
        output = StringIO()
        writer = csv.writer(output)
        
        writer.writerow(["Net Name"])
        for net in nets:
            writer.writerow([net])
        
        return output.getvalue().strip()


class JSONFormatter(BaseFormatter):
    """Formats data as clean JSON."""
    
    def __init__(self, indent: int = 2):
        """
        Initialize JSON formatter.
        
        Args:
            indent: Number of spaces for indentation (0 for compact)
        """
        self.indent = indent if indent > 0 else None

    def format_component_data(
        self,
        data: Dict[str, Dict[str, Any]],
        include_properties: List[str] = None,
        include_pins: bool = True
    ) -> str:
        """Format component data as JSON."""
        output = {"components": []}
        
        for ref, comp_data in data.items():
            props = comp_data.get("general_properties", {})
            pins = comp_data.get("pins", [])
            
            component = {
                "reference": ref,
                "properties": props
            }
            
            if include_pins:
                component["pins"] = pins
            
            output["components"].append(component)
        
        return json.dumps(output, indent=self.indent)

    def format_signal_flow(
        self,
        data: List[Dict[str, Any]]
    ) -> str:
        """Format signal flow data as JSON."""
        output = {"signal_flow": data}
        return json.dumps(output, indent=self.indent)

    def format_unique_nets(
        self,
        nets: List[str]
    ) -> str:
        """Format unique nets as JSON array."""
        output = {"unique_nets": nets, "count": len(nets)}
        return json.dumps(output, indent=self.indent)


def get_formatter(format_type: str, **kwargs) -> BaseFormatter:
    """
    Factory function to get the appropriate formatter.
    
    Args:
        format_type: One of 'markdown', 'md', 'csv', 'json'
        **kwargs: Additional arguments for the formatter
    
    Returns:
        Appropriate formatter instance
    """
    format_type = format_type.lower()
    
    if format_type in ('markdown', 'md'):
        return MarkdownFormatter(**kwargs)
    elif format_type == 'csv':
        return CSVFormatter()
    elif format_type == 'json':
        return JSONFormatter(**kwargs)
    else:
        raise ValueError(f"Unknown format type: {format_type}")
