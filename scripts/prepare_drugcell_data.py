#!/usr/bin/env python3
"""Validate released DrugCell inputs and freeze reproducible grouped CV splits.

All measurements of a (cell, drug) pair share a partition.  The shuffle seed and
fold assignment are project replication choices; published fold IDs are absent
from the released complete response table.  Source inputs are read unchanged.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
INPUT_NAMES = (
    "gene2ind.txt", "cell2ind.txt", "drug2ind.txt", "cell2mutation.txt",
    "drug2fingerprint.txt", "drugcell_ont.txt",
)
PARTITIONS = ("train", "validation", "test")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path):
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": sha256_file(path)}


def load_mapping(path):
    """Read a complete contiguous zero-based upstream ID mapping."""
    mapping = {}
    indices = set()
    with Path(path).open() as handle:
        for line_number, line in enumerate(handle, 1):
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 2:
                raise ValueError(f"{path}:{line_number}: expected index and identifier")
            index = int(fields[0])
            identifier = fields[1]
            if not identifier or identifier in mapping or index in indices:
                raise ValueError(f"{path}:{line_number}: duplicate or empty mapping entry")
            mapping[identifier] = index
            indices.add(index)
    if not mapping or indices != set(range(len(mapping))):
        raise ValueError(f"{path}: mapping indices must be contiguous from zero")
    return mapping


def validate_binary_matrix(path, expected_rows, expected_columns):
    row_count = 0
    ones = 0
    with Path(path).open() as handle:
        for row_count, line in enumerate(handle, 1):
            fields = line.rstrip("\r\n").split(",")
            if len(fields) != expected_columns:
                raise ValueError(f"{path}:{row_count}: expected {expected_columns} columns")
            try:
                values = [float(value) for value in fields]
            except ValueError as exc:
                raise ValueError(f"{path}:{row_count}: invalid numeric feature") from exc
            if any(value not in (0.0, 1.0) for value in values):
                raise ValueError(f"{path}:{row_count}: feature matrix must be binary")
            ones += sum(value == 1.0 for value in values)
    if row_count != expected_rows:
        raise ValueError(f"{path}: expected {expected_rows} rows, found {row_count}")
    return {"rows": row_count, "columns": expected_columns, "binary": True,
            "nonzero_entries": ones}


def validate_ontology(path, genes):
    terms = set()
    hierarchy = set()
    direct = set()
    with Path(path).open() as handle:
        for line_number, line in enumerate(handle, 1):
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 3 or fields[2] not in ("default", "gene"):
                raise ValueError(f"{path}:{line_number}: invalid ontology row")
            parent, child, kind = fields
            terms.add(parent)
            if kind == "default":
                if (parent, child) in hierarchy:
                    raise ValueError(f"{path}:{line_number}: duplicate ontology edge")
                terms.add(child)
                hierarchy.add((parent, child))
            else:
                if child not in genes:
                    raise ValueError(f"{path}:{line_number}: unknown gene {child}")
                if (parent, child) in direct:
                    raise ValueError(f"{path}:{line_number}: duplicate gene annotation")
                direct.add((parent, child))
    children = defaultdict(set)
    parents = defaultdict(set)
    reachable = {term: set() for term in terms}
    for parent, child in hierarchy:
        children[parent].add(child)
        parents[child].add(parent)
    for term, gene in direct:
        reachable[term].add(gene)
    roots = sorted(term for term in terms if not parents[term])
    if len(roots) != 1:
        raise ValueError(f"{path}: ontology must have exactly one root")
    remaining = {term: len(children[term]) for term in terms}
    leaves = deque(term for term in sorted(terms) if not children[term])
    heights = {term: 0 for term in leaves}
    visited = 0
    while leaves:
        term = leaves.popleft()
        visited += 1
        if not reachable[term]:
            raise ValueError(f"{path}: ontology term {term} has no descendant genes")
        for parent in parents[term]:
            reachable[parent].update(reachable[term])
            heights[parent] = max(heights.get(parent, 0), heights[term] + 1)
            remaining[parent] -= 1
            if remaining[parent] == 0:
                leaves.append(parent)
    if visited != len(terms):
        raise ValueError(f"{path}: ontology has a directed cycle")
    return {"terms": len(terms), "hierarchy_edges": len(hierarchy),
            "direct_gene_edges": len(direct), "root": roots[0],
            "annotated_genes": len({gene for _, gene in direct}),
            "reachable_gene_term_memberships": sum(map(len, reachable.values())),
            "maximum_height_edges": max(heights.values()), "acyclic": True}


def scan_responses(path, cells, drugs):
    groups = {}
    counts = []
    observed_cells = set()
    observed_drugs = set()
    total_rows = 0
    minimum = math.inf
    maximum = -math.inf
    with Path(path).open() as handle:
        for line_number, line in enumerate(handle, 1):
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 3:
                raise ValueError(f"{path}:{line_number}: expected cell, drug and response")
            cell, drug, label_text = fields
            if cell not in cells or drug not in drugs:
                raise ValueError(f"{path}:{line_number}: unknown cell or drug identifier")
            try:
                label = float(label_text)
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: invalid response") from exc
            if not math.isfinite(label):
                raise ValueError(f"{path}:{line_number}: response must be finite")
            pair = (cell, drug)
            group_id = groups.get(pair)
            if group_id is None:
                group_id = len(groups)
                groups[pair] = group_id
                counts.append(0)
            counts[group_id] += 1
            total_rows += 1
            observed_cells.add(cell)
            observed_drugs.add(drug)
            minimum = min(minimum, label)
            maximum = max(maximum, label)
    if not total_rows:
        raise ValueError(f"{path}: response table is empty")
    summary = {
        "rows": total_rows, "unique_cell_drug_pairs": len(groups),
        "additional_measurements_of_existing_pairs": total_rows - len(groups),
        "pairs_with_multiple_measurements": sum(count > 1 for count in counts),
        "measurement_count_distribution": dict(sorted(Counter(counts).items())),
        "observed_cells": len(observed_cells), "observed_drugs": len(observed_drugs),
        "label_minimum": minimum, "label_maximum": maximum,
        "all_identifiers_mapped": True, "all_labels_finite": True,
        "repeated_pair_measurements": "retained unchanged in the same partition",
    }
    return groups, counts, summary


def assign_groups(group_count, folds, validation_pairs, seed):
    if folds < 2 or validation_pairs < 1:
        raise ValueError("At least two folds and one validation pair are required")
    if group_count - math.ceil(group_count / folds) <= validation_pairs:
        raise ValueError("Insufficient unique pairs for nonempty training partitions")
    order = list(range(group_count))
    random.Random(seed).shuffle(order)
    test_fold = [0] * group_count
    for rank, group_id in enumerate(order):
        test_fold[group_id] = rank % folds
    validation_groups = []
    for fold in range(folds):
        eligible = [group_id for group_id in order if test_fold[group_id] != fold]
        random.Random(f"drugcell:{seed}:validation:{fold}").shuffle(eligible)
        validation_groups.append(set(eligible[:validation_pairs]))
    return test_fold, validation_groups


def partition_for(group_id, fold, test_fold, validation_groups):
    if test_fold[group_id] == fold:
        return "test"
    if group_id in validation_groups[fold]:
        return "validation"
    return "train"


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def prepare(source, responses, output, folds=5, validation_pairs=5000, seed=0):
    source, responses, output = map(lambda path: Path(path).resolve(), (source, responses, output))
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}; use a fresh destination")
    data = source / "data"
    genes = load_mapping(data / "gene2ind.txt")
    cells = load_mapping(data / "cell2ind.txt")
    drugs = load_mapping(data / "drug2ind.txt")
    matrices = {
        "cell_mutations": validate_binary_matrix(data / "cell2mutation.txt", len(cells), len(genes)),
        "drug_fingerprints": validate_binary_matrix(data / "drug2fingerprint.txt", len(drugs), 2048),
    }
    ontology = validate_ontology(data / "drugcell_ont.txt", genes)
    inputs = {name: file_record(data / name) for name in INPUT_NAMES}
    inputs["complete_responses"] = file_record(responses)
    groups, measurement_counts, response_summary = scan_responses(responses, cells, drugs)
    test_fold, validation_groups = assign_groups(len(groups), folds, validation_pairs, seed)
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = None
    fold_summaries = []
    for fold in range(folds):
        counts = {part: {"rows": 0, "unique_cell_drug_pairs": 0} for part in PARTITIONS}
        for group_id, measurements in enumerate(measurement_counts):
            part = partition_for(group_id, fold, test_fold, validation_groups)
            counts[part]["rows"] += measurements
            counts[part]["unique_cell_drug_pairs"] += 1
        fold_summaries.append({"fold": fold, "partitions": counts,
                               "pair_overlaps": {"train_validation": 0, "train_test": 0,
                                                 "validation_test": 0}})
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".drugcell-init-", dir=output.parent) as temp:
        staging = Path(temp) / "product"
        staging.mkdir()
        with ExitStack() as stack:
            handles = {}
            for fold in range(folds):
                directory = staging / "splits" / f"fold_{fold}"
                directory.mkdir(parents=True)
                for part in PARTITIONS:
                    handles[fold, part] = stack.enter_context((directory / f"{part}.tsv").open("w"))
            with responses.open() as handle:
                for line in handle:
                    cell, drug, _ = line.rstrip("\r\n").split("\t")
                    group_id = groups[cell, drug]
                    for fold in range(folds):
                        part = partition_for(group_id, fold, test_fold, validation_groups)
                        handles[fold, part].write(line.rstrip("\r\n") + "\n")
        for fold, summary in enumerate(fold_summaries):
            for part in PARTITIONS:
                relative = Path("splits") / f"fold_{fold}" / f"{part}.tsv"
                summary["partitions"][part].update({
                    "path": relative.as_posix(), "bytes": (staging / relative).stat().st_size,
                    "sha256": sha256_file(staging / relative),
                })
        if sha256_file(responses) != inputs["complete_responses"]["sha256"]:
            raise ValueError("Response input changed while preparing splits")
        protocol = {
            "folds": folds, "seed": seed, "seed_provenance": "project replication seed",
            "published_fold_ids": "unavailable in the released complete response table",
            "group_key": ["cell_identifier", "drug_identifier"],
            "test_assignment": "shuffle first-occurrence group IDs with random.Random(seed), then rank modulo folds",
            "validation_assignment": "shuffle non-test groups with random.Random(f'drugcell:{seed}:validation:{fold}') and take the requested number",
            "validation_unique_pairs_per_fold": validation_pairs,
            "all_measurements_retained": True, "output_row_order": "original source row order",
            "each_group_tested_once": True,
            "paper_protocol": "five pair-level folds and 5000 validation pairs; released rows are grouped here to retain repeated measurements together",
        }
        split_manifest = {"schema_version": 1, "protocol": protocol,
                          "response_source": inputs["complete_responses"], "folds": fold_summaries}
        write_json(staging / "split_manifest.json", split_manifest)
        manifest = {
            "schema_version": 1, "source_repository": "https://github.com/idekerlab/DrugCell",
            "source_commit": commit, "source_inputs": inputs,
            "mapped_entities": {"genes": len(genes), "cells": len(cells), "drugs": len(drugs)},
            "feature_matrices": matrices, "pruned_ontology": ontology,
            "responses": response_summary, "split_protocol": protocol,
            "split_manifest": {"path": "split_manifest.json",
                               "sha256": sha256_file(staging / "split_manifest.json")},
            "input_handling": "upstream files and complete response table read unchanged; hashes pin all inputs",
        }
        write_json(staging / "manifest.json", manifest)
        staging.rename(output)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "third_party/DrugCell")
    parser.add_argument("--responses", type=Path, default=ROOT / "data/raw/drugcell/v1/drugcell_all.txt")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/drugcell/v1")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--validation-pairs", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    manifest = prepare(args.source, args.responses, args.output, args.folds, args.validation_pairs, args.seed)
    print(json.dumps({"output": str(args.output.resolve()), "responses": manifest["responses"],
                      "pruned_ontology": manifest["pruned_ontology"]}, indent=2))


if __name__ == "__main__":
    main()
