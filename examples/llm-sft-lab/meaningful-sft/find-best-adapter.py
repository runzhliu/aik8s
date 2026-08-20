#!/usr/bin/env python3
"""Print the validation-selected Adapter path from a Trainer output tree."""

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir")
    args = parser.parse_args()
    root = Path(args.output_dir)

    states = sorted(root.glob("**/trainer_state.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for state_path in states:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        best = state.get("best_model_checkpoint")
        if not best:
            continue
        best_path = Path(best)
        if (best_path / "adapter_config.json").is_file():
            print(best_path)
            return
        relocated = list(root.glob(f"**/{best_path.name}/adapter_config.json"))
        if relocated:
            print(relocated[0].parent)
            return

    adapters = sorted(root.glob("**/adapter_config.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not adapters:
        raise FileNotFoundError(f"No adapter_config.json found under {root}")
    print(adapters[0].parent)


if __name__ == "__main__":
    main()
