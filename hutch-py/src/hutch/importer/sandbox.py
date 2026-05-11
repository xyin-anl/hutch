"""Constrained execution for LLM-generated adapter code.

The importer runs untrusted Python in a subprocess with a stripped
environment. This is defense-in-depth, not a kernel sandbox: for untrusted
datasets, prefer running Hutch inside a container or VM with no host
secrets mounted. The runner rejects imports and obvious dangerous
builtins, uses a small builtin allowlist, has no shell, has a limited
timeout, and captures I/O.

Generated adapters define::

    def to_canonical(record: dict) -> list[dict]: ...

The runner reads a JSON list of records on stdin, calls ``to_canonical``
on each, and prints a JSON-encoded ``list[list[dict]]`` (one event list
per input record).
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

DEFAULT_TIMEOUT_S = 30.0
RUNNER = """
import ast
import json
import sys
import traceback

FORBIDDEN_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
    ast.Delete,
)
FORBIDDEN_NAMES = {
    "__builtins__",
    "__import__",
    "breakpoint",
    "compile",
    "delattr",
    "eval",
    "exec",
    "getattr",
    "globals",
    "help",
    "input",
    "locals",
    "open",
    "setattr",
    "vars",
}
SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "Exception": Exception,
    "KeyError": KeyError,
    "TypeError": TypeError,
    "ValueError": ValueError,
}


def validate_adapter_code(code):
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, FORBIDDEN_NODES):
            raise ValueError(f"forbidden syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise ValueError(f"forbidden name: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError(f"forbidden dunder attribute: {node.attr}")


ADAPTER_CODE = sys.stdin.readline()
ADAPTER_CODE = json.loads(ADAPTER_CODE)
records = json.loads(sys.stdin.read())

ns = {"__builtins__": SAFE_BUILTINS}
try:
    validate_adapter_code(ADAPTER_CODE)
    exec(ADAPTER_CODE, ns)
except Exception:
    print(json.dumps({"error": traceback.format_exc(), "results": []}))
    sys.exit(0)

to_canonical = ns.get("to_canonical")
if not callable(to_canonical):
    print(json.dumps({"error": "to_canonical not defined", "results": []}))
    sys.exit(0)

results = []
for rec in records:
    try:
        events = to_canonical(rec)
        if events is None:
            events = []
        if isinstance(events, dict):
            events = [events]
        # Normalize iterators to a list for json.dumps below.
        results.append(list(events))
    except Exception:
        results.append({"_error": traceback.format_exc()})
print(json.dumps({"error": None, "results": results}))
"""


def execute_adapter(
    adapter_code: str,
    records: list[dict[str, Any]],
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Run *adapter_code* against *records* in a subprocess.

    Returns ``{"error": str | None, "results": [...]}``. ``results`` is one
    element per input record: either a list of canonical-event dicts, or a
    ``{"_error": <traceback>}`` marker if that record raised.
    """
    payload = json.dumps(adapter_code) + "\n" + json.dumps(records)
    proc = subprocess.run(  # noqa: S603 — running our own python with a stripped env
        [sys.executable, "-c", RUNNER],
        input=payload.encode("utf-8"),
        env={"PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"},
        timeout=timeout_s,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return {
            "error": f"runner exited {proc.returncode}: {proc.stderr.decode(errors='replace')}",
            "results": [],
        }
    try:
        parsed = json.loads(proc.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return {"error": f"runner produced unparseable output: {exc}", "results": []}
    if not isinstance(parsed, dict):
        return {"error": "runner returned non-object JSON", "results": []}
    return parsed
