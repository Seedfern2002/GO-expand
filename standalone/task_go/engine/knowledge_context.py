"""Task-local concept and assertion lookup, with evidence-preserving proposals."""

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from .knowledge import encoded, read_json, read_records, sha256, workspace_file, assemble, validate_knowledge_review
from .ontology import Ontology, open_text


def normalized(text):
    # Preserve meaningful punctuation, including the distinction between C and C*.
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def evidence_key(evidence):
    return encoded({k: v for k, v in evidence.items() if k not in {"concept_metadata", "concept_resolution"}})


class KnowledgeContext:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row

    def close(self):
        self.db.close()

    def concept(self, identity, label="", definition="", kind="", status="candidate"):
        self.db.execute("INSERT OR IGNORE INTO concepts VALUES(?,?,?,?,?)", (identity, label or identity, definition, kind, status))
        self.db.execute("INSERT OR IGNORE INTO names VALUES(?,?,?)", (identity, normalized(label or identity), label or identity))

    def statement(self, record, status):
        key = encoded([record["subject_label"], record["object_id"], record["relation"], record["polarity"], record["context"]])
        # Distinct contexts, polarities and review states retain independent rows.
        self.db.execute("INSERT INTO assertions VALUES(?,?,?,?,?,?,?,?)", (
            record["subject_label"], record["subject_id"], record["object_id"], record["relation"],
            record["polarity"], encoded(record["context"]), encoded(record.get("evidence", [])), status))
        return key

    @classmethod
    def build(cls, root, path, candidates=None):
        root, path = Path(root), Path(path)
        root, path = root.resolve(), path.resolve()
        if not path.is_relative_to(root):
            raise ValueError("Index must stay inside the task workspace")
        if path.exists():
            raise FileExistsError("Create a fresh knowledge-context snapshot")
        path.parent.mkdir(parents=True, exist_ok=True)
        ctx = cls(path)
        ctx.db.executescript("""
            CREATE TABLE concepts(id TEXT PRIMARY KEY,label TEXT,definition TEXT,kind TEXT,status TEXT);
            CREATE TABLE names(id TEXT,name TEXT,label TEXT,UNIQUE(id,name));
            CREATE INDEX concept_names ON names(name);
            CREATE TABLE edges(source TEXT,relation TEXT,target TEXT);
            CREATE INDEX edge_source ON edges(source);
            CREATE TABLE assertions(gene TEXT,subject_id TEXT,object_id TEXT,relation TEXT,polarity TEXT,context TEXT,evidence TEXT,status TEXT);
            CREATE INDEX gene_assertions ON assertions(gene);
            CREATE INDEX target_assertions ON assertions(object_id);
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
        """)
        task = read_json(root / "task.json")
        policy = task["compilation"]
        sources = []
        ontology_path = policy.get("ontology_path")
        if ontology_path:
            file = workspace_file(root, ontology_path)
            ontology = Ontology.read(file)
            sources.append({"path": ontology_path, "sha256": sha256(file)})
            for term in ontology.terms.values():
                if term.obsolete:
                    continue
                ctx.concept(term.id, term.name, term.definition, term.namespace, "ontology")
                for alias in term.alt_ids:
                    ctx.db.execute("INSERT OR IGNORE INTO names VALUES(?,?,?)", (term.id, normalized(alias), alias))
                ctx.db.executemany("INSERT INTO edges VALUES(?,?,?)", [(term.id, relation, target) for relation, target in term.edges])
            current = None
            with open_text(file) as stream:
                for raw in stream:
                    if raw.startswith("["):
                        current = None
                    if raw.startswith("id: "):
                        current = raw[4:].strip()
                    match = re.match(r'synonym: "(.*)" EXACT ', raw)
                    if match and current in ontology.terms and not ontology.terms[current].obsolete:
                        ctx.db.execute("INSERT OR IGNORE INTO names VALUES(?,?,?)", (current, normalized(match[1]), match[1]))
        file = workspace_file(root, policy["baseline_annotations_path"])
        sources.append({"path": policy["baseline_annotations_path"], "sha256": sha256(file)})
        for gene, attributes in read_json(file).items():
            for attribute in attributes:
                ctx.concept(attribute, status="baseline")
                ctx.statement({"subject_label": gene, "subject_id": "SYMBOL:" + gene, "object_id": attribute,
                               "relation": "annotated_to", "polarity": "positive", "context": {}}, "baseline")
        approved_paths = set()
        review_path = root / "stages/reviewer/result.json"
        candidate_path = root / "stages/retriever/result.json"
        if review_path.exists() and candidate_path.exists():
            approved_paths = set(validate_knowledge_review(task, read_json(candidate_path), read_json(review_path), root))
        active = candidates if candidates is not None else (
            read_json(root / "rounds/active_candidates.json") if (root / "rounds/active_candidates.json").exists() else {"batches": []})
        cache = {}
        for batch in active["batches"]:
            file = workspace_file(root, batch["records_path"])
            if sha256(file) != batch["records_sha256"]:
                raise ValueError("Candidate batch changed before context indexing")
            sources.append({"path": batch["records_path"], "sha256": batch["records_sha256"]})
            state = "reviewed" if file in approved_paths else "candidate"
            for record in read_records(file, task, root, cache):
                metadata = next((e["concept_metadata"] for e in record["evidence"] if "concept_metadata" in e), {})
                ctx.concept(record["object_id"], record["object_label"], metadata.get("definition", ""), metadata.get("kind", ""), state)
                ctx.statement(record, state)
        ctx.db.execute("INSERT INTO metadata VALUES('sources',?)", (encoded(sources),))
        ctx.db.commit()
        return ctx

    def query(self, genes=(), concept_id=None, label=None, limit=30, offset=0):
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("Use a page size from1 to200 and a nonnegative offset")
        result = {"genes": {}, "concepts": [], "match_scope": "Exact IDs, normalized names/EXACT synonyms, and textual candidates; biological equivalence requires review."}
        for gene in genes:
            ids = [gene, "GENE:" + gene] + [r[0] for r in self.db.execute("SELECT DISTINCT subject_id FROM assertions WHERE gene=?", (gene,))]
            marks = ",".join("?" for _ in ids)
            where = f"gene=? OR object_id IN ({marks})"
            count = self.db.execute("SELECT count(*) FROM assertions WHERE " + where, [gene, *ids]).fetchone()[0]
            rows = self.db.execute("SELECT * FROM assertions WHERE " + where + " ORDER BY object_id,relation,status LIMIT ? OFFSET ?", [gene, *ids, limit, offset])
            assertions = []
            for row in rows:
                d = dict(row)
                d["context"], d["evidence"] = json.loads(d["context"]), json.loads(d["evidence"])
                term = self.db.execute("SELECT label,definition,kind FROM concepts WHERE id=?", (d["object_id"],)).fetchone()
                d["concept"] = dict(term) if term else None
                assertions.append(d)
            result["genes"][gene] = {"assertions": assertions, "total": count, "next_offset": offset + limit if count > offset + limit else None}
        if concept_id or label:
            if concept_id:
                rows = self.db.execute("SELECT DISTINCT c.* FROM concepts c LEFT JOIN names n ON c.id=n.id WHERE c.id=? OR n.name=? LIMIT ? OFFSET ?", (concept_id, normalized(concept_id), limit, offset))
            else:
                value = normalized(label)
                rows = self.db.execute("SELECT DISTINCT c.* FROM concepts c JOIN names n ON c.id=n.id WHERE n.name=? OR instr(n.name,?)>0 ORDER BY c.id LIMIT ? OFFSET ?", (value, value, limit, offset))
            for row in rows:
                d = dict(row)
                d["aliases"] = [r[0] for r in self.db.execute("SELECT label FROM names WHERE id=?", (d["id"],))]
                d["ontology_edges"] = [dict(r) for r in self.db.execute("SELECT relation,target FROM edges WHERE source=?", (d["id"],))]
                d["memberships"] = [dict(r) for r in self.db.execute("SELECT DISTINCT gene,relation,polarity,status FROM assertions WHERE object_id=? ORDER BY gene LIMIT ? OFFSET ?", (d["id"], limit, offset))]
                d["membership_count"] = self.db.execute("SELECT count(*) FROM assertions WHERE object_id=?", (d["id"],)).fetchone()[0]
                result["concepts"].append(d)
            result["concept_next_offset"] = offset + limit if len(result["concepts"]) == limit else None
        return result

    def propose(self, root, records_path, output, concepts=(), equivalences=()):
        """Emit a reviewable new acquisition artifact; prior batches stay immutable."""
        root, output = Path(root).resolve(), Path(output).resolve()
        if not output.is_relative_to(root):
            raise ValueError("Proposal output must stay inside the task workspace")
        if output.exists():
            raise FileExistsError("Publish proposals under a fresh directory")
        task = read_json(root / "task.json")
        records = read_records(workspace_file(root, records_path), task, root)
        assemble([], equivalences)  # Validate mapping evidence, namespaces and cycles.
        aliases = {}
        for mapping in equivalences:
            if mapping.get("scope", "concept") != "concept":
                raise ValueError("Only concept-level equivalence can replace an identifier")
            aliases[mapping["alias_id"]] = mapping["canonical_id"]
        def canonical(term):
            while term in aliases:
                term = aliases[term]
            return term
        definitions = {r["id"]: r for r in concepts}
        # Work transactionally: failed proposals leave no indexed partial additions.
        emitted, decisions = [], []
        try:
            self.db.execute("BEGIN")
            for record in records:
                r = dict(record)
                original = r["object_id"]
                r["object_id"] = canonical(original)
                concept = self.db.execute("SELECT * FROM concepts WHERE id=?", (r["object_id"],)).fetchone()
                if not concept:
                    metadata = definitions.get(r["object_id"], {})
                    if not metadata.get("definition", "").strip() or not metadata.get("kind", "").strip():
                        raise ValueError("New concepts require a definition and entity type")
                    matches = {row[0] for row in self.db.execute("SELECT id FROM names WHERE name=?", (normalized(r["object_label"]),))}
                    distinguished = {d["concept_id"] for d in metadata.get("distinct_from", []) if d.get("reason", "").strip()}
                    if matches - distinguished:
                        raise ValueError("Review matching existing concepts before minting a new ID")
                    self.concept(r["object_id"], r["object_label"], metadata["definition"], metadata["kind"])
                    r["evidence"] = [{**e, "concept_metadata": metadata} for e in r["evidence"]]
                else:
                    r["object_label"] = concept["label"]
                if original != r["object_id"]:
                    mapping = {"original_object_id": original, "canonical_id": r["object_id"], "equivalence_evidence": list(equivalences)}
                    r["evidence"] = [{**e, "concept_resolution": mapping} for e in r["evidence"]]
                prior = list(self.db.execute("SELECT * FROM assertions WHERE gene=? AND object_id=?", (r["subject_label"], r["object_id"])))
                exact = [row for row in prior if row["relation"] == r["relation"] and row["polarity"] == r["polarity"] and row["context"] == encoded(r["context"])]
                prior_evidence = {evidence_key(e) for row in exact for e in json.loads(row["evidence"])}
                fresh = []
                for evidence in r["evidence"]:
                    key = evidence_key(evidence)
                    if key not in prior_evidence:
                        fresh.append(evidence)
                        prior_evidence.add(key)
                action = "append_evidence" if exact else "add_contextual_assertion" if prior else "add_association"
                if not concept:
                    action = "propose_concept_and_association"
                if not fresh:
                    action = "already_supported"
                else:
                    r["evidence"] = fresh
                    import hashlib
                    r["id"] = "ADD:" + hashlib.sha256(encoded(r).encode()).hexdigest()[:24]
                    emitted.append(r)
                    self.statement(r, "candidate")
                decisions.append({"input_record_id": record["id"], "gene": r["subject_label"], "object_id": r["object_id"],
                                  "original_object_id": original, "action": action,
                                  "prior_review_states": sorted({row["status"] for row in prior}),
                                  "context": r["context"], "relation": r["relation"], "polarity": r["polarity"]})
            # Validate transformed records through the same ingestion contract.
            output.mkdir(parents=True)
            target = output / "records.jsonl"
            target.write_text("".join(encoded(r) + "\n" for r in emitted))
            read_records(target, task, root)
            (output / "decisions.jsonl").write_text("".join(encoded(d) + "\n" for d in decisions))
            (output / "concepts.json").write_text(encoded(list(concepts)) + "\n")
            (output / "equivalence_proposals.json").write_text(encoded(list(equivalences)) + "\n")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return {"records_path": str(target.relative_to(root)), "records_sha256": sha256(target),
                "records_emitted": len(emitted), "actions": decisions,
                "review_state": "candidate; reviewer approval required before final compilation"}
