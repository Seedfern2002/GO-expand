"""Preserve GAF records, including negation and evidence, during inspection."""

from dataclasses import dataclass
from .ontology import open_text


@dataclass(frozen=True)
class Annotation:
    object_id: str
    symbol: str
    relation: str
    negated: bool
    term_id: str
    reference: str
    evidence: str
    with_from: str
    aspect: str
    taxon: str
    date: str
    assigned_by: str
    extension: str
    product_form_id: str


def read_gaf(path):
    """Stream GAF 2.2 records; inspect fields without performing full validation.

    IDs retain database prefixes; symbols are display labels, not join keys.
    Legacy GAF 2.1 requires explicit conversion before using this reader.
    """
    version = None
    with open_text(path) as handle:
        for number, raw in enumerate(handle, 1):
            if raw.startswith("!gaf-version:"):
                version = raw.split(":", 1)[1].strip()
                if version != "2.2":
                    raise ValueError(f"GAF {version} is not supported; expected 2.2")
            if raw.startswith("!") or not raw.strip():
                continue
            if version is None:
                raise ValueError("Missing !gaf-version: 2.2 header")
            fields = raw.rstrip("\r\n").split("\t")
            if len(fields) != 17:
                raise ValueError(f"Line {number}: expected 17 GAF fields, got {len(fields)}")
            relation_parts = fields[3].split("|")
            relations = [part for part in relation_parts if part != "NOT"]
            if len(relations) != 1 or not relations[0] or len(relation_parts) != len(set(relation_parts)):
                raise ValueError(f"Line {number}: expected one relation and optional NOT")
            yield Annotation(
                object_id=f"{fields[0]}:{fields[1]}", symbol=fields[2],
                relation=relations[0], negated="NOT" in relation_parts,
                term_id=fields[4], reference=fields[5], evidence=fields[6],
                with_from=fields[7], aspect=fields[8], taxon=fields[12],
                date=fields[13], assigned_by=fields[14], extension=fields[15],
                product_form_id=fields[16],
            )
    if version is None:
        raise ValueError("Missing !gaf-version: 2.2 header")
