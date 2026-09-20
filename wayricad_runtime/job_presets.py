"""Conservative, report-only command sequences for native KiCad job sets.

Each argument is intentionally a separate list entry.  The job-set runner is
responsible for expanding ``${...}`` tokens and for creating a fresh directory
for every step.  These are report sequences, not declarations of electrical,
manufacturing, or release compliance.
"""

from __future__ import annotations


# Values listed here must be supplied by a caller before the preset can run.
# The electrical sequence does not bake example signal or solver values into a
# project job set.
REQUIRED_VARIABLES = {
    "fabrication": (),
    "inventory": (),
    "electrical": (
        "net",
        "source",
        "sink",
        "voltage",
        "current",
        "rise_ns",
        "frequency_mhz",
    ),
    "bom": ("bom_pipeline",),
}


DESCRIPTIONS = {
    "fabrication": (
        "Runs KiCad's saved-board DRC and saved-schematic ERC with violation "
        "exit codes, then exports a native BOM CSV and board statistics. "
        "Reports are evidence for review, not a manufacturing-release approval."
    ),
    "inventory": (
        "Lists saved-board copper/path inputs for RLC, Quick PI, and Quick SI. "
        "It does not solve a selected electrical path."
    ),
    "electrical": (
        "Produces PI, SI, and RLC reports for one explicitly selected saved-board "
        "path.  Results retain each tool's modelling limits and are not protocol "
        "compliance or sign-off results."
    ),
    "bom": (
        "Runs an explicit BOM Studio data-only pipeline in a fresh subdirectory. "
        "Its manifest records hashes and policy gates; it does not certify ERC, DRC, "
        "or manufacturing approval."
    ),
}


PRESETS = {
    "fabrication": [
        {
            "id": "pcb_drc",
            "label": "Native PCB DRC report",
            "argv": [
                "${kicad_cli}", "pcb", "drc", "--format", "json", "--units", "mm",
                "--severity-error", "--severity-warning", "--exit-code-violations",
                "--output", "${step_dir}/drc.json", "${board}",
            ],
            "outputs": ["drc.json"],
            "timeout_seconds": 180,
        },
        {
            "id": "schematic_erc",
            "label": "Native schematic ERC report",
            "argv": [
                "${kicad_cli}", "sch", "erc", "--format", "json", "--units", "mm",
                "--severity-error", "--severity-warning", "--exit-code-violations",
                "--output", "${step_dir}/erc.json", "${schematic}",
            ],
            "outputs": ["erc.json"],
            "timeout_seconds": 180,
        },
        {
            "id": "native_bom",
            "label": "Native KiCad BOM CSV",
            "argv": [
                "${kicad_cli}", "sch", "export", "bom", "--output",
                "${step_dir}/bom.csv", "${schematic}",
            ],
            "outputs": ["bom.csv"],
            "depends_on": ["schematic_erc"],
            "timeout_seconds": 120,
        },
        {
            "id": "board_statistics",
            "label": "Native board statistics JSON",
            "argv": [
                "${kicad_cli}", "pcb", "export", "stats", "--format", "json",
                "--output", "${step_dir}/board-statistics.json", "${board}",
            ],
            "outputs": ["board-statistics.json"],
            "depends_on": ["pcb_drc"],
            "timeout_seconds": 120,
        },
    ],
    "inventory": [
        {
            "id": "rlc_inventory",
            "label": "RLC copper and net inventory",
            "argv": [
                "${native_python}", "-m", "trace_impedance_plugin.cli", "inspect",
                "${board}", "--output", "${step_dir}/rlc-inventory.json",
            ],
            "outputs": ["rlc-inventory.json"],
            "timeout_seconds": 120,
        },
        {
            "id": "pi_inventory",
            "label": "Quick PI power-net inventory",
            "argv": [
                "${python}", "-m", "quick_pi_plugin.cli", "${board}",
                "--output", "${step_dir}/pi-inventory.json",
            ],
            "outputs": ["pi-inventory.json"],
            "timeout_seconds": 300,
        },
        {
            "id": "si_inventory",
            "label": "Quick SI route inventory",
            "argv": [
                "${native_python}", "-m", "signal_integrity_advisor_plugin.cli", "inspect",
                "${board}", "--output", "${step_dir}/si-inventory.json",
            ],
            "outputs": ["si-inventory.json"],
            "timeout_seconds": 120,
        },
    ],
    "electrical": [
        {
            "id": "pi_path",
            "label": "Quick PI path report",
            "argv": [
                "${python}", "-m", "quick_pi_plugin.cli", "${board}", "--net", "${net}",
                "--source", "${source}", "--sink", "${sink}", "--voltage", "${voltage}",
                "--current", "${current}", "--output", "${step_dir}/pi.json", "--html",
                "${step_dir}/pi.html",
            ],
            "outputs": ["pi.json", "pi.html"],
            "timeout_seconds": 300,
        },
        {
            "id": "si_path",
            "label": "Quick SI path report",
            "argv": [
                "${native_python}", "-m", "signal_integrity_advisor_plugin.cli", "screen",
                "${board}", "--net", "${net}", "--start", "${source}", "--end", "${sink}",
                "--rise-ns", "${rise_ns}", "--frequency-mhz", "${frequency_mhz}",
                "--output", "${step_dir}/si.json", "--html", "${step_dir}/si.html",
            ],
            "outputs": ["si.json", "si.html"],
            "timeout_seconds": 180,
        },
        {
            "id": "rlc_path",
            "label": "RLC path report",
            "argv": [
                "${native_python}", "-m", "trace_impedance_plugin.cli", "path", "${board}",
                "--net", "${net}", "--start", "${source}", "--end", "${sink}",
                "--frequency-mhz", "${frequency_mhz}", "--output", "${step_dir}/rlc.json",
            ],
            "outputs": ["rlc.json"],
            "timeout_seconds": 180,
        },
    ],
    "bom": [
        {
            "id": "bom_pipeline",
            "label": "BOM Studio pipeline report",
            "argv": [
                "${python}", "-m", "bom_studio_plugin.bomstudio.cli", "run", "${project}",
                "--config", "${bom_pipeline}", "--output-dir", "${step_dir}/bom",
            ],
            "outputs": ["bom/manifest.json"],
            "timeout_seconds": 300,
        },
    ],
}
