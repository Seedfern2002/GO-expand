"""Illustrate the effect of an annotation overlay on GO-derived similarity."""

from pathlib import Path
from go_enrichment.ontology import Ontology, jaccard

ontology = Ontology.read(Path(__file__).with_name("toy.obo"))
exclude = {"DEMO:0000"}
gene_a = ontology.closure({"DEMO:0001"}, exclude=exclude)
gene_b = ontology.closure({"DEMO:0002"}, exclude=exclude)
augmented_b = ontology.closure({"DEMO:0002", "DEMO:0001"}, exclude=exclude)

print("Synthetic teaching example; no real genes or empirical result.")
print("A terms:", sorted(gene_a))
print("B terms:", sorted(gene_b))
print("B terms after adding a repair annotation:", sorted(augmented_b))
print("Original Jaccard:", jaccard(gene_a, gene_b))
print("Augmented Jaccard:", jaccard(gene_a, augmented_b))
print("regulates was preserved as an edge, but not used for positive annotation closure.")
