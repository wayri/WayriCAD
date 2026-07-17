# data_extractor.py
"""
Core data extraction logic for KiWay Extract Pins Plugin.
This module is shared between GUI and CLI interfaces.

@author - Wayri (Yawar)
@version - 2.0.0
"""

import re
from typing import Dict, List, Any, Optional, Set, Tuple


# Default patterns for identifying power nets
DEFAULT_POWER_NET_PATTERNS = [
    "VCC*", "VDD*", "VBAT*", "VBUS*", "VIN*", "VOUT*",
    "+*V", "+*V*", "*+*V", "3V3*", "3.3V*", "5V*", "12V*", "1V8*",
    "GND*", "AGND*", "DGND*", "PGND*", "VSS*", "AVSS*", "DVSS*",
    "PWR*", "POWER*", "*_PWR", "*_POWER",
    "V+", "V-", "+V", "-V"
]

# Ground net patterns (subset of power nets)
DEFAULT_GROUND_NET_PATTERNS = [
    "GND*", "AGND*", "DGND*", "PGND*", "VSS*", "AVSS*", "DVSS*", "GNDA*", "GNDD*"
]

# Supply voltage patterns (subset of power nets)
DEFAULT_SUPPLY_NET_PATTERNS = [
    "VCC*", "VDD*", "VBAT*", "VBUS*", "VIN*", "VOUT*",
    "+*V", "+*V*", "3V3*", "3.3V*", "5V*", "12V*", "1V8*",
    "V+", "+V", "PWR*", "POWER*"
]


class DataExtractor:
    """
    Extracts pin and component data from KiCAD PCB boards.
    This class encapsulates all data extraction logic to be reusable
    across GUI and CLI interfaces.
    """

    def __init__(self, board, power_net_patterns: list = None):
        """
        Initialize the data extractor with a KiCAD board reference.
        
        Args:
            board: A pcbnew.BOARD object
            power_net_patterns: Optional list of wildcard patterns for power nets
        """
        self.board = board
        self._footprints_cache = None
        self._nets_cache = None
        self._net_to_pads_cache = None
        
        # Compile power net patterns for classification
        patterns = power_net_patterns if power_net_patterns else DEFAULT_POWER_NET_PATTERNS
        self._power_net_regexes = [
            re.compile(self.convert_wildcard_to_regex(p.upper())) 
            for p in patterns
        ]
        self._ground_net_regexes = [
            re.compile(self.convert_wildcard_to_regex(p.upper())) 
            for p in DEFAULT_GROUND_NET_PATTERNS
        ]
        self._supply_net_regexes = [
            re.compile(self.convert_wildcard_to_regex(p.upper())) 
            for p in DEFAULT_SUPPLY_NET_PATTERNS
        ]

    @property
    def footprints(self) -> list:
        """Cached list of all footprints on the board."""
        if self._footprints_cache is None:
            self._footprints_cache = list(self.board.GetFootprints())
        return self._footprints_cache

    @property
    def all_nets(self) -> Set[str]:
        """Cached set of all net names on the board."""
        if self._nets_cache is None:
            self._nets_cache = set()
            for fp in self.footprints:
                for pad in fp.Pads():
                    net = pad.GetNet()
                    if net:
                        self._nets_cache.add(net.GetNetname())
        return self._nets_cache

    def get_net_to_pads_map(self) -> Dict[str, List[Tuple[Any, Any]]]:
        """
        Build and cache a mapping from net names to list of (footprint, pad) tuples.
        Essential for signal flow analysis.
        """
        if self._net_to_pads_cache is None:
            self._net_to_pads_cache = {}
            for fp in self.footprints:
                for pad in fp.Pads():
                    net = pad.GetNet()
                    if net:
                        net_name = net.GetNetname()
                        if net_name not in self._net_to_pads_cache:
                            self._net_to_pads_cache[net_name] = []
                        self._net_to_pads_cache[net_name].append((fp, pad))
        return self._net_to_pads_cache

    def classify_net(self, net_name: str) -> str:
        """
        Classify a net as 'ground', 'supply', 'power', or 'signal'.
        
        Args:
            net_name: The net name to classify
        
        Returns:
            One of: 'ground', 'supply', 'power', 'signal'
        """
        net_upper = net_name.upper()
        
        # Check ground first (most specific)
        for regex in self._ground_net_regexes:
            if regex.fullmatch(net_upper):
                return 'ground'
        
        # Check supply voltages
        for regex in self._supply_net_regexes:
            if regex.fullmatch(net_upper):
                return 'supply'
        
        # Check general power (catches remaining power patterns)
        for regex in self._power_net_regexes:
            if regex.fullmatch(net_upper):
                return 'power'
        
        return 'signal'

    def is_power_net(self, net_name: str) -> bool:
        """Check if a net is a power net (ground, supply, or power)."""
        return self.classify_net(net_name) != 'signal'

    def sort_nets_by_type(
        self,
        nets: List[str],
        signals_first: bool = True,
        group_power: bool = True
    ) -> List[str]:
        """
        Sort nets with power nets grouped separately from signal nets.
        
        Args:
            nets: List of net names to sort
            signals_first: If True, signal nets come before power nets
            group_power: If True, group power nets by type (supply/ground)
        
        Returns:
            Sorted list of net names
        """
        # Classify all nets
        classified = {}
        for net in nets:
            net_type = self.classify_net(net)
            if net_type not in classified:
                classified[net_type] = []
            classified[net_type].append(net)
        
        # Sort each group naturally
        for net_type in classified:
            classified[net_type].sort(key=self.natural_sort_key)
        
        # Build result based on preferences
        result = []
        
        if signals_first:
            # Signals first, then power
            result.extend(classified.get('signal', []))
            if group_power:
                result.extend(classified.get('supply', []))
                result.extend(classified.get('ground', []))
                result.extend(classified.get('power', []))
            else:
                power_nets = (
                    classified.get('supply', []) + 
                    classified.get('ground', []) + 
                    classified.get('power', [])
                )
                power_nets.sort(key=self.natural_sort_key)
                result.extend(power_nets)
        else:
            # Power first, then signals
            if group_power:
                result.extend(classified.get('supply', []))
                result.extend(classified.get('ground', []))
                result.extend(classified.get('power', []))
            else:
                power_nets = (
                    classified.get('supply', []) + 
                    classified.get('ground', []) + 
                    classified.get('power', [])
                )
                power_nets.sort(key=self.natural_sort_key)
                result.extend(power_nets)
            result.extend(classified.get('signal', []))
        
        return result

    @staticmethod
    def natural_sort_key(text: str) -> list:
        """Helper for natural sorting (e.g., J1, J2, J10 instead of J1, J10, J2)."""
        return [int(s) if s.isdigit() else s.lower() for s in re.split('([0-9]+)', text)]

    @staticmethod
    def convert_wildcard_to_regex(pattern: str) -> str:
        """Converts a wildcard pattern (e.g., 'J*') into a regex pattern."""
        escaped_pattern = re.escape(pattern)
        regex_pattern = escaped_pattern.replace(r'\*', '.*')
        return regex_pattern

    @staticmethod
    def get_footprint_property(footprint, prop_name: str) -> Optional[str]:
        """Safely retrieves a custom property value from a footprint."""
        try:
            fields = footprint.GetFields() if hasattr(footprint, "GetFields") else []
            for field in fields:
                if field.GetName() == prop_name:
                    return field.GetText()
        except Exception:
            return None
        return None

    def get_footprints_by_reference_pattern(self, pattern: str) -> List[Any]:
        """
        Get footprints matching a reference pattern (supports wildcards).
        
        Args:
            pattern: Reference pattern like "J*", "U*", "R1?", etc.
        
        Returns:
            List of matching footprints
        """
        regex = self.convert_wildcard_to_regex(pattern.upper())
        return [fp for fp in self.footprints 
                if re.fullmatch(regex, fp.GetReference().upper())]

    def get_footprints_by_connector_type(self, connector_types: List[str]) -> List[Any]:
        """
        Get footprints with specific connector-type property values.
        
        Args:
            connector_types: List of connector type values (supports wildcards)
        
        Returns:
            List of matching footprints
        """
        patterns = [self.convert_wildcard_to_regex(t.strip().lower()) 
                    for t in connector_types if t.strip()]
        
        result = []
        for fp in self.footprints:
            fp_type = self.get_footprint_property(fp, "connector-type")
            if fp_type is not None:
                fp_type_lower = fp_type.lower().strip()
                if any(re.fullmatch(p, fp_type_lower) for p in patterns):
                    result.append(fp)
        return result

    def get_footprint_by_reference(self, reference: str) -> Optional[Any]:
        """Get a single footprint by exact reference designator."""
        for fp in self.footprints:
            if fp.GetReference() == reference:
                return fp
        return None

    def extract_footprint_data(
        self,
        footprints: List[Any],
        ignore_unconnected: bool = False,
        ignore_free_pins: bool = False,
        ignore_power_nets: bool = False,
        value_filter: Optional[str] = None,
        net_filter: Optional[str] = None,
        sort_pins_by_net_type: bool = False
    ) -> Dict[str, Dict[str, Any]]:
        """
        Extract detailed data from a list of footprints.
        
        Args:
            footprints: List of footprints to extract data from
            ignore_unconnected: Skip pins with 'unconnected' net name
            ignore_free_pins: Skip pins with no net assigned
            ignore_power_nets: Skip power/ground nets
            value_filter: Optional wildcard filter for component values
            net_filter: Optional wildcard filter for net names
            sort_pins_by_net_type: If True, sort pins with signals first, power last
        
        Returns:
            Dictionary keyed by reference designator with component data
        """
        # Apply value filter
        if value_filter:
            value_regex = self.convert_wildcard_to_regex(value_filter.lower())
            footprints = [fp for fp in footprints 
                         if re.fullmatch(value_regex, fp.GetValue().lower())]

        # Apply net filter (keep footprints with at least one matching pin)
        if net_filter:
            net_patterns = [self.convert_wildcard_to_regex(p.strip().lower()) 
                          for p in net_filter.split(',') if p.strip()]
            if net_patterns:
                filtered = []
                for fp in footprints:
                    for pad in fp.Pads():
                        net = pad.GetNet()
                        if net:
                            net_name_lower = net.GetNetname().lower()
                            if any(re.fullmatch(p, net_name_lower) for p in net_patterns):
                                filtered.append(fp)
                                break
                footprints = filtered

        result = {}
        for fp in footprints:
            ref = fp.GetReference()
            pos = fp.GetPosition()
            rot = fp.GetOrientation()
            
            connector_type = self.get_footprint_property(fp, "connector-type") or ""
            try:
                description = fp.GetLibDescription() if hasattr(fp, "GetLibDescription") else ""
            except Exception:
                description = ""
            
            general_properties = {
                "Reference": ref,
                "Value": fp.GetValue(),
                "Footprint Name": str(fp.GetFPID()) if hasattr(fp, "GetFPID") else "",
                "Description": description if description and description != "No description" else "N/A",
                "Layer": fp.GetLayerName(),
                "Position": f"({pos.x / 1000000.0:.2f}mm, {pos.y / 1000000.0:.2f}mm)",
                "Rotation": f"{rot.AsDegrees():.1f}°",
                "Connector Type": connector_type
            }

            pins = []
            for pad in fp.Pads():
                net = pad.GetNet()
                is_connected = bool(net)
                net_name = net.GetNetname() if is_connected else ""
                is_unconnected_literal = net_name.lower() == "unconnected"

                # Apply pin filters
                if ignore_unconnected and is_unconnected_literal:
                    continue
                if ignore_free_pins and not is_connected:
                    continue
                if ignore_power_nets and net_name and self.is_power_net(net_name):
                    continue

                net_type = self.classify_net(net_name) if net_name else ""
                
                pins.append({
                    "Pad Name/Number": pad.GetPadName(),
                    "Net Name": net_name,
                    "Net Type": net_type
                })

            # Sort pins by net type if requested
            if sort_pins_by_net_type and pins:
                type_order = {'signal': 0, 'supply': 1, 'ground': 2, 'power': 3, '': 4}
                pins.sort(key=lambda p: (
                    type_order.get(p.get('Net Type', ''), 4),
                    self.natural_sort_key(p.get('Pad Name/Number', ''))
                ))

            result[ref] = {
                "general_properties": general_properties,
                "pins": pins
            }

        return result

    def extract_unique_nets(
        self,
        footprints: List[Any],
        ignore_unconnected: bool = False,
        ignore_free_pins: bool = False,
        ignore_power_nets: bool = False,
        net_filter: Optional[str] = None,
        sort_by_type: bool = False
    ) -> List[str]:
        """
        Extract unique net names from a set of footprints.
        
        Args:
            footprints: List of footprints to scan
            ignore_unconnected: Skip 'unconnected' nets
            ignore_free_pins: Skip unconnected pads
            ignore_power_nets: Skip power/ground nets
            net_filter: Optional wildcard filter for net names
            sort_by_type: If True, sort with signals first, power grouped at end
        
        Returns:
            Sorted list of unique net names
        """
        unique_nets = set()
        
        for fp in footprints:
            for pad in fp.Pads():
                net = pad.GetNet()
                if net:
                    net_name = net.GetNetname()
                    is_unconnected = net_name.lower() == "unconnected"
                    
                    if ignore_unconnected and is_unconnected:
                        continue
                    if ignore_free_pins and not net:
                        continue
                    if ignore_power_nets and self.is_power_net(net_name):
                        continue
                    
                    unique_nets.add(net_name)

        # Apply net filter
        if net_filter:
            patterns = [self.convert_wildcard_to_regex(p.strip().lower()) 
                       for p in net_filter.split(',') if p.strip()]
            if patterns:
                unique_nets = {n for n in unique_nets 
                              if any(re.fullmatch(p, n.lower()) for p in patterns)}

        net_list = list(unique_nets)
        
        if sort_by_type:
            return self.sort_nets_by_type(net_list, signals_first=True, group_power=True)
        else:
            return sorted(net_list, key=self.natural_sort_key)
