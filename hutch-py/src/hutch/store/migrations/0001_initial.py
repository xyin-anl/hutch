"""Initial DuckDB schema (M1).

Creates a raw ``events`` log plus denormalized snapshot tables for the
event kinds the M3 UI views read from. Additional snapshot tables can be
added in later migrations as views come online.
"""

from __future__ import annotations

from hutch.store.database import DuckConn

VERSION = 1

CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        VARCHAR PRIMARY KEY,
    name          VARCHAR,
    project       VARCHAR,
    started_at_ns BIGINT,
    ended_at_ns   BIGINT,
    status        VARCHAR
);
"""

CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    event_id     UUID PRIMARY KEY,
    event_kind   VARCHAR NOT NULL,
    run_id       VARCHAR NOT NULL,
    timestamp_ns BIGINT  NOT NULL,
    stream_id    VARCHAR,
    worker_id    VARCHAR,
    span_id      VARCHAR,
    trace_id     VARCHAR,
    payload      JSON    NOT NULL
);
"""

CREATE_EVENTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS events_run_idx ON events (run_id, timestamp_ns);",
    "CREATE INDEX IF NOT EXISTS events_kind_idx ON events (event_kind);",
]

CREATE_INDIVIDUALS = """
CREATE TABLE IF NOT EXISTS individuals (
    run_id           VARCHAR NOT NULL,
    individual_id    VARCHAR NOT NULL,
    kind             VARCHAR NOT NULL,
    parent_ids       VARCHAR[],
    is_seed          BOOLEAN,
    genome_uri       VARCHAR,
    genome_hash      VARCHAR,
    population_id    VARCHAR,
    island_id        VARCHAR,
    generation_index INTEGER,
    timestamp_ns     BIGINT  NOT NULL,
    PRIMARY KEY (run_id, individual_id)
);
"""

CREATE_FITNESS = """
CREATE TABLE IF NOT EXISTS fitness (
    run_id          VARCHAR NOT NULL,
    individual_id   VARCHAR NOT NULL,
    evaluator_kind  VARCHAR NOT NULL,
    scores          JSON,
    composite       DOUBLE,
    cascade_stage   INTEGER,
    is_pareto_front BOOLEAN,
    invalid_reason  VARCHAR,
    timestamp_ns    BIGINT  NOT NULL
);
"""

CREATE_FITNESS_INDEX = (
    "CREATE INDEX IF NOT EXISTS fitness_lookup_idx "
    "ON fitness (run_id, individual_id, timestamp_ns);"
)

CREATE_OPERATORS = """
CREATE TABLE IF NOT EXISTS operators (
    run_id       VARCHAR NOT NULL,
    operator_id  VARCHAR NOT NULL,
    kind         VARCHAR NOT NULL,
    parent_ids   VARCHAR[],
    child_id     VARCHAR NOT NULL,
    llm_id       VARCHAR,
    cost_usd     DOUBLE,
    tokens_in    INTEGER,
    tokens_out   INTEGER,
    timestamp_ns BIGINT  NOT NULL,
    PRIMARY KEY (run_id, operator_id)
);
"""

CREATE_DESCRIPTORS = """
CREATE TABLE IF NOT EXISTS descriptors (
    run_id        VARCHAR NOT NULL,
    individual_id VARCHAR NOT NULL,
    archive_id    VARCHAR NOT NULL,
    kind          VARCHAR NOT NULL,
    coordinates   DOUBLE[],
    cell_id       VARCHAR,
    is_replaced   BOOLEAN,
    timestamp_ns  BIGINT  NOT NULL
);
"""


def up(conn: DuckConn) -> None:
    """Apply migration 0001."""
    conn.execute(CREATE_RUNS)
    conn.execute(CREATE_EVENTS)
    for stmt in CREATE_EVENTS_INDEXES:
        conn.execute(stmt)
    conn.execute(CREATE_INDIVIDUALS)
    conn.execute(CREATE_FITNESS)
    conn.execute(CREATE_FITNESS_INDEX)
    conn.execute(CREATE_OPERATORS)
    conn.execute(CREATE_DESCRIPTORS)
