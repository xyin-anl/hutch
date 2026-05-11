"""Synthetic CVEvolve session for adapter tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def make_session(target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    history_dir = target_dir / "history"
    workspace_dir = target_dir / "workspace"
    code_dir = workspace_dir / "worker_0" / "candidates"
    history_dir.mkdir(parents=True, exist_ok=True)
    code_dir.mkdir(parents=True, exist_ok=True)

    (target_dir / "config.snapshot.yaml").write_text(
        "\n".join(
            [
                "name: cvevolve-toy",
                "model:",
                "  model_name: gpt-4.1",
                "  temperature: 0.2",
                "workspace:",
                "  root_dir: /tmp/cvevolve",
                "metric:",
                "  name_hint: registration_error",
                "  direction_hint: minimize",
            ]
        ),
        encoding="utf-8",
    )

    candidate_specs = [
        ("cand-baseline", 0, "baseline", [], "seed implementation", {}),
        ("cand-generate", 1, "generate", [], "fresh proposal", {}),
        ("cand-tune", 2, "tune", ["cand-generate"], "parameter tuning", {}),
        (
            "cand-mut",
            3,
            "evolve",
            ["cand-tune"],
            "mutation from tuned candidate",
            {"evolve_strategy": "mutation"},
        ),
        (
            "cand-cross",
            4,
            "evolve",
            ["cand-tune", "cand-mut"],
            "crossover of tuned and mutated candidates",
            {"evolve_strategy": "crossover"},
        ),
    ]

    for candidate_id, round_index, _, _, description, _ in candidate_specs:
        path = code_dir / f"{candidate_id}.py"
        path.write_text(
            f'"""Synthetic CVEvolve candidate {candidate_id}."""\n\n'
            f"def solve():\n    return {round_index!r}, {description!r}\n",
            encoding="utf-8",
        )

    db_path = history_dir / "search_history.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE metric_definitions (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                direction TEXT NOT NULL,
                is_primary INTEGER NOT NULL DEFAULT 0,
                created_at TEXT
            );
            CREATE TABLE rounds (
                round_index INTEGER PRIMARY KEY,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE candidates (
                candidate_id TEXT PRIMARY KEY,
                round_index INTEGER,
                action TEXT,
                candidate_name TEXT,
                description TEXT,
                code_path TEXT,
                code_file_path TEXT,
                lineage_id TEXT,
                lineage_parent_ids_json TEXT,
                parent_ids_json TEXT,
                notes TEXT,
                metadata_json TEXT,
                created_at TEXT
            );
            CREATE TABLE metrics (
                id INTEGER PRIMARY KEY,
                candidate_id TEXT,
                round_index INTEGER,
                metric_name TEXT,
                value REAL,
                is_primary INTEGER,
                notes TEXT,
                settings_json TEXT,
                created_at TEXT
            );
            CREATE TABLE evaluation_metrics (
                id INTEGER PRIMARY KEY,
                candidate_id TEXT,
                metric_name TEXT,
                value REAL,
                created_at TEXT
            );
            CREATE TABLE session_state (
                singleton_id INTEGER PRIMARY KEY,
                phase TEXT,
                status TEXT,
                current_round_index INTEGER,
                current_action TEXT,
                current_reason TEXT,
                preparation_summary TEXT,
                stop_reason TEXT,
                updated_at TEXT
            );
            CREATE TABLE holdout_test_metrics (
                id INTEGER PRIMARY KEY,
                candidate_id TEXT,
                round_index INTEGER,
                metric_name TEXT,
                value REAL,
                notes TEXT,
                settings_json TEXT,
                created_at TEXT
            );
            CREATE TABLE candidate_failures (
                id INTEGER PRIMARY KEY,
                round_index INTEGER,
                action TEXT,
                candidate_name TEXT,
                code_file_path TEXT,
                parent_ids_json TEXT,
                error_message TEXT,
                notes TEXT,
                settings_json TEXT,
                metadata_json TEXT,
                created_at TEXT
            );
            """
        )

        conn.executemany(
            """
            INSERT INTO metric_definitions
                (id, name, direction, is_primary, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (1, "registration_error", "minimize", 1, _ts(0)),
                (2, "accuracy", "maximize", 0, _ts(0)),
            ],
        )
        conn.executemany(
            """
            INSERT INTO rounds
                (round_index, status, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            [(idx, "completed", _ts(idx), _ts(idx, 20)) for idx in range(5)],
        )

        for candidate_id, round_index, action, parents, description, extra_meta in candidate_specs:
            metadata = {
                "settings": {"temperature": 0.2 + round_index / 10},
                "analysis": {"summary": f"{candidate_id} summary"},
                **extra_meta,
            }
            rel_code = f"worker_0/candidates/{candidate_id}.py"
            conn.execute(
                """
                INSERT INTO candidates (
                    candidate_id,
                    round_index,
                    action,
                    candidate_name,
                    description,
                    code_path,
                    code_file_path,
                    lineage_id,
                    lineage_parent_ids_json,
                    parent_ids_json,
                    notes,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    round_index,
                    action,
                    f"Candidate {round_index}",
                    description,
                    rel_code,
                    rel_code,
                    f"lineage-{candidate_id}",
                    json.dumps(parents),
                    json.dumps(parents),
                    f"notes for {candidate_id}",
                    json.dumps(metadata),
                    _ts(round_index, 1),
                ),
            )

        primary_scores = {
            "cand-baseline": 0.42,
            "cand-generate": 0.31,
            "cand-tune": 0.24,
            "cand-mut": 0.2,
            "cand-cross": 0.17,
        }
        metric_rows = [
            (
                idx,
                candidate_id,
                idx - 1,
                "registration_error",
                score,
                1,
                "primary metric",
                json.dumps({"split": "validation"}),
                _ts(idx - 1, 5),
            )
            for idx, (candidate_id, score) in enumerate(primary_scores.items(), start=1)
        ]
        metric_rows.append(
            (
                6,
                "cand-cross",
                4,
                "accuracy",
                0.91,
                0,
                "secondary metric",
                json.dumps({"split": "validation"}),
                _ts(4, 6),
            )
        )
        conn.executemany(
            """
            INSERT INTO metrics (
                id,
                candidate_id,
                round_index,
                metric_name,
                value,
                is_primary,
                notes,
                settings_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            metric_rows,
        )

        conn.execute(
            """
            INSERT INTO evaluation_metrics
                (id, candidate_id, metric_name, value, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (1, "cand-cross", "registration_error", 0.16, _ts(4, 7)),
        )
        conn.executemany(
            """
            INSERT INTO holdout_test_metrics (
                id,
                candidate_id,
                round_index,
                metric_name,
                value,
                notes,
                settings_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1,
                    "cand-cross",
                    4,
                    "registration_error",
                    0.19,
                    "holdout score",
                    json.dumps({"split": "holdout"}),
                    _ts(5, 1),
                ),
                (
                    2,
                    "cand-mut",
                    3,
                    "registration_error",
                    None,
                    "holdout timed out",
                    json.dumps({"split": "holdout"}),
                    _ts(5, 2),
                ),
            ],
        )
        conn.execute(
            """
            INSERT INTO candidate_failures (
                id,
                round_index,
                action,
                candidate_name,
                code_file_path,
                parent_ids_json,
                error_message,
                notes,
                settings_json,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                5,
                "evolve",
                "Failed candidate",
                "worker_1/candidates/failed.py",
                json.dumps(["cand-cross"]),
                "SyntaxError: invalid syntax",
                "failure notes",
                json.dumps({"temperature": 0.6}),
                json.dumps({"analysis": "failed parse"}),
                _ts(5, 3),
            ),
        )
        conn.execute(
            """
            INSERT INTO session_state (
                singleton_id,
                phase,
                status,
                current_round_index,
                current_action,
                current_reason,
                preparation_summary,
                stop_reason,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "completed",
                "success",
                4,
                "done",
                "",
                "synthetic fixture",
                "max rounds",
                _ts(5, 4),
            ),
        )

    messages_db = history_dir / "messages.sqlite"
    with sqlite3.connect(messages_db) as conn:
        conn.executescript(
            """
            CREATE TABLE message_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                round_index INTEGER,
                worker_index INTEGER NOT NULL DEFAULT 0,
                message_type TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO message_events (
                created_at,
                round_index,
                worker_index,
                message_type,
                content,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    _ts(1, 2),
                    1,
                    0,
                    "system",
                    "You are optimizing the registration error.",
                    json.dumps({"phase": "generate"}),
                ),
                (
                    _ts(4, 8),
                    4,
                    1,
                    "assistant",
                    "Crossover produced a stronger candidate.",
                    json.dumps({"candidate_id": "cand-cross"}),
                ),
            ],
        )

    tool_calls_db = history_dir / "tool_calls.sqlite"
    with sqlite3.connect(tool_calls_db) as conn:
        conn.executescript(
            """
            CREATE TABLE tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO tool_calls (created_at, tool_name, arguments_json)
            VALUES (?, ?, ?)
            """,
            (_ts(2, 8), "submit_candidate", json.dumps({"candidate_name": "Candidate 2"})),
        )

    return target_dir


def _ts(round_index: int, offset: int = 0) -> str:
    minute = round_index * 10 + offset
    return f"2025-01-01T00:{minute:02d}:00+00:00"
