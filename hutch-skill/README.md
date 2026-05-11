# hutch-skill

The distributable Hutch skill for LLM-driven autoresearch agents.

The canonical instruction file is `SKILL.md`. Drop it into your agent's
instruction surface — `.claude/skills/hutch/`, system prompt, custom GPT
instructions, Cursor rules, etc.

Worked examples live in `examples/`. Real-LLM regression tests live in
`hutch-py/tests/test_skill_eval.py` and are gated on `OPENAI_API_KEY` +
the optional `[skill-eval]` extra.
