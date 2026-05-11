"""Generate a synthetic foreign autoresearch run for testing the LLM-assisted
importer.

The generated layout intentionally doesn't match any of our hand-written
adapters (OpenEvolve / AIDE / DGM), so the LLM has to read the records and
the README to figure out the mapping.
"""

from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from typing import Any


def make_foreign_run(target_dir: Path, *, seed: int = 17, num_trials: int = 16) -> Path:
    rng = random.Random(seed)
    target_dir.mkdir(parents=True, exist_ok=True)
    trials_dir = target_dir / "trials"
    trials_dir.mkdir(exist_ok=True)

    trials: list[dict[str, Any]] = []
    parents: list[str | None] = [None]
    for step in range(num_trials):
        trial_id = f"trial-{step:03d}-{uuid.uuid4().hex[:6]}"
        parent = rng.choice(parents) if step > 0 else None
        score = round(rng.uniform(0.2, 0.95), 4)
        record = {
            "trial_id": trial_id,
            "from_parent": parent,
            "candidate_program": f"# attempt {step}\nresult = {step * 0.1:.2f}",
            "objective_score": score,
            "step": step,
            "mutation_kind": rng.choice(["mutate", "refine", "perturb"]),
            "wall_time_s": round(rng.uniform(0.1, 5.0), 2),
        }
        trials.append(record)
        parents.append(trial_id)

    for trial in trials:
        (trials_dir / f"{trial['trial_id']}.json").write_text(json.dumps(trial, indent=2))

    (target_dir / "README.md").write_text(
        "# my-foreign-run\n\n"
        "This is a synthetic run from the FooBar autoresearch framework.\n\n"
        "Each `trials/<trial_id>.json` is one candidate program produced by\n"
        "the search. Fields:\n\n"
        "- `trial_id`: unique id\n"
        "- `from_parent`: parent's trial_id (null for the seed)\n"
        "- `candidate_program`: the program text\n"
        "- `objective_score`: scalar fitness (higher is better)\n"
        "- `step`: monotonically increasing iteration index\n"
        "- `mutation_kind`: how this trial was produced (`mutate`/`refine`/`perturb`)\n"
        "- `wall_time_s`: wall-clock seconds spent on this trial\n"
    )

    (target_dir / "metadata.json").write_text(
        json.dumps(
            {
                "framework": "FooBar",
                "framework_version": "0.4.2",
                "task": "synthetic-toy-bowl",
                "num_trials": num_trials,
            },
            indent=2,
        )
    )
    return target_dir
