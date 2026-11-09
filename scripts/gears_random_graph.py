"""Sample directed graph endpoints with matched incoming degrees and weights."""

from collections import Counter
import math
import random


def randomize_go_graph(edges, weights, gene_count, seed=0):
    edges = [tuple(map(int, edge)) for edge in edges]
    weights = [float(value) for value in weights]
    if len(edges) != len(weights) or len(edges) != len(set(edges)):
        raise ValueError("Expected unique directed edges and one weight per edge")
    if any(not 0 <= index < gene_count for edge in edges for index in edge):
        raise ValueError("Graph endpoint outside the gene universe")
    if any(not math.isfinite(value) or value <= 0 for value in weights):
        raise ValueError("Expected finite positive edge weights")
    rng = random.Random(seed)
    loops = {source: weight for (source, target), weight in zip(edges, weights) if source == target}
    counts = Counter(target for source, target in edges if source != target)
    nonself_weights = [weight for (source, target), weight in zip(edges, weights) if source != target]
    rng.shuffle(nonself_weights)
    result, values = [], []
    cursor = 0
    for target in range(gene_count):
        if target in loops:
            result.append((target, target))
            values.append(loops[target])
        for draw in rng.sample(range(gene_count - 1), counts[target]):
            source = draw + (draw >= target)
            result.append((source, target))
            values.append(nonself_weights[cursor])
            cursor += 1
    return result, values
