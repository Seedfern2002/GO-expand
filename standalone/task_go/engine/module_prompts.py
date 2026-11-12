"""Load role-specific skills and record the exact module-agent instructions."""

import hashlib
import json
from pathlib import Path

from engine.knowledge import sha256


ROLE_INSTRUCTIONS = {
    "editor": ("transaction", "place-functional-modules", "transactions.md"),
    "recipe_editor": ("group_recipe", "place-functional-modules", "group-recipes.md"),
    "reviewer": ("transaction", "review-functional-modules", "transactions.md"),
    "recipe_reviewer": ("group_recipe", "review-functional-modules", "group-reviews.md"),
}


def _instruction_bundle(root, role):
    if role not in ROLE_INSTRUCTIONS:
        raise ValueError("Unknown module agent role")
    root = Path(root).resolve()
    mode, skill, reference = ROLE_INSTRUCTIONS[role]
    entries = [("role_prompt", f"pipeline/prompts/modules/{role}.md"),
               ("skill", f"pipeline/skills/{skill}/SKILL.md"),
               ("shared_semantics", "pipeline/references/knowledge_semantics.md"),
               ("active_interface", f"pipeline/skills/{skill}/references/{reference}")]
    resources, parts = [], []
    for kind, relative in entries:
        path = (root / relative).resolve()
        if not path.is_relative_to(root / "pipeline"):
            raise ValueError("Module instructions must remain in the task pipeline")
        data = path.read_bytes()
        resources.append({"kind": kind, "path": relative, "sha256": hashlib.sha256(data).hexdigest()})
        parts.append(f"Instruction {kind} ({relative}):\n" + data.decode())
    return parts, {"role": role, "interface": mode, "skill": skill, "resources": resources}


def instruction_manifest(root, role):
    return _instruction_bundle(root, role)[1]


def build_module_prompt(root, role, context):
    parts, manifest = _instruction_bundle(root, role)
    parts.insert(0, "The controller supplies the assigned role, skill, shared scientific conventions and active interface below. Their complete contents are embedded for this invocation.")
    parts += ["Scientific task:\n" + (Path(root) / "task.json").read_text(),
              "Current batch context:\n" + json.dumps(context, ensure_ascii=False, separators=(",", ":"))]
    prompt = "\n\n".join(parts)
    manifest["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
    return prompt, manifest


def instruction_receipts(root):
    """Collect verified per-invocation skill receipts for the frozen graph."""
    root = Path(root).resolve()
    invocations = []
    for path in sorted((root / "batches").glob("*/*/instruction_manifest.json")):
        manifest = json.loads(path.read_text())
        expected = instruction_manifest(root, manifest["role"])
        if {k: manifest[k] for k in expected} != expected:
            raise ValueError("Module instruction resources changed during the run")
        execution = json.loads(path.with_name("execution.json").read_text())
        prompt_hash = sha256(path.with_name("prompt.md"))
        if (execution["instruction_manifest_sha256"] != sha256(path)
                or execution["prompt_sha256"] != prompt_hash or manifest["prompt_sha256"] != prompt_hash):
            raise ValueError("Module instruction receipt differs from its executed prompt")
        invocations.append({"directory": str(path.parent.relative_to(root)), **manifest,
                            "instruction_manifest_sha256": sha256(path)})
    if not invocations:
        raise ValueError("Module graph freeze requires executed instruction receipts")
    return {"invocations": invocations}
