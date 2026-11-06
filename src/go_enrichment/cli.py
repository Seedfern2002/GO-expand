import argparse
import json
from collections import Counter
from dataclasses import asdict

from .annotations import read_gaf
from .ontology import Ontology


def main():
    parser = argparse.ArgumentParser(description="Inspect GO ontology and annotation inputs")
    commands = parser.add_subparsers(dest="command", required=True)
    summary = commands.add_parser("summary", help="Count active terms and typed edges")
    summary.add_argument("obo")
    term = commands.add_parser("term", help="Show a term and its positive-grouping ancestors")
    term.add_argument("obo")
    term.add_argument("term_id")
    annotations = commands.add_parser("annotations", help="Stream GAF 2.2 annotations as JSON lines")
    annotations.add_argument("gaf")
    annotations.add_argument("--object-id", help="Qualified identifier, e.g. UniProtKB:P12345")
    annotations.add_argument("--taxon", help="Primary taxon, e.g. taxon:9606")
    annotations.add_argument("--evidence", nargs="+", help="Evidence codes to retain")
    args = parser.parse_args()
    try:
        if args.command == "annotations":
            for record in read_gaf(args.gaf):
                if args.object_id and record.object_id != args.object_id:
                    continue
                if args.taxon and record.taxon.split("|")[0] != args.taxon:
                    continue
                if args.evidence and record.evidence not in args.evidence:
                    continue
                print(json.dumps(asdict(record), ensure_ascii=False))
            return
        ontology = Ontology.read(args.obo)
        if args.command == "summary":
            active = [term for term in ontology.terms.values() if not term.obsolete]
            result = {
                "metadata": ontology.metadata,
                "active_terms": len(active),
                "obsolete_terms": len(ontology.terms) - len(active),
                "namespaces": dict(Counter(term.namespace for term in active)),
                "edge_relations": dict(Counter(rel for term in active for rel, _ in term.edges)),
            }
        else:
            selected = ontology.resolve(args.term_id)
            result = asdict(selected)
            result["positive_grouping_ancestors"] = (
                None if selected.obsolete else sorted(ontology.ancestors(selected.id))
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
