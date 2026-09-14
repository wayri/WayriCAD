#!/usr/bin/env python3
"""
WayriCAD Extract Pins Plugin - Example Scripts

These examples demonstrate CLI usage for common documentation tasks.
Run from the directory containing your .kicad_pcb file.

Usage:
    python examples.py <example_name> <pcb_file>
    
    Or run individual examples:
    python -m extract_pins_plugin <command> [options] <pcb_file>
"""

import subprocess
import sys
import os
from pathlib import Path


def run_cli(args: list, output_file: str = None):
    """Run a CLI command and optionally save output."""
    cmd = [sys.executable, "-m", "extract_pins_plugin"] + args
    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd)}")
    print('='*60)
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return None
    
    output = result.stdout
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"Output saved to: {output_file}")
    else:
        print(output[:2000] + ("..." if len(output) > 2000 else ""))
    
    return output


def example_extract_all_connectors(pcb_file: str, output_dir: str = "output"):
    """
    Example 1: Extract all connector (J*) pin data to CSV and Markdown.
    
    Use case: Create connector documentation for manufacturing.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n" + "="*60)
    print("EXAMPLE 1: Extract All Connectors")
    print("="*60)
    
    # CSV output - good for spreadsheet analysis
    run_cli([
        "extract",
        "--refs", "J*",
        "--format", "csv",
        "--sort-by-net-type",
        "-o", f"{output_dir}/connectors.csv",
        pcb_file
    ])
    
    # Markdown output - good for documentation
    run_cli([
        "extract", 
        "--refs", "J*",
        "--format", "md",
        "--highlight",
        "-o", f"{output_dir}/connectors.md",
        pcb_file
    ])


def example_signal_flow_connector_to_mcu(pcb_file: str, output_dir: str = "output"):
    """
    Example 2: Generate signal flow from connectors to MCU/CPU.
    
    Use case: Document all signals entering your MCU from external connectors.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n" + "="*60)
    print("EXAMPLE 2: Signal Flow - Connectors to MCU")
    print("="*60)
    
    # Table format
    run_cli([
        "signal-flow",
        "--source", "J*",
        "--dest", "U1",  # Assuming U1 is MCU
        "--format", "md",
        "--highlight",
        "-o", f"{output_dir}/connector_to_mcu.md",
        pcb_file
    ])
    
    # SVG diagram
    run_cli([
        "signal-flow",
        "--source", "J*",
        "--dest", "U1",
        "--format", "svg",
        "-o", f"{output_dir}/connector_to_mcu.svg",
        pcb_file
    ])


def example_ic_signal_chart(pcb_file: str, ic_ref: str = "U1", output_dir: str = "output"):
    """
    Example 3: Generate complete IC signal chart.
    
    Use case: Document all connections to/from a specific IC for debugging.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n" + "="*60)
    print(f"EXAMPLE 3: IC Signal Chart for {ic_ref}")
    print("="*60)
    
    # Exclude power nets for cleaner signal chart
    run_cli([
        "ic-chart",
        "--ic", ic_ref,
        "--format", "svg",
        "-o", f"{output_dir}/{ic_ref}_signal_chart.svg",
        pcb_file
    ])
    
    # Include power nets for complete documentation
    run_cli([
        "ic-chart",
        "--ic", ic_ref,
        "--include-power",
        "--format", "csv",
        "-o", f"{output_dir}/{ic_ref}_all_pins.csv",
        pcb_file
    ])


def example_unique_nets_by_type(pcb_file: str, output_dir: str = "output"):
    """
    Example 4: Extract unique nets grouped by type (signal/power/ground).
    
    Use case: Net list for design review or impedance planning.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n" + "="*60)
    print("EXAMPLE 4: Unique Nets by Type")
    print("="*60)
    
    # Signal nets only (from connectors)
    run_cli([
        "unique-nets",
        "--refs", "J*",
        "--ignore-power",
        "--format", "csv",
        "-o", f"{output_dir}/signal_nets.csv",
        pcb_file
    ])
    
    # All nets grouped by type
    run_cli([
        "unique-nets",
        "--refs", "J*,U*",
        "--sort-by-type",
        "--format", "md",
        "-o", f"{output_dir}/all_nets_grouped.md",
        pcb_file
    ])


def example_spi_i2c_documentation(pcb_file: str, output_dir: str = "output"):
    """
    Example 5: Document SPI and I2C buses.
    
    Use case: Bus documentation for firmware development.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n" + "="*60)
    print("EXAMPLE 5: SPI/I2C Bus Documentation")
    print("="*60)
    
    # SPI signals
    run_cli([
        "extract",
        "--refs", "J*,U*",
        "--net-filter", "SPI*,MOSI*,MISO*,SCK*,CS*,SS*",
        "--format", "md",
        "-o", f"{output_dir}/spi_bus.md",
        pcb_file
    ])
    
    # I2C signals  
    run_cli([
        "extract",
        "--refs", "J*,U*",
        "--net-filter", "I2C*,SDA*,SCL*,TWI*",
        "--format", "md",
        "-o", f"{output_dir}/i2c_bus.md",
        pcb_file
    ])


def example_test_point_map(pcb_file: str, output_dir: str = "output"):
    """
    Example 6: Generate test point documentation.
    
    Use case: Create test point map for production testing.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n" + "="*60)
    print("EXAMPLE 6: Test Point Documentation")
    print("="*60)
    
    run_cli([
        "extract",
        "--refs", "TP*",
        "--format", "csv",
        "-o", f"{output_dir}/test_points.csv",
        pcb_file
    ])


def example_power_distribution(pcb_file: str, output_dir: str = "output"):
    """
    Example 7: Document power distribution network.
    
    Use case: Power rail documentation for power integrity analysis.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n" + "="*60)
    print("EXAMPLE 7: Power Distribution")
    print("="*60)
    
    # Find all components on power nets
    run_cli([
        "extract",
        "--refs", "*",
        "--net-filter", "VCC*,VDD*,3V3*,5V*,12V*,GND*,VSS*",
        "--format", "csv",
        "-o", f"{output_dir}/power_connections.csv",
        pcb_file
    ])


def example_connector_pinout_comparison(pcb_file: str, output_dir: str = "output"):
    """
    Example 8: Compare pinouts of multiple connectors.
    
    Use case: Verify cable harness design between boards.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n" + "="*60)
    print("EXAMPLE 8: Connector Pinout Comparison")
    print("="*60)
    
    # Export each connector type
    for ref_pattern in ["J1", "J2", "J3"]:
        run_cli([
            "extract",
            "--refs", ref_pattern,
            "--format", "csv",
            "--ignore-unconnected",
            "-o", f"{output_dir}/{ref_pattern}_pinout.csv",
            pcb_file
        ])


def example_batch_ic_charts(pcb_file: str, output_dir: str = "output"):
    """
    Example 9: Generate signal charts for all ICs.
    
    Use case: Complete IC documentation for the entire board.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n" + "="*60)
    print("EXAMPLE 9: Batch IC Signal Charts")
    print("="*60)
    
    # Generate charts for all U* components
    run_cli([
        "ic-chart",
        "--ic", "U*",
        "--format", "svg",
        "-o", f"{output_dir}/ic_charts.svg",
        pcb_file
    ])


def example_full_board_documentation(pcb_file: str, output_dir: str = "output"):
    """
    Example 10: Generate complete board documentation package.
    
    Use case: Full documentation for design review or handoff.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n" + "="*60)
    print("EXAMPLE 10: Full Board Documentation")
    print("="*60)
    
    # Component list
    run_cli([
        "list",
        "--format", "csv",
        "-o", f"{output_dir}/component_list.csv",
        pcb_file
    ])
    
    # Connector documentation
    run_cli([
        "extract",
        "--refs", "J*,P*",
        "--format", "md",
        "--highlight",
        "-o", f"{output_dir}/connectors.md",
        pcb_file
    ])
    
    # Net list
    run_cli([
        "unique-nets",
        "--sort-by-type",
        "--format", "md",
        "-o", f"{output_dir}/net_list.md",
        pcb_file
    ])
    
    # Signal flow if MCU exists
    run_cli([
        "signal-flow",
        "--source", "J*",
        "--dest", "U*",
        "--format", "md",
        "-o", f"{output_dir}/signal_flow.md",
        pcb_file
    ])
    
    print(f"\n✅ Documentation package created in: {output_dir}/")


# CLI interface for running examples
EXAMPLES = {
    "connectors": example_extract_all_connectors,
    "signal-flow": example_signal_flow_connector_to_mcu,
    "ic-chart": example_ic_signal_chart,
    "unique-nets": example_unique_nets_by_type,
    "buses": example_spi_i2c_documentation,
    "test-points": example_test_point_map,
    "power": example_power_distribution,
    "pinout": example_connector_pinout_comparison,
    "batch-ics": example_batch_ic_charts,
    "full-doc": example_full_board_documentation,
}


def main():
    if len(sys.argv) < 3:
        print("WayriCAD Extract Pins - Example Scripts")
        print("="*50)
        print(f"\nUsage: python {sys.argv[0]} <example> <pcb_file> [output_dir]")
        print("\nAvailable examples:")
        for name, func in EXAMPLES.items():
            doc = func.__doc__.split('\n')[1].strip() if func.__doc__ else ""
            print(f"  {name:15} - {doc}")
        print(f"\n  all           - Run all examples")
        print(f"\nExample:")
        print(f"  python {sys.argv[0]} connectors my_board.kicad_pcb")
        print(f"  python {sys.argv[0]} full-doc my_board.kicad_pcb docs/")
        sys.exit(1)
    
    example_name = sys.argv[1]
    pcb_file = sys.argv[2]
    output_dir = sys.argv[3] if len(sys.argv) > 3 else "output"
    
    if not os.path.exists(pcb_file):
        print(f"Error: PCB file not found: {pcb_file}")
        sys.exit(1)
    
    if example_name == "all":
        for name, func in EXAMPLES.items():
            try:
                func(pcb_file, output_dir)
            except Exception as e:
                print(f"Error in {name}: {e}")
    elif example_name in EXAMPLES:
        EXAMPLES[example_name](pcb_file, output_dir)
    else:
        print(f"Unknown example: {example_name}")
        print(f"Available: {', '.join(EXAMPLES.keys())}")
        sys.exit(1)


if __name__ == "__main__":
    main()
