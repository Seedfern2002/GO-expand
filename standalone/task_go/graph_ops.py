"""Read the current task graph and source module catalog from compact queries."""
import argparse
import json
from pathlib import Path
from engine.module_graph import GraphContext


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=Path("graph/current.json"))
    parser.add_argument("--module")
    parser.add_argument("--concept")
    parser.add_argument("--label")
    parser.add_argument("--concepts", nargs="+")
    parser.add_argument("--labels", nargs="+")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--neighbor-offset", type=int, default=0)
    args = parser.parse_args()
    if not 1 <= args.limit <= 30:
        raise ValueError("Query page size must be between 1 and 30")
    if min(args.offset, args.neighbor_offset) < 0:
        raise ValueError("Query offsets must be nonnegative")
    graph = json.loads(args.graph.read_text())
    catalog = json.loads(Path("inputs/modules.json").read_text())
    facts = json.loads(Path("inputs/placement_evidence.json").read_text())
    context = GraphContext(graph, catalog, facts)
    if args.module:
        result = context.module(args.module, args.limit)
    elif args.concept:
        result = context.node(args.concept, args.limit, args.neighbor_offset)
    elif args.label:
        result = context.search(args.label, args.limit, args.offset)
    elif args.concepts:
        result = {key: context.node(key, args.limit, args.neighbor_offset) for key in args.concepts}
    elif args.labels:
        result = [context.search(label, args.limit, args.offset) for label in args.labels]
    else:
        parser.error("Supply --module, --concept, --label, --concepts or --labels")
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
