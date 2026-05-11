# Example 07 — Live steering demo

Demonstrates the **steering write-back channel**.
Issue commands from the UI; the running script obeys them between
iterations.

## What it shows

- `pause_run` / `resume_run` halts/resumes the loop without killing the
  process — the dashboard stays subscribed and individuals stop appearing
  until you resume.
- `cancel_individual <ind_id>` marks a specific Individual `invalid` before
  evaluation. You'll see it in the run's fitness table with
  `invalid_reason="cancelled by steering"`.
- `inject_hint {"text": "..."}` (one-shot): biases the next evaluation
  upward to prove the round-trip is live.
- `fork_from <ind_id>`: rewinds the chain — the next iteration's
  `parent_id` is set to the targeted Individual.

Each command is also persisted as a `steering_command` event in DuckDB,
so the audit trail survives daemon restarts.

## Run it

```bash
# Terminal 1 — daemon
hutch serve --db /tmp/hutch-steering-demo.duckdb

# Terminal 2 — the loop
HUTCH_DAEMON_URL=http://127.0.0.1:7777 python examples/07-steering-demo/run.py
```

Open the Hutch dashboard at <http://127.0.0.1:7777/> and click into the
new run; the **Steering** tab has a form for issuing commands.

For a CLI-only demo:

```bash
RUN_ID=<paste from the loop's stdout>
curl -X POST http://127.0.0.1:7777/steering/$RUN_ID \
     -H 'content-type: application/json' \
     -d '{"command":"pause_run","actor":"human"}'
```
