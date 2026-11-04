# Met collection documentation survey

An interactive overview of how fully The Met's collection is documented, field by field and department by department, built from a survey of 546,856 objects across 19 curatorial departments and 84 scored metadata fields via the Met's private Hasura collection API.

**Live page:** https://giuliataurino.github.io/met_collection_documentation_survey/

## What is here

- `met_department_field_fill_heatmap.html` — the self-contained interactive heatmap (department × field fill rate, Met reds for empty through Met blues for full, with a classification view and least/most documented summaries). `index.html` just opens it.
- `data/` — the survey outputs the page was built from:
  - `department_x_field_fill.csv`, `classification_x_field_fill.csv` — fill-rate matrices
  - `department_summary.csv`, `classification_summary.csv` — per-group completeness, fields never/always filled
  - `field_survey.csv` — per-field fill, how it is unfilled (null / empty / placeholder / zero / absent), distinct values, label-quality signals
  - `focused_department_summary.csv`, `scholar_metadata_summary.csv` — completeness on curatorial and scholarship fields only
  - `field_by_department_comparison.csv`, `taxonomy_spreadsheet.csv` — field × department pivot and the field-to-category taxonomy

## How to read it

A field counts as filled when the object carries an informative value; nulls, empty strings and lists, numeric zeros in date fields, placeholder strings and absent keys all count as unfilled. Identifiers, flags and housekeeping columns are not scored. Fields marked *private* exist only in the Hasura schema, not in the public Collection API, so their fill rates describe internal cataloguing rather than what the public can see.

Related: [met-harvester-diagnostics](https://github.com/giuliataurino/met-harvester-diagnostics) and [met-harvester-diagnostics-visualizations](https://github.com/giuliataurino/met-harvester-diagnostics-visualizations), which run the equivalent survey against the public Collection API.

## Publishing

The site is served with GitHub Pages from the `main` branch, root folder (Settings → Pages → Deploy from a branch → `main` / `/ (root)`).
