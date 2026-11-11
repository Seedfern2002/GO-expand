"""Query existing biological knowledge and publish evidence-backed proposals."""

import argparse
from collections import Counter
import json
from pathlib import Path

from engine.knowledge import read_json, workspace_file
from engine.knowledge_context import KnowledgeContext


def output_path(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Output must stay inside the task workspace")
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, default=Path.cwd())
    commands = p.add_subparsers(dest="command", required=True)
    b = commands.add_parser("build")
    b.add_argument("--index", required=True)
    q = commands.add_parser("query")
    q.add_argument("--index", required=True)
    q.add_argument("--genes", nargs="*", default=[])
    q.add_argument("--concept-id")
    q.add_argument("--label")
    q.add_argument("--limit", type=int, default=30)
    q.add_argument("--offset", type=int, default=0)
    q.add_argument("--output")
    a = commands.add_parser("propose")
    a.add_argument("--index", required=True)
    a.add_argument("--records", required=True)
    a.add_argument("--output", required=True)
    a.add_argument("--concepts")
    a.add_argument("--equivalences")
    args = p.parse_args()
    root = args.workspace.resolve()
    index = output_path(root, args.index)
    if args.command == "build":
        ctx = KnowledgeContext.build(root, index)
        result = {"index": str(index.relative_to(root)), "status": "ready"}
    else:
        if not index.is_file():
            raise FileNotFoundError(index)
        ctx = KnowledgeContext(index)
        if args.command == "query":
            result = ctx.query(args.genes, args.concept_id, args.label, args.limit, args.offset)
            if args.output:
                target = output_path(root, args.output)
                if target.exists():
                    raise FileExistsError(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(result, indent=2) + "\n")
                result = {"context_path": str(target.relative_to(root)), "gene_queries": len(args.genes), "concept_candidates": len(result["concepts"])}
        else:
            result = ctx.propose(root, workspace_file(root, args.records), output_path(root, args.output),
                                 read_json(workspace_file(root, args.concepts)) if args.concepts else [],
                                 read_json(workspace_file(root, args.equivalences)) if args.equivalences else [])
            result["action_counts"] = dict(Counter(row["action"] for row in result.pop("actions")))
            result["decisions_path"] = str((output_path(root, args.output) / "decisions.jsonl").relative_to(root))
    ctx.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
