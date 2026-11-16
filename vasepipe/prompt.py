"""Prompts. The constrained prompt carries the hierarchy and scope notes,
not a flat keyword list. The model sees the photograph and this text only."""
from . import vocab

BASELINE = "Describe this object."

RESPONSE_SHAPE = (
    '{"is_fragment": false, "shape_id": "calyx-krater", "shape_confidence": 0.8, '
    '"shape_evidence": "one sentence on the visible features that decide the shape", '
    '"technique_id": "red-figure", "fabric_id": "attic", "period_id": "classical", '
    '"decoration": [{"zone": "Side A", "text": "what is shown"}], "subjects": ["Dionysos", "satyrs"], '
    '"description": "Two to four sentences in catalogue style, using the vocabulary labels for shape and technique.", '
    '"out_of_vocabulary": ["any term you needed that the vocabulary lacks"]}'
)


def constrained():
    lines = [
        "You are cataloguing one ancient Greek or Roman ceramic vessel, or a fragment of one, from a single "
        "photograph, for a museum collection record.",
        "Use ONLY the controlled vocabulary below. Shapes form a hierarchy: objects > furnishings and equipment > "
        "containers > vessels > function group > shape > variant. Work down it and choose the deepest node the "
        "photograph supports. If the evidence supports only the parent (for example a krater whose handles are not "
        'visible), stop at the parent. Never substitute a generic word such as "vase", "pot", "urn" or "jar" for a '
        "listed term.",
        "If the object is a fragment, set is_fragment to true and still name the shape it came from when the "
        "profile, curvature or decoration scheme supports it; otherwise shape_id is null.",
        "", "SHAPES  (id | label | scope note)",
    ]

    def add(shape, indent):
        lines.append(f"{indent}{shape['id']} | {shape['label']} | {shape['note']}")
        for child in vocab.SHAPES.values():
            if child["parent"] == shape["id"]:
                add(child, indent + "  ")

    for fn_id, fn_label in vocab.FN:
        lines.append(fn_label)
        for s in vocab.SHAPES.values():
            if s["fn"] == fn_id and not s["parent"]:
                add(s, "  ")
    lines += ["", "TECHNIQUES  (id | label | scope note)"]
    lines += [f"  {t['id']} | {t['label']} | {t['note']}" for t in vocab.TECHNIQUES.values()]
    lines += ["", "FABRICS  (id | label | region)"]
    lines += [f"  {f['id']} | {f['label']} | {f['note']}" for f in vocab.FABRICS.values()]
    lines += ["", "PERIODS  (id | label | years, negative = BCE)"]
    lines += [f"  {p['id']} | {p['label']} | {p['start']} to {p['end']}" for p in vocab.PERIODS.values()]
    lines += ["", "Reply with only a JSON object of this form:", RESPONSE_SHAPE,
              "Use null for any id the photograph cannot support. Use only ids from the lists above."]
    return "\n".join(lines)
