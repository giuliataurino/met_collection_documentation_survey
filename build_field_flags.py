"""Build the heatmap's flag layer from one page of the Met's Collection Online docs:
departments/tombstone-check.html ("The CRD Tombstone Documentation, checked", 29 Oct 2026),
the cell-by-cell audit of Collection Information's Tombstone workbook (538 cells).

Each grid cell (workbook row x department) carries a verdict (correct / incomplete / outdated /
wrong / ambiguous) and a hover text "Workbook: ... / Today: ...". From it we take

  * blanked  - the "Today" text says CRD blanks or never shows the field for that department
               -> hatched cell in the heatmap ("blanked by an import rule for that department")
  * verdicts - wrong / outdated / incomplete per field x department -> marker on the field name
               (red = wrong somewhere, amber = outdated, grey = incomplete / ambiguous)

Usage:  python build_field_flags.py collection-online.html  -> field_flags.json, field_flags.csv
"""
import csv, html, json, re, sys
from collections import defaultdict

PAGE = "departments/tombstone-check.html"

DEPT = {"MCR": "The Michael C. Rockefeller Wing", "AW": "The American Wing", "ADA": "The American Wing",
        "APS": None, "AWAA": "Ancient West Asian Art", "ARMS": "Arms and Armor", "ASA": "Asian Art",
        "CI": "Costume Institute", "DP": "Drawings and Prints", "EG": "Egyptian Art",
        "ESDA": "European Sculpture and Decorative Arts", "EP": "European Paintings", "GR": "Greek and Roman Art",
        "ISL": "Islamic Art", "MED": "Medieval Art", "CLOIS": "The Cloisters", "MED/CLOIS": ["Medieval Art", "The Cloisters"],
        "MOD": "Modern and Contemporary Art", "MI": "Musical Instruments", "PH": "Photographs",
        "RLC": "Robert Lehman Collection", "LIB": "The Libraries", "All": None}

# workbook row -> heatmap field names it describes
ROW_FIELDS = {
    "Title": ["title"], "Artist": ["artistDisplayName", "artistRole", "artistDisplayBio", "constituents"],
    "Period": ["period"], "Date": ["objectDate"], "Dynasty": ["dynasty"], "Reign": ["reign"],
    "Catalogue Raisonne": ["catRais"], "Portfolio/Series": ["portfolio"],
    "Geography": ["country", "region", "city", "state", "county", "subregion", "locale", "locus", "excavation", "river"],
    "Culture": ["culture"], "Medium": ["medium"], "Dimensions": ["dimensions"],
    "Classification": ["classification", "subClassification"],
    "Credit Line for Reproduction": ["rightsAndReproduction"], "Credit Line": ["creditLine"],
    "Object Number": ["accessionNumber"], "Label": ["webLabel"], "Other Labels": ["textEntries"],
    "Provenance": ["provenance"], "Exhibition History": ["exhibitionsStructured"], "Marks": ["markings"],
    "Signed": ["signed"], "Inscribed": ["inscribed"], "Notes": ["notes"], "Related Works": ["relatedWorks"],
    "References": ["bibliographyStructured"],
}
SYMBOL = {"✓": "correct", "+": "incomplete", "old": "outdated", "✗": "wrong", "?": "ambiguous", "": "empty"}
# "Today" texts that mean the nightly import (CRD) publishes nothing for that department
BLANK_RE = re.compile(r"^(never shown|Field blanked|Not even published to CRD)", re.I)
# ... except where the text says CRD does publish it and only the website recipe drops it
DISPLAY_ONLY_RE = re.compile(r"CRD publishes \w+ for the|removed from the Collection API|API recipe has no", re.I)


def load_page(path: str) -> str:
    s = open(path, encoding="utf-8", errors="ignore").read()
    m = re.search(r'<script type="application/json" id="co-pages">(.*?)</script>', s, flags=re.S)
    return (json.loads(m.group(1))[PAGE]["h"]) if m else s


def parse_grid(h: str):
    """yield (sheet, row, dept_abbr, verdict, workbook_text, today_text) for every grid cell"""
    for sheet in re.split(r"<h2[^>]*>", h)[1:]:
        name = re.sub(r"<.*?>", "", sheet.split("</h2>")[0]).strip()
        thead = re.search(r"<thead>(.*?)</thead>", sheet, flags=re.S)
        if not thead:
            continue
        cols = [html.unescape(re.sub(r"<.*?>", "", c)).strip() for c in re.findall(r"<th[^>]*>(.*?)</th>", thead.group(1), flags=re.S)][1:]
        body = sheet.split("</thead>", 1)[1].split("</table>")[0]
        for tr in re.findall(r"<tr>(.*?)</tr>", body, flags=re.S):
            rowm = re.search(r'<th class="rowh">(.*?)</th>', tr)
            if not rowm:
                continue
            row = html.unescape(re.sub(r"<.*?>", "", rowm.group(1))).strip()
            cells = re.findall(r'<td class="cell[^"]*"(?: title="(.*?)")?>(.*?)</td>', tr, flags=re.S)
            for (title, sym), dept in zip(cells, cols):
                t = html.unescape(title or "")
                wb, _, today = t.partition("\n\nToday: ")
                yield name, row, dept, SYMBOL.get(html.unescape(sym).strip(), "other"), wb.replace("Workbook: ", "").strip(), today.strip()


def build(doc_path: str):
    h = load_page(doc_path)
    acc = defaultdict(lambda: {"blanked": set(), "cells": []})
    n = 0
    for sheet, row, abbr, verdict, wb, today in parse_grid(h):
        fields = ROW_FIELDS.get(row)
        if not fields:
            continue
        depts = DEPT.get(abbr, abbr)
        depts = depts if isinstance(depts, list) else ([depts] if depts else [])
        blank = bool(BLANK_RE.search(today)) and not DISPLAY_ONLY_RE.search(today)
        display_only = bool(BLANK_RE.search(today)) and bool(DISPLAY_ONLY_RE.search(today))
        n += 1
        for f in fields:
            for d in depts:
                if blank:
                    acc[f]["blanked"].add(d)
                acc[f]["cells"].append({"dept": d, "sheet": sheet, "row": row, "verdict": verdict, "blanked": blank,
                                        "display_only": display_only, "workbook": wb[:400], "today": today[:600]})
    out = {}
    for f, v in acc.items():
        verdicts = {c["verdict"] for c in v["cells"]}
        level = ("high" if "wrong" in verdicts else "medium" if "outdated" in verdicts
                 else "low" if verdicts & {"incomplete", "ambiguous"} else "none")
        if level == "none" and not v["blanked"]:
            continue
        by = {k: sorted({c["dept"] for c in v["cells"] if c["verdict"] == k}) for k in ("wrong", "outdated", "incomplete", "ambiguous")}
        summary = "; ".join(f"{k} for {', '.join(d)}" for k, d in by.items() if d) or "blanked for some departments"
        out[f] = {"level": level, "summary": summary, "blanked": sorted(v["blanked"]), "row": v["cells"][0]["row"],
                  "sheet": v["cells"][0]["sheet"], "cells": v["cells"]}
    print(f"{n} workbook cells mapped onto {len(out)} fields")
    return out


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "collection-online.html"
    flags = build(src)
    json.dump(flags, open("field_flags.json", "w"), indent=1)
    with open("field_flags.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["field", "workbook_sheet", "workbook_row", "department", "verdict", "blanked_by_import", "dropped_by_website_only", "workbook_says", "true_today"])
        for f, v in sorted(flags.items()):
            for c in v["cells"]:
                w.writerow([f, c["sheet"], c["row"], c["dept"], c["verdict"], "yes" if c["blanked"] else "", "yes" if c["display_only"] else "", c["workbook"], c["today"]])
    for f, v in sorted(flags.items(), key=lambda x: ({"high": 0, "medium": 1, "low": 2, "none": 3}[x[1]["level"]], x[0])):
        print(f"  {v['level']:6s} {f:24s} {v['summary'][:80]}{'  | blanked: ' + ', '.join(v['blanked']) if v['blanked'] else ''}")
