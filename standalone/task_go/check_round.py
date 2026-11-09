"""Preview the controller's validation of a retrieval-round draft result."""

import argparse
import json
from pathlib import Path

from engine.knowledge import read_json
from engine.rounds import validate_round
from run import validate_schema

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--round-directory", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    state_path = root / "rounds/state.json"
    state = read_json(state_path) if state_path.exists() else {"candidates": {"batches": []}, "observations": [], "progress": {}}
    validate_schema(read_json(args.result), read_json(args.round_directory / "schema.json"))
    checked = validate_round(read_json(root / "task.json"), read_json(args.result), root, args.round_directory, state)
    print(json.dumps({"passed": True, "progress": checked["progress"]}, indent=2))
