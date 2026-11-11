"""Planner-directed, abstract-first reading within task resource ceilings."""

ADAPTIVE = "planner_adaptive"
BODY_REASONS = {"missing_context", "relationship_ambiguity", "entity_identity",
                "complex_composition", "large_scale_screen", "functional_atlas",
                "supplementary_table", "conflicting_evidence"}

READING_PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "initial_papers": {"type": "integer", "minimum": 1},
        "batch_size": {"type": "integer", "minimum": 1},
        "max_full_text_papers": {"type": "integer", "minimum": 0},
        "topic_questions": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "stop_criteria": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    },
    "required": ["initial_papers", "batch_size", "max_full_text_papers", "topic_questions", "stop_criteria"],
}
READING_DECISION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "decision": {"type": "string", "enum": ["continue", "stop"]},
        "reason": {"type": "string", "minLength": 1},
        "stop_code": {"type": "string", "enum": ["continue", "coverage_sufficient", "candidate_pool_exhausted"]},
        "next_batch_size": {"type": "integer", "minimum": 0},
        "unresolved_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision", "reason", "stop_code", "next_batch_size", "unresolved_questions"],
}


def adaptive(task):
    return task["retrieval_budget"].get("reading_mode") == ADAPTIVE


def validate_reading_plan(task, plan):
    if not adaptive(task):
        return
    p = plan.get("reading_plan")
    if not p:
        raise ValueError("Adaptive reading requires a Planner reading_plan")
    budget = task["retrieval_budget"]
    for field, low, high in [
        ("initial_papers", 1, budget["max_papers"]),
        ("batch_size", 1, budget.get("max_papers_per_round", 50)),
        ("max_full_text_papers", 0, min(budget["max_papers"], budget.get("max_full_text_papers", budget["max_papers"]))),
    ]:
        value = p.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError("Planner reading budget outside task ceiling: " + field)
    for field in ("topic_questions", "stop_criteria"):
        values = p.get(field)
        if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError("Reading plan needs biological questions and stopping criteria")


def round_reading_input(task, plan, runtime, progress, previous_decision=None):
    if not adaptive(task):
        return {"new_papers_target": runtime.get("papers_per_round", 50),
                "full_text_inspections_target": runtime.get("full_texts_per_round", 30)}
    p, budget = plan["reading_plan"], task["retrieval_budget"]
    requested = (previous_decision or {}).get("next_batch_size", p["batch_size"])
    remaining = max(0, budget["max_papers"] - progress.get("paper_identities_opened", 0))
    return {
        "reading_mode": ADAPTIVE,
        "new_papers_target": min(requested, p["batch_size"], runtime.get("papers_per_round", 50), remaining),
        "full_text_inspections_target": 0,
        "full_text_budget_remaining": max(0, p["max_full_text_papers"] - progress.get("full_text_inspected_primary", 0)),
        "initial_papers": p["initial_papers"], "topic_questions": p["topic_questions"],
        "stop_criteria": p["stop_criteria"],
    }


def validate_reading_decision(task, plan, result, observations, progress):
    if not adaptive(task):
        return None
    d = result.get("reading_decision", {})
    if not d.get("reason", "").strip():
        raise ValueError("Reading decision requires an evidence-based reason")
    if d.get("decision") not in {"continue", "stop"}:
        raise ValueError("Declare whether reading continues or stops")
    if d["decision"] == "continue":
        if d.get("stop_code") != "continue" or not 1 <= d.get("next_batch_size", 0) <= plan["reading_plan"]["batch_size"]:
            raise ValueError("Continuation needs a bounded next batch")
    else:
        if d.get("next_batch_size") != 0 or d.get("stop_code") not in {"coverage_sufficient", "candidate_pool_exhausted"}:
            raise ValueError("Stopping needs an explicit code and zero next batch")
        if d["stop_code"] == "coverage_sufficient" and (
            progress["inspected_primary"] < plan["reading_plan"]["initial_papers"] or d.get("unresolved_questions")
        ):
            raise ValueError("Coverage stop requires initial reading and resolved questions")
    if progress["full_text_inspected_primary"] > plan["reading_plan"]["max_full_text_papers"]:
        raise ValueError("Planner full-text ceiling exceeded")
    for row in observations:
        if row["inspection_level"] != "full_text":
            continue
        need = row.get("body_reading_request", {})
        if need.get("reason_code") not in BODY_REASONS or not need.get("question", "").strip():
            raise ValueError("Body reading requires a concrete information need")
        if not need.get("abstract_assessment", "").strip():
            raise ValueError("Body reading requires an abstract assessment")
    return d
