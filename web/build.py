#!/usr/bin/env python3
"""Parse src-optimized/OPTIMIZATION-LOG.md into structured JSON for the browser.

One JSON record per browsable log entry: the origin "Iteration N" experiments,
the milestone/report sections, and the H-numbered hypotheses (H1..Hn). For each
we pull a representative speedup, the kept/rejected decision, optimized/reference
medians, date and token cost, plus the raw markdown body so the page can render
the full text of every entry.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.normpath(os.path.join(HERE, "..", "src-optimized", "OPTIMIZATION-LOG.md"))

# A new browsable entry starts at any of these headers. Everything up to the
# next such header (including deeper ### / #### subsections) is that entry's body.
ENTRY_STARTS = [
    re.compile(r"^##\s+H(\d+)\b\s*[—-]\s*(.*)$"),            # H-hypotheses
    re.compile(r"^###\s+(Iteration\s+\d+)\b\s*[—-]?\s*(.*)$"),  # origin iterations
    re.compile(r"^###\s+(Milestone)\b\s*[—-]?\s*(.*)$"),
    re.compile(r"^###\s+(Historical final[^\n]*)$"),
    re.compile(r"^###\s+(Phase 4[^\n]*)$"),
    re.compile(r"^###\s+(Final integrated[^\n]*)$"),
    re.compile(r"^##\s+(~[^\n]*milestone[^\n]*)$"),
    re.compile(r"^##\s+(Origin history[^\n]*)$"),
]

# Curated representative speedups for the narrative entries whose number lives in
# prose/tables rather than a "speedup N.Nx" measurement line. Keys are entry ids.
SPEEDUP_OVERRIDE = {
    "H1": 25.3, "H2": 54.4, "H3": 61.5, "H4": 60.0, "H5": 51.5,
}


def split_entries(text):
    lines = text.split("\n")
    entries = []
    cur = None
    for ln in lines:
        start = None
        for rx in ENTRY_STARTS:
            m = rx.match(ln)
            if m:
                start = (rx, m)
                break
        if start:
            if cur:
                entries.append(cur)
            rx, m = start
            if rx is ENTRY_STARTS[0]:  # H entry
                eid = "H" + m.group(1)
                title = m.group(2).strip()
            else:
                gid = m.group(1).strip()
                rest = (m.group(2).strip() if m.lastindex and m.lastindex >= 2 else "")
                eid = gid
                title = rest
            cur = {"id": eid, "title": title, "header": ln, "body_lines": []}
        elif cur is not None:
            cur["body_lines"].append(ln)
    if cur:
        entries.append(cur)
    return entries


def flat(text):
    return re.sub(r"\s+", " ", text)


def find_decision(eid, body):
    m = re.search(r"\*\*Decision:\*\*\s*([A-Za-z/ ]+)", body)
    if m:
        d = m.group(1).upper()
        if "ADOPT" in d or "KEPT" in d or "KEEP" in d:
            return "kept"
        if "REJECT" in d or "REVERT" in d:
            return "rejected"
    f = flat(body).lower()
    # origin iterations phrase their decision in prose
    if re.search(r"decision:\s*(keep|adopt)", f):
        return "kept"
    if re.search(r"decision:\s*reject", f):
        return "rejected"
    if "target reached" in (eid + " " + body).lower() or "milestone" in eid.lower() \
            or "report" in eid.lower() or "phase 4" in eid.lower():
        return "milestone"
    return "info"


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def get_section(body, name):
    """Text of the '### <name>' subsection up to the next ###/## header."""
    out, grab = [], False
    for ln in body.split("\n"):
        if re.match(r"^#{2,4}\s+", ln):
            grab = ln.strip().lower().lstrip("# ").startswith(name.lower())
            continue
        if grab:
            out.append(ln)
    return "\n".join(out)


def logical_lines(text):
    """Rejoin soft-wrapped bullets/paragraphs into one logical line each, so a
    value never gets separated from its label by the 78-column wrap."""
    out = []
    for ln in text.split("\n"):
        if not ln.strip():
            out.append("")
            continue
        starts_block = re.match(r"^\s*([-*]\s|#{1,6}\s|\||\d+\.\s)", ln)
        if starts_block or not out or out[-1] == "":
            out.append(ln.strip())
        else:
            out[-1] = out[-1] + " " + ln.strip()
    return [l for l in out if l.strip()]


def median_in(line, which):
    m = re.search(which + r" median[s]?:?\s*(?:was\s*|about\s*)?([0-9.]+)", line)
    if not m:
        return None
    v = num(m.group(1))
    # a real median is a sub-second time; anything >= 5 is a speedup like
    # "reference median: 23.94x" appearing in a sentence, not a time.
    return v if (v is not None and v < 5) else None


def find_medians(eid, body):
    """Return (ref_median, opt_median) for this entry's own measurement.

    Scoped to single lines so the periods inside decimals never let a match
    bleed across into a neighbouring (e.g. baseline) measurement.
    """
    sec = get_section(body, "Measurement protocol")
    text = sec if sec.strip() else body
    lines = logical_lines(text)
    idrx = re.compile(re.escape(eid) + r"\b")
    # 1) a line naming this entry id that carries BOTH medians (the paired
    #    measurement that the keep/revert decision is actually based on)
    for l in lines:
        o, r = median_in(l, "optimized"), median_in(l, "reference")
        if idrx.search(l) and o is not None and r is not None:
            return r, o
    # 2) any single line carrying both medians
    for l in lines:
        o, r = median_in(l, "optimized"), median_in(l, "reference")
        if o is not None and r is not None:
            return r, o
    # 3) a line naming this entry id with at least an optimized median
    for l in lines:
        if idrx.search(l) and median_in(l, "optimized") is not None:
            return median_in(l, "reference"), median_in(l, "optimized")
    # 4) first optimized / first reference median anywhere (origin iterations)
    ref = opt = None
    for l in lines:
        if opt is None:
            opt = median_in(l, "optimized")
        if ref is None:
            ref = median_in(l, "reference")
    return ref, opt


def find_speedup(eid, title, body):
    if eid in SPEEDUP_OVERRIDE:
        return SPEEDUP_OVERRIDE[eid]
    # milestone title like "(23.94x)" or "~64× milestone"
    m = re.search(r"\((\d+(?:\.\d+)?)x\)", title)
    if m:
        return num(m.group(1))
    m = re.search(r"~(\d+(?:\.\d+)?)\s*[x×]", title)
    if m:
        return num(m.group(1))

    # the keep/revert metric is the paired median ratio; prefer it when present
    ref, opt = find_medians(eid, body)
    if ref and opt:
        return round(ref / opt, 2)

    sec = get_section(body, "Measurement protocol")
    text = sec if sec.strip() else body
    sp = re.compile(r"speedup[^.\n]*?(\d+(?:\.\d+)?)\s*[x×]", re.I)
    for l in logical_lines(text):
        m = sp.search(l)
        if m:
            return num(m.group(1))
    # last resort: any "speedup ... Nx" / "about Nx" in the whole body
    m = sp.search(flat(body))
    if m:
        return num(m.group(1))
    m = re.search(r"about\s+(\d+(?:\.\d+)?)\s*[x×]\b", flat(body), re.I)
    if m:
        return num(m.group(1))
    return None


def find_date(body):
    m = re.search(r"\*\*Date:\*\*\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", body)
    return m.group(1) if m else None


def find_tokens(body):
    f = flat(body)
    for rx in (r"=\s*([\d,]+)\s*total",
               r"reported token delta:\s*([\d,]+)",
               r"token delta[^.]*?([\d,]+)\s*(?:total|in)"):
        m = re.search(rx, f)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def main():
    with open(LOG, encoding="utf-8") as fh:
        text = fh.read()
    raw_entries = split_entries(text)

    records = []
    idx = 0
    for e in raw_entries:
        eid = e["id"]
        body = "\n".join(e["body_lines"]).strip("\n")
        # the overview / section-divider entries are headers only, not experiments
        is_section = eid.lower().startswith("origin history") \
            or eid.lower().startswith("continued")
        decision = "info" if is_section else find_decision(eid, body)
        speedup = None if is_section else find_speedup(eid, e["title"], body)
        ref, opt = find_medians(eid, body)
        rec = {
            "index": idx,
            "id": eid,
            "title": e["title"],
            "decision": decision,
            "speedup": speedup,
            "ref_median": ref,
            "opt_median": opt,
            "opt_ms": round(opt * 1000, 3) if opt else None,
            "date": find_date(body),
            "tokens": find_tokens(body),
            "is_section": bool(is_section),
            "markdown": body,
        }
        records.append(rec)
        idx += 1

    # group flag: origin vs continued (this repo). Split at "Continued in this repo".
    phase = "origin"
    for r in records:
        if r["id"].lower().startswith("continued") or r["id"].startswith("H"):
            phase = "repo"
        r["phase"] = phase

    out = {
        "source": "src-optimized/OPTIMIZATION-LOG.md",
        "generated_by": "web/build.py",
        "entries": records,
    }
    with open(os.path.join(HERE, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)

    # debug table
    if "--debug" in sys.argv:
        for r in records:
            print(f"{r['index']:>3} {r['id']:<14} {str(r['decision']):<9} "
                  f"speed={str(r['speedup']):<8} opt_ms={str(r['opt_ms']):<9} "
                  f"ref={str(r['ref_median']):<9} tok={str(r['tokens']):<9} "
                  f"| {r['title'][:50]}")
    print(f"\nWrote data.json with {len(records)} entries")


if __name__ == "__main__":
    main()
