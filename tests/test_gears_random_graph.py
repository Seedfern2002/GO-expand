"""Check random graph controls against their reference graph invariants."""

from collections import Counter
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/gears_random_graph.py"
spec = importlib.util.spec_from_file_location("random_graph", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RandomGraphTests(unittest.TestCase):
    def setUp(self):
        self.edges = [(0, 0), (1, 0), (2, 0), (1, 1), (3, 1), (4, 1),
                      (2, 2), (0, 2), (1, 2), (3, 3), (0, 3), (2, 3), (4, 4), (1, 4)]
        self.weights = [1.0 if s == t else 0.2 + i / 100 for i, (s, t) in enumerate(self.edges)]

    def test_controls_preserve_edges_incoming_degrees_loops_and_weight_distribution(self):
        edges, weights = module.randomize_go_graph(self.edges, self.weights, 5, seed=0)
        self.assertEqual(len(edges), len(self.edges))
        self.assertEqual(len(set(edges)), len(edges))
        self.assertEqual(Counter(t for s, t in edges), Counter(t for s, t in self.edges))
        self.assertEqual({(s, t) for s, t in edges if s == t}, {(s, t) for s, t in self.edges if s == t})
        self.assertEqual(sorted(weights), sorted(self.weights))
        self.assertNotEqual(set(edges), set(self.edges))
        self.assertEqual((edges, weights), module.randomize_go_graph(self.edges, self.weights, 5, seed=0))
        self.assertNotEqual(edges, module.randomize_go_graph(self.edges, self.weights, 5, seed=1)[0])

    def test_zero_degree_nodes_remain_in_the_fixed_universe(self):
        edges, weights = module.randomize_go_graph([(0, 0)], [1.0], 5)
        self.assertEqual(edges, [(0, 0)])
        self.assertEqual(weights, [1.0])

    def test_duplicate_edges_are_rejected(self):
        with self.assertRaises(ValueError):
            module.randomize_go_graph([(0, 1), (0, 1)], [0.5, 0.6], 5)


if __name__ == "__main__":
    unittest.main()
