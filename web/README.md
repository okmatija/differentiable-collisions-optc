# Optimization log browser

A static, dependency-free web page for browsing the optimization history in
`src-optimized/OPTIMIZATION-LOG.md`:

- **Speedup-over-iterations line chart** — x = entry index, y = speedup (×) or
  optimized runtime (ms). Kept changes are green, rejected experiments red,
  milestones blue diamonds. The 50× and 100× targets are drawn as guide lines.
- **Hover** over the plot / x-axis to move the solid cursor line and update the
  graph tooltip. **Click** a point (or a list row) to pin its full markdown text
  below the graph; a dotted vertical line marks the pinned entry and the text
  stays until the next click.
- **Searchable, filterable entry list** (All / Kept / Rejected / Milestones).
- **Extras**: hypothesis batting-average donut (kept vs rejected), recorded
  per-entry token cost, and links to the 3D pair visualizer, README, paper, and
  raw log.

## Run

```bash
# from this web/ folder
python3 build.py                       # optional: regenerate data.json from the log

# serve the REPO ROOT (one level up) so the "explore the repo" links
# (../viz, ../README.md, ../documents) resolve — the page lives at /web/
cd .. && python3 -m http.server 8011
# open http://localhost:8011/web/
```

`build.py` parses `../src-optimized/OPTIMIZATION-LOG.md` into `data.json`
(one record per Iteration / milestone / H-hypothesis, with the extracted
speedup, decision, medians, date and token cost, plus the raw markdown body).
Re-run it whenever the log changes. `python3 build.py --debug` prints the
extracted table for spot-checking.

The page must be served over `http://` (not opened as `file://`) because it
`fetch`es `data.json`.
