"""Skill entrypoint for the task-local knowledge operations."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from knowledge_ops import main

if __name__ == "__main__":
    main()
