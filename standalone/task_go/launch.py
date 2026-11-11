"""Prepare and launch a self-contained, task-only GO augmentation workspace."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pickle
import shutil
import subprocess

from engine.knowledge import RELATIONS, sha256, write_json
from engine.reading import adaptive


TASK_FIELDS = {"task_id", "task_description", "organism", "biological_context", "candidate_categories",
               "knowledge_requirements", "retrieval_budget", "projection_policy", "source_candidates"}
CONTEXT_FIELDS = {"cell_type", "tissue", "perturbation", "condition"}


def import_paper_cache(source_root, workspace):
    """Copy external paper metadata/text only, using generic task-local paths."""
    source_root = Path(source_root).resolve()
    manifest = source_root / "acquisition/papers/manifest.jsonl"
    target = workspace / "inputs/paper_cache"
    target.mkdir()
    copied, count = {}, 0
    fields = {"paper_id", "pmid", "pmcid", "doi", "title", "pub_types", "topics", "isOpenAccess", "abstract"}
    with manifest.open() as stream, (target / "manifest.jsonl").open("w") as output:
        for line in stream:
            row = json.loads(line)
            item = {key: value for key, value in row.items() if key in fields}
            for name, suffix in [("text_path", ".txt"), ("xml_path", ".xml")]:
                if not row.get(name):
                    continue
                original = Path(row[name])
                if original.is_absolute():
                    original = original.relative_to("/workspace")
                source = (source_root / original).resolve()
                if not source.is_relative_to(source_root) or not source.is_file():
                    raise ValueError("Paper cache references an invalid source file")
                expected = row.get(name.removesuffix("_path") + "_sha256")
                if expected and sha256(source) != expected:
                    raise ValueError("Cached scientific text hash mismatch")
                if source not in copied:
                    destination = target / f"paper_{len(copied) + 1:05d}{suffix}"
                    shutil.copyfile(source, destination)
                    copied[source] = destination
                destination = copied[source]
                item[name] = str(destination.relative_to(workspace))
                item[name.removesuffix("_path") + "_sha256"] = sha256(destination)
            if "text_path" not in item:
                raise ValueError("Cached paper needs saved scientific text")
            output.write(json.dumps(item, ensure_ascii=False) + "\n")
            count += 1
    return {"paper_manifest_path": "inputs/paper_cache/manifest.jsonl", "papers": count,
            "content": "External paper identifiers, metadata and saved scientific text"}


def prepare(task_path, genes_path, gene_field, annotations_path, ontology_path, output, model, reasoning_effort, timeout,
            paper_cache=None, include_research_skills=True):
    source = Path(__file__).resolve().parent
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("Use a new private run directory")
    task = json.loads(Path(task_path).read_text())
    if adaptive(task) and not include_research_skills:
        raise ValueError("Planner-adaptive reading uses the packaged add-go-knowledge skill")
    if task.keys() - TASK_FIELDS:
        raise ValueError("Task card contains fields outside the scientific input contract")
    required = TASK_FIELDS - {"source_candidates"}
    if required - task.keys():
        raise ValueError("Task card is missing required task fields")
    if task["biological_context"].keys() - CONTEXT_FIELDS:
        raise ValueError("Biological context contains non-task metadata")
    if not task["candidate_categories"] or not task["knowledge_requirements"]:
        raise ValueError("Declare the task's knowledge requirements")
    data = json.loads(Path(genes_path).read_text())
    genes = data[gene_field] if isinstance(data, dict) else data
    if not genes or any(not isinstance(g, str) or not g for g in genes) or len(genes) != len(set(genes)):
        raise ValueError("Expected a unique fixed gene universe")
    if Path(annotations_path).suffix == ".pkl":
        # The caller supplies a trusted local biological annotation snapshot.
        with Path(annotations_path).open("rb") as stream:
            base = pickle.load(stream)
    else:
        base = json.loads(Path(annotations_path).read_text())
    annotations = {g: sorted(set(base.get(g, []))) for g in genes}
    output.mkdir(parents=True)
    workspace = output / "workspace"
    (workspace / "inputs").mkdir(parents=True)
    excluded = ["__pycache__", "tests"] + ([] if include_research_skills else ["skills"])
    shutil.copytree(source, workspace / "pipeline", ignore=shutil.ignore_patterns(*excluded))
    write_json(workspace / "inputs/genes.json", {"genes": genes})
    write_json(workspace / "inputs/annotations.json", annotations)
    if ontology_path:
        shutil.copyfile(ontology_path, workspace / "inputs/go.obo")
    if paper_cache:
        task["source_cache"] = import_paper_cache(paper_cache, workspace)
    task["scope"] = {"unit": "task", "gene_universe_path": "inputs/genes.json", "gene_field": "genes",
                     "gene_count": len(genes), "screening_policy": "One shared overlay across all task instances and all declared genes"}
    task["compilation"] = {"baseline_annotations_path": "inputs/annotations.json",
                           "ontology_path": "inputs/go.obo" if ontology_path else None,
                           "allowed_relations": sorted(RELATIONS),
                           "allowed_evidence_classes": ["database_derived", "literature_extracted", "analysis_inferred"],
                           "projection": {"adapter": "gene_attributes", **task.pop("projection_policy")}}
    task["initial_knowledge_summary"] = {"genes": len(genes), "gene_annotation_memberships": sum(map(len, annotations.values())),
                                         "distinct_terms": len(set().union(*(set(v) for v in annotations.values())))}
    write_json(workspace / "task.json", task)
    write_json(workspace / "runtime.json", {"model": model, "reasoning_effort": reasoning_effort, "stage_timeout_seconds": timeout})
    write_json(workspace / "inputs/manifest.json", {
        "input_types": ["task_definition", "gene_identifiers", "original_functional_annotations", "ontology"]
                       + (["external_paper_cache"] if paper_cache else []),
        "files": [{"path": str(p.relative_to(workspace)), "sha256": sha256(p)}
                  for p in sorted((workspace / "inputs").rglob("*")) if p.is_file()],
        "task_sha256": sha256(workspace / "task.json"),
    })
    (output / "private_home/.codex").mkdir(parents=True)
    write_json(output / "receipt.json", {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                                         "workspace": str(workspace), "task_source_sha256": sha256(task_path),
                                         "research_skills_included": include_research_skills,
                                         "skill_files": [{"path": str(p.relative_to(workspace)), "sha256": sha256(p)}
                                                         for p in sorted((workspace / "pipeline/skills").rglob("*")) if p.is_file()],
                                         "prompt_files": [{"path": str(p.relative_to(workspace)), "sha256": sha256(p)}
                                                          for p in sorted((workspace / "pipeline/prompts").glob("*.md"))],
                                         "boundary": "Only workspace, clean runtime home, system libraries and Codex executable are mounted"})
    return workspace


def sandbox_command(output, codex_bin, auth_file, entrypoint="run.py"):
    if entrypoint not in {"run.py", "place_modules.py"}:
        raise ValueError("Unknown task-only entrypoint")
    output = Path(output).resolve()
    home_path = Path.home()
    args = ["bwrap", "--unshare-user", "--unshare-pid", "--unshare-uts", "--unshare-ipc", "--new-session",
            "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64",
            "--symlink", "usr/bin", "/bin", "--ro-bind", "/etc", "/etc", "--proc", "/proc", "--dev", "/dev",
            "--tmpfs", "/tmp", "--dir", "/home", "--bind", str(output / "private_home"), str(home_path),
            "--bind", str(output / "workspace"), "/workspace", "--dir", "/opt",
            "--ro-bind", str(Path(codex_bin).resolve()), "/opt/codex"]
    # resolv.conf can point outside /etc on systemd hosts; expose only its
    # resolved file rather than mounting the host's runtime directories.
    resolver = Path("/etc/resolv.conf").resolve()
    if not resolver.is_relative_to(Path("/etc")):
        args += ["--ro-bind", str(resolver), str(resolver)]
    backend_directory = Path(codex_bin).resolve().parent
    for helper in ("codex-code-mode-host", "codex-resources", "codex-package.json", "codex-path", "rg"):
        path = backend_directory / helper
        if path.exists():
            args += ["--ro-bind", str(path), "/opt/" + helper]
    auth_root = Path(os.environ.get("CODEX_HOME", home_path / ".codex"))
    if auth_root != home_path / ".codex":
        args += ["--bind", str(output / "private_home/.codex"), str(auth_root)]
    if entrypoint == "place_modules.py":
        args += ["--ro-bind", str(output / "workspace/inputs"), "/workspace/inputs",
                 "--ro-bind", str(output / "workspace/pipeline"), "/workspace/pipeline",
                 "--symlink", "/usr/bin/python3", "/opt/python",
                 "--setenv", "PATH", "/opt:/usr/local/bin:/usr/bin:/bin"]
    args += ["--ro-bind", str(Path(auth_file).resolve()), str(auth_root / "auth.json"),
             "--chdir", "/workspace", "--", "/usr/bin/python3", "/workspace/pipeline/" + entrypoint, "--workspace", "/workspace"]
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--genes", type=Path, required=True)
    parser.add_argument("--gene-field", default="genes")
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--ontology", type=Path)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--codex-bin", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--stage-timeout-seconds", type=int, default=1800)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--paper-cache-workspace", type=Path)
    parser.add_argument("--without-research-skills", action="store_true",
                        help="Package the current prompts with the research-skills directory excluded")
    parser.add_argument("--retrieval-rounds", type=int, default=None)
    parser.add_argument("--papers-per-round", type=int, default=50)
    parser.add_argument("--full-texts-per-round", type=int, default=30)
    parser.add_argument("--stalled-round-limit", type=int, default=3)
    args = parser.parse_args()
    task_preview = json.loads(args.task.read_text())
    if args.retrieval_rounds is None:
        args.retrieval_rounds = 60 if adaptive(task_preview) else 1
    if args.without_research_skills and adaptive(task_preview):
        parser.error("Planner-adaptive acquisition uses the add-go-knowledge skill; include research skills")
    if min(args.retrieval_rounds, args.papers_per_round, args.full_texts_per_round, args.stalled_round_limit) < 1:
        parser.error("Round limits and reading targets must be positive")
    workspace = prepare(args.task, args.genes, args.gene_field, args.annotations, args.ontology,
                        args.run_dir, args.model, args.reasoning_effort, args.stage_timeout_seconds,
                        args.paper_cache_workspace, not args.without_research_skills)
    runtime = json.loads((workspace / "runtime.json").read_text())
    runtime.update(retrieval_rounds=args.retrieval_rounds, papers_per_round=args.papers_per_round,
                   full_texts_per_round=args.full_texts_per_round, stalled_round_limit=args.stalled_round_limit)
    write_json(workspace / "runtime.json", runtime)
    if args.prepare_only:
        print(json.dumps({"workspace": str(workspace), "status": "prepared"}))
        return
    auth_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    auth_file = auth_root / "auth.json"
    if not auth_file.is_file() or not shutil.which("bwrap"):
        raise RuntimeError("The isolated Codex backend requires bubblewrap and an existing local login")
    environment = os.environ.copy()
    # Remove project-specific discovery hooks without changing HOME/CODEX_HOME.
    for name in ("PYTHONPATH", "VIRTUAL_ENV", "PWD", "OLDPWD", "GIT_DIR", "GIT_WORK_TREE"):
        environment.pop(name, None)
    environment.update(CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")
    command = sandbox_command(args.run_dir, args.codex_bin, auth_file)
    with (args.run_dir / "pipeline.log").open("w") as log:
        child = subprocess.Popen(command, cwd=args.run_dir, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    result = {"pid": child.pid, "workspace": str(workspace), "log": str(args.run_dir / "pipeline.log"), "detached": True}
    write_json(args.run_dir / "launch.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
