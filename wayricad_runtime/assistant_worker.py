"""Isolated fixed-action CLI dispatcher used by the local Assistant broker."""

from pathlib import Path
import json
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
# An independent Assistant PCM contains its own complete headless backend set.
# A wheel/source checkout already has canonical packages at ROOT.
sys.path.insert(0, str(ROOT))
if (ROOT / "_suite").is_dir():
    sys.path.insert(0, str(ROOT / "_suite"))


def main():
    from wayricad_runtime.assistant import validate_plan, _compile, _relative
    from wayricad_runtime.jobs import load_json
    from wayricad_runtime.tool_cli import COMMANDS

    try:
        if len(sys.argv) != 2:
            raise ValueError("Expected one private worker request.")
        request = load_json(sys.argv[1])
        if not isinstance(request, dict) or set(request) != {
            "plan",
            "index",
            "output_dir",
        }:
            raise ValueError("Invalid worker request.")
        plan = validate_plan(request["plan"])
        index = request["index"]
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < len(plan["steps"])
        ):
            raise ValueError("Invalid action index.")
        output = Path(request["output_dir"]).resolve()
        if (
            output != Path(sys.argv[1]).resolve().parent
            or output != Path.cwd().resolve()
        ):
            raise ValueError("Worker output directory changed.")
        compiled = _compile(plan["steps"][index], plan["context"], output)
        for name, document in compiled["documents"].items():
            if load_json(_relative(output, name)) != document:
                raise ValueError("Generated action inputs changed before execution.")
        module, prefix, _ = COMMANDS[compiled["tool"]]
        sys.argv = [module, *prefix, *compiled["arguments"]]
        runpy.run_module(module, run_name="__main__", alter_sys=True)
        return 0
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
