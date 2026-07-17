# signal_flow.py
"""
Signal Flow Analysis module for KiWay Extract Pins Plugin.
Provides functionality for tracing signals between components.

@author - Wayri (Yawar)
@version - 2.0.0
"""

from typing import Dict, List, Any, Optional, Tuple, Set
from .data_extractor import DataExtractor


class SignalFlowAnalyzer:
    """
    Analyzes signal flow between components on a KiCAD PCB.
    Supports:
    - Source to destination signal tracing
    - IC signal chart generation (all connections from an IC)
    """

    def __init__(self, data_extractor: DataExtractor):
        """
        Initialize the signal flow analyzer.
        
        Args:
            data_extractor: A DataExtractor instance for accessing board data
        """
        self.extractor = data_extractor
        self._net_map = None

    @property
    def net_to_pads_map(self) -> Dict[str, List[Tuple[Any, Any]]]:
        """Cached net to pads mapping."""
        if self._net_map is None:
            self._net_map = self.extractor.get_net_to_pads_map()
        return self._net_map

    def get_connected_components(
        self,
        footprint,
        pad
    ) -> List[Dict[str, Any]]:
        """
        Get all components connected to a specific pad via its net.
        
        Args:
            footprint: The source footprint
            pad: The source pad
        
        Returns:
            List of dictionaries with destination component info
        """
        net = pad.GetNet()
        if not net:
            return []
        
        net_name = net.GetNetname()
        if net_name.lower() in ["", "unconnected"]:
            return []

        source_ref = footprint.GetReference()
        source_pad_name = pad.GetPadName()
        
        connected = []
        pads_on_net = self.net_to_pads_map.get(net_name, [])
        
        for dest_fp, dest_pad in pads_on_net:
            dest_ref = dest_fp.GetReference()
            dest_pad_name = dest_pad.GetPadName()
            
            # Skip self-connections (same component, same pad)
            if dest_ref == source_ref and dest_pad_name == source_pad_name:
                continue
            
            connected.append({
                "Reference": dest_ref,
                "Value": dest_fp.GetValue(),
                "Pad": dest_pad_name,
                "Footprint": str(dest_fp.GetFPID()),
                "Layer": dest_fp.GetLayerName(),
                "Connector Type": self.extractor.get_footprint_property(dest_fp, "connector-type") or ""
            })
        
        return connected

    def generate_source_destination_table(
        self,
        source_refs: List[str],
        destination_refs: List[str],
        include_intermediates: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Generate a signal flow table between source and destination components.
        
        Args:
            source_refs: List of source component reference designators
            destination_refs: List of destination component reference designators
            include_intermediates: If True, include intermediate components in the path
        
        Returns:
            List of signal flow entries with source/destination pin and net info
        """
        dest_refs_set = set(destination_refs)
        result = []
        
        for source_ref in source_refs:
            source_fp = self.extractor.get_footprint_by_reference(source_ref)
            if not source_fp:
                continue
            
            source_value = source_fp.GetValue()
            source_type = self.extractor.get_footprint_property(source_fp, "connector-type") or ""
            
            for pad in source_fp.Pads():
                net = pad.GetNet()
                if not net:
                    continue
                
                net_name = net.GetNetname()
                if net_name.lower() in ["", "unconnected"]:
                    continue
                
                source_pad_name = pad.GetPadName()
                
                # Find all destinations on this net
                pads_on_net = self.net_to_pads_map.get(net_name, [])
                
                for dest_fp, dest_pad in pads_on_net:
                    dest_ref = dest_fp.GetReference()
                    
                    # Skip if not in destination list or is the source itself
                    if dest_ref not in dest_refs_set or dest_ref == source_ref:
                        continue
                    
                    dest_value = dest_fp.GetValue()
                    dest_pad_name = dest_pad.GetPadName()
                    dest_type = self.extractor.get_footprint_property(dest_fp, "connector-type") or ""
                    
                    entry = {
                        "Source Reference": source_ref,
                        "Source Value": source_value,
                        "Source Pin": source_pad_name,
                        "Source Type": source_type,
                        "Net Name": net_name,
                        "Destination Reference": dest_ref,
                        "Destination Value": dest_value,
                        "Destination Pin": dest_pad_name,
                        "Destination Type": dest_type
                    }
                    
                    if include_intermediates:
                        # Find intermediate components on this net
                        intermediates = []
                        for inter_fp, inter_pad in pads_on_net:
                            inter_ref = inter_fp.GetReference()
                            if inter_ref != source_ref and inter_ref not in dest_refs_set:
                                intermediates.append(f"{inter_ref}:{inter_pad.GetPadName()}")
                        entry["Intermediates"] = "; ".join(intermediates) if intermediates else ""
                    
                    result.append(entry)
        
        # Sort by source reference, then source pin
        result.sort(key=lambda x: (
            DataExtractor.natural_sort_key(x["Source Reference"]),
            DataExtractor.natural_sort_key(x["Source Pin"])
        ))
        
        return result

    def generate_rich_source_destination_table(
        self,
        source_refs: List[str],
        destination_refs: List[str],
        include_intermediates: bool = True,
        include_power: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return chart-ready rows with path, protocol, and net classification."""
        rows = self.generate_source_destination_table(source_refs, destination_refs, include_intermediates=True)
        enriched = []
        for row in rows:
            net_name = row.get("Net Name", "")
            net_type = self.extractor.classify_net(net_name) if net_name else "unconnected"
            if not include_power and net_type != "signal":
                continue
            protocol = self._protocol(net_name)
            intermediates = row.get("Intermediates", "") if include_intermediates else ""
            path = [row.get("Source Reference", "")]
            path.extend(part.split(":", 1)[0].strip() for part in intermediates.split(";") if part.strip())
            path.append(row.get("Destination Reference", ""))
            row.update({
                "Net Type": net_type,
                "Power Net": "Yes" if net_type != "signal" else "No",
                "Protocol": protocol,
                "Path": " -> ".join(item for item in path if item),
                "Hop Count": max(0, len(path) - 1),
            })
            enriched.append(row)
        return enriched

    @staticmethod
    def _protocol(net_name: str) -> str:
        tokens = {part.upper() for part in str(net_name).split("_") if part}
        for protocol in ("SPI", "I2C", "I3C", "UART", "CAN", "LIN", "USB", "JTAG", "SWD", "QSPI", "SDIO", "MDIO", "RMII", "MIPI", "LVDS", "TM", "TC", "TA", "TD", "CA", "CD"):
            if protocol in tokens or str(net_name).upper().startswith(protocol):
                return protocol
        return ""

    def generate_ic_signal_chart(
        self,
        ic_ref: str,
        include_power_nets: bool = False,
        power_net_patterns: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate a complete signal chart for an IC showing all its connections.
        
        Args:
            ic_ref: Reference designator of the IC
            include_power_nets: Include power/ground nets in output
            power_net_patterns: List of patterns to identify power nets (default: VCC*, VDD*, GND*, VSS*)
        
        Returns:
            List of signal entries with IC pin info and all destinations
        """
        if power_net_patterns is None:
            power_net_patterns = ["VCC*", "VDD*", "GND*", "VSS*", "+*V*", "-*V*", "VBAT*"]
        
        power_regexes = [DataExtractor.convert_wildcard_to_regex(p.upper()) 
                        for p in power_net_patterns]
        
        ic_fp = self.extractor.get_footprint_by_reference(ic_ref)
        if not ic_fp:
            return []
        
        ic_value = ic_fp.GetValue()
        result = []
        
        for pad in ic_fp.Pads():
            net = pad.GetNet()
            if not net:
                continue
            
            net_name = net.GetNetname()
            if net_name.lower() in ["", "unconnected"]:
                continue
            
            # Check if this is a power net
            is_power_net = any(
                __import__('re').fullmatch(regex, net_name.upper()) 
                for regex in power_regexes
            )
            
            if not include_power_nets and is_power_net:
                continue
            
            pad_name = pad.GetPadName()
            
            # Get all destinations for this pin
            destinations = self.get_connected_components(ic_fp, pad)
            
            if destinations:
                # Create an entry for each destination
                for dest in destinations:
                    result.append({
                        "IC Reference": ic_ref,
                        "IC Value": ic_value,
                        "IC Pin": pad_name,
                        "Net Name": net_name,
                        "Is Power Net": "Yes" if is_power_net else "No",
                        "Destination Reference": dest["Reference"],
                        "Destination Value": dest["Value"],
                        "Destination Pin": dest["Pad"],
                        "Destination Type": dest["Connector Type"]
                    })
            else:
                # No destinations (net connected only to this IC)
                result.append({
                    "IC Reference": ic_ref,
                    "IC Value": ic_value,
                    "IC Pin": pad_name,
                    "Net Name": net_name,
                    "Is Power Net": "Yes" if is_power_net else "No",
                    "Destination Reference": "N/C",
                    "Destination Value": "",
                    "Destination Pin": "",
                    "Destination Type": ""
                })
        
        # Sort by IC pin number (natural sort)
        result.sort(key=lambda x: DataExtractor.natural_sort_key(x["IC Pin"]))
        
        return result

    def find_signal_path(
        self,
        start_ref: str,
        end_ref: str,
        max_hops: int = 10
    ) -> List[List[Dict[str, Any]]]:
        """
        Find all signal paths between two components (BFS-based).
        
        Args:
            start_ref: Starting component reference
            end_ref: Ending component reference
            max_hops: Maximum number of component hops to search
        
        Returns:
            List of paths, where each path is a list of connection dictionaries
        """
        start_fp = self.extractor.get_footprint_by_reference(start_ref)
        end_fp = self.extractor.get_footprint_by_reference(end_ref)
        
        if not start_fp or not end_fp:
            return []
        
        # BFS to find paths
        paths = []
        queue = [(start_ref, [])]  # (current_ref, path_so_far)
        visited_in_path = set()
        
        while queue and len(paths) < 100:  # Limit to 100 paths
            current_ref, path = queue.pop(0)
            
            if len(path) > max_hops:
                continue
            
            current_fp = self.extractor.get_footprint_by_reference(current_ref)
            if not current_fp:
                continue
            
            for pad in current_fp.Pads():
                net = pad.GetNet()
                if not net:
                    continue
                
                net_name = net.GetNetname()
                if net_name.lower() in ["", "unconnected"]:
                    continue
                
                pads_on_net = self.net_to_pads_map.get(net_name, [])
                
                for next_fp, next_pad in pads_on_net:
                    next_ref = next_fp.GetReference()
                    
                    if next_ref == current_ref:
                        continue
                    
                    # Create path entry
                    hop = {
                        "From Reference": current_ref,
                        "From Pin": pad.GetPadName(),
                        "Net Name": net_name,
                        "To Reference": next_ref,
                        "To Pin": next_pad.GetPadName()
                    }
                    
                    new_path = path + [hop]
                    
                    if next_ref == end_ref:
                        paths.append(new_path)
                    elif next_ref not in visited_in_path and len(new_path) < max_hops:
                        visited_in_path.add(next_ref)
                        queue.append((next_ref, new_path))
        
        return paths
