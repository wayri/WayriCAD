# Core module for KiWay Extract Pins Plugin
# Contains shared logic for both GUI and CLI interfaces

from .data_extractor import DataExtractor, DEFAULT_POWER_NET_PATTERNS
from .signal_flow import SignalFlowAnalyzer
from .formatters import MarkdownFormatter, CSVFormatter, JSONFormatter, get_formatter
from .diagram_generator import SVGDiagramGenerator
from .schematic_graph import SchematicGraphParser, InterfaceSignal
from .test_point_extractor import TestPointExtractor
from .layout_assistant import LayoutAssistant
from .doc_generator import DocGenerator
from .board_extract import extract_board_pin_rows, protocol_color
from .cross_linker import (
    CrossProjectLinker,
    ImportedPinDocument,
    LinkRule,
    PinDocumentImporter,
    PinEndpoint,
    parse_link_rules,
)
from .power_tree import PowerTreeAnalyzer, generate_power_tree_svg
from .controller_connector_mapper import (
    ACTIVE_RULE_EXAMPLES,
    DEFAULT_PASSIVE_RULE_TEXT,
    ControllerConnectorMapper,
    TraversalRule,
    parse_traversal_rules,
    rows_to_markdown,
)

__all__ = [
    'DataExtractor',
    'DEFAULT_POWER_NET_PATTERNS',
    'SignalFlowAnalyzer', 
    'MarkdownFormatter',
    'CSVFormatter',
    'JSONFormatter',
    'get_formatter',
    'SVGDiagramGenerator',
    'SchematicGraphParser',
    'InterfaceSignal',
    'TestPointExtractor',
    'LayoutAssistant',
    'DocGenerator',
    'extract_board_pin_rows',
    'protocol_color',
    'CrossProjectLinker',
    'ImportedPinDocument',
    'LinkRule',
    'PinDocumentImporter',
    'PinEndpoint',
    'parse_link_rules',
    'PowerTreeAnalyzer',
    'generate_power_tree_svg',
    'ACTIVE_RULE_EXAMPLES',
    'DEFAULT_PASSIVE_RULE_TEXT',
    'ControllerConnectorMapper',
    'TraversalRule',
    'parse_traversal_rules',
    'rows_to_markdown',
]
