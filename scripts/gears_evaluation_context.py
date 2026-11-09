"""Associate evaluation telemetry with the result consumed by GEARS metrics."""


class EvaluationContexts:
    def __init__(self):
        self.pending = {}

    def remember(self, result, phase, epoch, seconds):
        key = id(result)
        if key in self.pending:
            raise ValueError("Evaluation result already registered")
        self.pending[key] = (result, {
            "phase": phase, "epoch": epoch, "evaluation_seconds": seconds,
        })

    def take(self, result):
        stored, metadata = self.pending.pop(id(result))
        if stored is not result:
            raise ValueError("Evaluation result identity changed")
        return metadata
