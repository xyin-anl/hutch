# Skill tests

Real-LLM regression tests for the Hutch skill live in
`hutch-py/tests/test_skill_eval.py`. The suite is opt-in: it is skipped
unless `OPENAI_API_KEY` is set and the optional `[skill-eval]` extra is
installed (`uv pip install -e ".[skill-eval]"`). Budget per CI run is
capped at ≤ $5; the suite asserts ≥95% schema-validity across three
scenarios (linear-refine, evolutionary-2islands, self-improving).
