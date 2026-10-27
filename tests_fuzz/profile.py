"""Общие настройки Hypothesis для свойств: число примеров и seed снаружи, чтобы
CI укладывался во время, а падение воспроизводилось (тот же seed → тот же пример)."""
import os

from hypothesis import HealthCheck, settings

EXAMPLES = int(os.environ.get("FUZZ_EXAMPLES", "12"))
SEED = int(os.environ.get("FUZZ_SEED", "20261027"))


def props(examples: int | None = None):
    return settings(
        max_examples=examples or max(EXAMPLES * 5, 50),
        deadline=None,
        database=None,
        suppress_health_check=list(HealthCheck),
    )
