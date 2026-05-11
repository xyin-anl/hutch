"""Regenerate the docs/assets/screenshots/ dashboard screenshots.

Captures the six light-mode dashboard views embedded in the docs
(`docs/index.md`, `docs/distribution.md`, `docs/concepts.md`) at
1440×900 with a 2× device scale factor, using Playwright's headless
Chromium against a running hutch daemon.

Usage
-----

1. Start a daemon on a scratch DuckDB and populate it with the standard
   examples (whose run names this script relies on):

   ```bash
   rm -f /tmp/hutch-screens.duckdb
   hutch serve --db /tmp/hutch-screens.duckdb --port 7780 &
   export HUTCH_DAEMON_URL=http://127.0.0.1:7780
   python examples/02-openevolve-circle-packing/run_synthetic.py
   python examples/04-dgm-self-improvement/run_synthetic.py
   python examples/05-map-elites-toy/run.py
   python examples/06-evolutionary-operators/run.py
   ```

2. Run this script (Playwright is installed on the fly):

   ```bash
   HUTCH_URL=http://127.0.0.1:7780 \\
     uvx --with playwright python scripts/regen-screenshots.py
   ```

The script resolves the actual run_ids by matching a substring against
each run's ``name`` and ``run_id`` returned by ``GET /runs``, so the
hashes that the SDK assigns to auto-named runs do not need to be
hard-coded here.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

BASE = os.environ.get("HUTCH_URL", "http://127.0.0.1:7780").rstrip("/")
OUT = Path(__file__).resolve().parent.parent / "docs" / "assets" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def _runs() -> list[dict]:
    with urllib.request.urlopen(f"{BASE}/runs", timeout=10) as resp:  # noqa: S310
        return json.load(resp)


def _find_run(needle: str) -> str:
    needle = needle.lower()
    for r in _runs():
        haystack = f"{r.get('name', '')}::{r['run_id']}".lower()
        if needle in haystack:
            return r["run_id"]
    raise SystemExit(
        f"no run found matching {needle!r} in {BASE}/runs; "
        "populate the daemon with the standard examples first"
    )


# (filename, optional run-name substring, optional tab label)
SHOTS: list[tuple[str, str | None, str | None]] = [
    ("runs-list.png",          None,                 None),       # homepage
    ("run-overview.png",       "circle_packing",     "Overview"),
    ("run-phylogeny.png",      "circle_packing",     "Phylogeny"),
    ("run-archive.png",        "me-toy",             "Archive"),  # MAP-Elites toy
    ("run-operator-trace.png", "evo-multi-operator", "Operator-trace"),
    ("run-objectives.png",     "circle_packing",     "Objectives"),
]


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                color_scheme="light",
                device_scale_factor=2,
            )
            page = await context.new_page()
            for name, match, tab in SHOTS:
                url = f"{BASE}/" if match is None else f"{BASE}/run/?id={_find_run(match)}"
                await page.goto(url)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    pass
                if tab is not None:
                    locator = page.get_by_role("button", name=tab, exact=True)
                    try:
                        await locator.click(timeout=4_000)
                    except Exception:
                        await page.locator(f'button:has-text("{tab}")').first.click(timeout=4_000)
                    # Give charts and async data fetches time to settle.
                    await page.wait_for_timeout(1_500)
                target = OUT / name
                await page.screenshot(path=str(target), full_page=False)
                print(f"  wrote {target.name}  ({target.stat().st_size // 1024} KB)")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
