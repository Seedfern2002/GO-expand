"""Check startup against an allocator whose statistics are initialized lazily."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


class CUDAStartupTests(unittest.TestCase):
    def test_first_allocation_precedes_memory_stat_reset(self):
        path = Path(__file__).resolve().parents[1] / "scripts/run_gears_baseline.py"
        spec = importlib.util.spec_from_file_location("baseline_startup", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        state = {"allocated": False, "synchronized": False, "reset": False}

        def ones(count, device):
            self.assertEqual((count, device), (8, "cuda:0"))
            state["allocated"] = True
            return SimpleNamespace(sum=lambda: SimpleNamespace(item=lambda: 8))

        def synchronize(device):
            self.assertTrue(state["allocated"])
            state["synchronized"] = True

        def reset(device):
            if not state["allocated"]:
                raise RuntimeError("Invalid device argument")
            self.assertTrue(state["synchronized"])
            state["reset"] = True

        torch = SimpleNamespace(ones=ones, cuda=SimpleNamespace(synchronize=synchronize, reset_peak_memory_stats=reset))
        module.initialize_cuda_telemetry(torch, "cuda:0")
        self.assertTrue(state["reset"])


if __name__ == "__main__":
    unittest.main()
