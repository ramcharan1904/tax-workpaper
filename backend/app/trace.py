"""Trace API: every number to its evidence, every document to where it landed.

Read-only. Nothing here changes data; adjustments and notes come later in
their own module.
"""
import json

from fastapi import APIRouter, HTTPException

from backend.app import db

router = APIRouter(prefix="/api")

HEADLINES = {
    "federal": [
        ("F1040.9", "Total income"),
        ("F1040.11", "Adjusted gross income"),
        ("F1040.15", "Taxable income"),
        ("F1040.24", "Total tax"),
        ("F1040.33", "Total payments"),
        ("F1040.37", "Amount owed"),
    ],
    "california": [
        ("F540NR.17", "Total income under California law"),
        ("F540NR.32", "California AGI"),
        ("F540NR.64", "Total tax"),
        ("F540NR.78", "Total payments"),
        ("F540NR.97", "Overpaid"),
    ],
}
# Documents that are never return inputs by nature (engagement, identity,
# prior-year reference). Anything else left unused is flagged for review.
SUPPORTING_TYPES = {
    "engagement_letter": "Engagement record, not a return input",
    "consent_7216": "Consent record, not a return input",
    "identity_document": "Identity verification, not a return input",
    "irs_ip_pin_notice": "IP PIN for e-filing, not a return input",
    "prior_year_return": "Loaded as the 2024 version for comparison",
}

# The 2024 return was a full-year California 540, so a few keys differ.
PRIOR_KEY = {"F540NR.32": "CA540.17", "F540NR.64": "CA540.64", "F540NR.78": None}


def _num(v):
    return float(v) if v is not None else None


def _line_value(row):
    return _num(row["value_num"]) if row["value_num"] is not None else row["value_text"]


def _variance_rule(conn):
    std = conn.execute("SELECT value FROM settings WHERE key = 'firm_standards'").fetchone()
    rule = (std["value"] if std else {}).get("variance_review", {})
    return rule.get("flag_if_change_over_percent", 10), rule.get("and_over_amount", 1000)


def _flag(current, prior, pct, amount):
    """Firm rule: flag a swing over pct% AND over amount (both must hold)."""
    if not isinstance(current, (int, float)) or not isinstance(prior, (int, float)):
        return False
    diff = abs(current - prior)
    base = abs(prior) or 1
    return diff > amount and diff / base * 100 > pct


@router.get("/summary")
def summary(version: str = "v3"):
    with db.pool().connection() as conn:
        pct, amount = _variance_rule(conn)
        out = {}
        for jur, items in HEADLINES.items():
            keys = [k for k, _ in items] + [PRIOR_KEY.get(k, k) for k, _ in items if PRIOR_KEY.get(k, k)]
            rows = conn.execute(
                "SELECT version, key, value_num, value_text FROM return_lines "
                "WHERE version IN (%s, '2024') AND key = ANY(%s)", (version, keys)
            ).fetchall()
            vals = {(r["version"], r["key"]): _line_value(r) for r in rows}
            out[jur] = []
            for key, label in items:
                cur = vals.get((version, key))
                pkey = PRIOR_KEY.get(key, key)
                prior = vals.get(("2024", pkey)) if pkey else None
                out[jur].append({"key": key, "label": label, "value": cur, "prior": prior,
                                 "flag": _flag(cur, prior, pct, amount)})
        areas = conn.execute(
            """
            SELECT a.id, a.name, a.budget_hours,
                   (SELECT count(*) FROM return_lines l WHERE l.version = %s AND l.area_id = a.id) AS lines,
                   (SELECT count(*) FROM findings f WHERE f.area_id = a.id AND f.status = 'open') AS open_findings
            FROM areas a ORDER BY a.sort_order
            """, (version,)
        ).fetchall()
        meta = conn.execute("SELECT version, computed_at, trigger FROM return_versions "
                            "ORDER BY computed_at").fetchall()
    return {"version": version, "headlines": out, "areas": areas, "versions": meta,
            "variance_rule": {"percent": pct, "amount": amount}}


@router.get("/areas/{area_id}")
def area(area_id: str, version: str = "v3"):
    with db.pool().connection() as conn:
        a = conn.execute("SELECT * FROM areas WHERE id = %s", (area_id,)).fetchone()
        if not a:
            raise HTTPException(404, "Unknown area")
        pct, amount = _variance_rule(conn)
        lines = conn.execute(
            """
            SELECT l.key, l.form, l.line, l.label, l.value_num, l.value_text, l.jurisdiction,
                   p.value_num AS prior_num,
                   (SELECT count(*) FROM findings f
                     WHERE f.status = 'open' AND ('line:v3:' || l.key) = ANY(f.evidence_refs)) AS findings
            FROM return_lines l
            LEFT JOIN return_lines p ON p.version = '2024' AND p.key = l.key
            WHERE l.version = %s AND l.area_id = %s
            ORDER BY l.form, l.key
            """, (version, area_id)
        ).fetchall()
        findings = conn.execute(
            "SELECT id, title, est_federal, est_ca, status, check_id FROM findings "
            "WHERE area_id = %s ORDER BY status, abs(coalesce(est_federal,0)) DESC", (area_id,)
        ).fetchall()
    rows = []
    for r in lines:
        value = _line_value(r)
        prior = _num(r["prior_num"])
        rows.append({"key": r["key"], "form": r["form"], "line": r["line"], "label": r["label"],
                     "value": value, "prior": prior, "jurisdiction": r["jurisdiction"],
                     "findings": r["findings"], "flag": _flag(value, prior, pct, amount)})
    return {"area": a, "lines": rows, "findings": findings}


def _resolve_pointer(doc, pointer):
    node = doc
    for part in pointer.strip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(part)] if part.isdigit() and int(part) < len(node) else None
        elif isinstance(node, dict):
            node = node.get(part)
        else:
            return None
        if node is None:
            return None
    return node


def _describe_ref(conn, ref, cache):
    """Turn any non-extracted-value ref into something a person can read."""
    kind, _, rest = ref.partition(":")
    if kind in ("qa", "msg", "call"):
        c = conn.execute("SELECT * FROM client_communications WHERE id = %s", (rest,)).fetchone()
        if c:
            title = c["question"] or f"{c['kind'].replace('_', ' ').title()} from {c['author'] or ', '.join(c['participants'] or [])}"
            return {"ref": ref, "kind": "client", "title": title, "detail": c["body"]}
    if kind == "asset":
        a = conn.execute("SELECT * FROM assets WHERE id = %s", (rest,)).fetchone()
        if a:
            return {"ref": ref, "kind": "asset", "title": a["description"],
                    "detail": f"{a['method']}, placed in service {a['placed_in_service']}"}
    if kind == "py":
        if rest.startswith("/return_2024/lines/"):
            key = rest.split("/")[-1]
            r = conn.execute("SELECT * FROM return_lines WHERE version = '2024' AND key = %s",
                             (key,)).fetchone()
            if r:
                return {"ref": ref, "kind": "line", "title": f"2024 return: {r['label'] or key}",
                        "detail": _line_value(r), "link": {"version": "2024", "key": key}}
        if "prior_years" not in cache:
            row = conn.execute("SELECT content FROM packet_sections WHERE name = 'prior_years'").fetchone()
            cache["prior_years"] = row["content"] if row else {}
        value = _resolve_pointer(cache["prior_years"], rest)
        return {"ref": ref, "kind": "prior_year", "title": "Prior-year record " + rest,
                "detail": value if not isinstance(value, (dict, list)) else json.dumps(value)[:400]}
    if kind == "ref":
        if "engine" not in cache:
            row = conn.execute("SELECT content FROM packet_sections WHERE name = 'engine_reference'").fetchone()
            cache["engine"] = row["content"] if row else {}
        path = rest.removeprefix("param.").replace(".", "/")
        params = cache["engine"].get("parameters", {})
        value = _resolve_pointer(params, path)
        return {"ref": ref, "kind": "parameter", "title": "Engine parameter " + rest,
                "detail": value if not isinstance(value, (dict, list)) else json.dumps(value)[:400]}
    if kind == "household":
        h = conn.execute("SELECT name, role, relationship, dob FROM household_people WHERE id = %s",
                         (rest,)).fetchone()
        if h:
            return {"ref": ref, "kind": "household", "title": h["name"],
                    "detail": f"{h['relationship'] or h['role']}, born {h['dob']}"}
    if kind == "timeline":
        t = conn.execute("SELECT * FROM timeline WHERE id = %s", (rest,)).fetchone()
        if t:
            return {"ref": ref, "kind": "timeline", "title": t["event"].replace("_", " "),
                    "detail": t["detail"]}
    return {"ref": ref, "kind": "other", "title": ref, "detail": None}


def _ev_display(e):
    """Sensitive values are stored encrypted; show the masked text instead."""
    if e["value"] is None and e["value_enc"] is not None:
        return e["text_as_read"]
    return e["value"]


@router.get("/lines/{version}/{key}")
def line(version: str, key: str):
    with db.pool().connection() as conn:
        ln = conn.execute("SELECT * FROM return_lines WHERE version = %s AND key = %s",
                          (version, key)).fetchone()
        if not ln:
            raise HTTPException(404, "Unknown line")
        inputs = conn.execute(
            "SELECT l.key, l.label, l.value_num, l.value_text FROM line_inputs i "
            "JOIN return_lines l ON l.version = i.version AND l.key = i.input_key "
            "WHERE i.version = %s AND i.key = %s ORDER BY l.key", (version, key)
        ).fetchall()
        used_by = conn.execute(
            "SELECT l.key, l.label, l.value_num, l.value_text FROM line_inputs i "
            "JOIN return_lines l ON l.version = i.version AND l.key = i.key "
            "WHERE i.version = %s AND i.input_key = %s ORDER BY l.key", (version, key)
        ).fetchall()
        sources = conn.execute(
            "SELECT s.source_ref, e.id, e.document_id, e.page, e.field, e.label, e.value, e.value_enc, "
            "e.value_type, e.text_as_read, e.confidence, d.title AS document_title "
            "FROM line_sources s LEFT JOIN extracted_values e ON e.id = s.ev_id "
            "LEFT JOIN documents d ON d.id = e.document_id "
            "WHERE s.version = %s AND s.key = %s ORDER BY s.source_ref", (version, key)
        ).fetchall()
        history = conn.execute(
            "SELECT l.version, l.value_num, l.value_text FROM return_lines l "
            "JOIN return_versions v USING (version) WHERE l.key = %s ORDER BY v.computed_at",
            (key,)
        ).fetchall()
        refs = [f"line:{version}:{key}", f"line:v3:{key}"] + [f"ev:{s['id']}" for s in sources if s["id"]]
        findings = conn.execute(
            "SELECT id, title, status, est_federal, est_ca FROM findings "
            "WHERE evidence_refs && %s ORDER BY id", (refs,)
        ).fetchall()
        cache = {}
        evidence, other = [], []
        for s in sources:
            if s["id"]:
                evidence.append({
                    "ev_id": s["id"], "document_id": s["document_id"], "document_title": s["document_title"],
                    "page": s["page"], "field": s["field"], "label": s["label"], "value": _ev_display(s),
                    "confidence": float(s["confidence"]), "text_as_read": s["text_as_read"],
                })
            else:
                other.append(_describe_ref(conn, s["source_ref"], cache))
    fmt = lambda rows: [{"key": r["key"], "label": r["label"], "value": _line_value(r)} for r in rows]  # noqa: E731
    return {
        "line": {"version": version, "key": key, "label": ln["label"], "form": ln["form"],
                 "line": ln["line"], "jurisdiction": ln["jurisdiction"], "value": _line_value(ln),
                 "rule": ln["rule"], "note": ln["note"], "area_id": ln["area_id"]},
        "inputs": fmt(inputs), "used_by": fmt(used_by),
        "evidence": evidence, "other_sources": other,
        "history": [{"version": h["version"], "value": _line_value(h)} for h in history],
        "findings": findings,
    }


def _doc_status(conn, doc_id, version="v3"):
    """Where did this document land? If nowhere, why not?"""
    used = conn.execute(
        "SELECT count(DISTINCT s.key) AS n FROM line_sources s JOIN extracted_values e ON e.id = s.ev_id "
        "WHERE s.version = %s AND e.document_id = %s", (version, doc_id)
    ).fetchone()["n"]
    if used:
        return "used", f"Feeds {used} line(s) in {version}"
    v = conn.execute("SELECT documents_superseded FROM return_versions WHERE version = %s",
                     (version,)).fetchone()
    if v and doc_id in (v["documents_superseded"] or []):
        return "superseded", "Replaced by a corrected version of this document"
    d = conn.execute("SELECT extraction_status, extraction_reason FROM documents WHERE id = %s",
                     (doc_id,)).fetchone()
    if d["extraction_status"] == "not_extracted":
        return "not_extracted", d["extraction_reason"]
    note = conn.execute(
        "SELECT key, note FROM return_lines WHERE version = %s AND note LIKE %s LIMIT 1",
        (version, f"%{doc_id}%")
    ).fetchone()
    if note:
        return "duplicate", f"{note['note']} (see {note['key']})"
    doc_type = conn.execute("SELECT document_type FROM documents WHERE id = %s",
                            (doc_id,)).fetchone()["document_type"]
    open_findings = conn.execute(
        "SELECT count(*) AS n FROM findings f WHERE f.status = 'open' AND EXISTS ("
        " SELECT 1 FROM unnest(f.evidence_refs) r WHERE r LIKE %s OR r IN ("
        "  SELECT 'ev:' || id FROM extracted_values WHERE document_id = %s))",
        (f"doc:{doc_id}#%", doc_id)
    ).fetchone()["n"]
    if open_findings:
        return "not_used", f"Not used by any line, and {open_findings} open finding(s) point at it"
    if doc_type in SUPPORTING_TYPES:
        return "supporting", SUPPORTING_TYPES[doc_type]
    # A tax document the return never used is a completeness question:
    # either it is irrelevant (say why) or the return is missing something.
    return "not_used", "Not used by any line: needs a reviewer to explain why"


@router.get("/documents")
def documents(version: str = "v3"):
    with db.pool().connection() as conn:
        docs = conn.execute(
            "SELECT d.id, d.title, d.document_type, d.received_at, d.extraction_status, "
            "(SELECT count(*) FROM extracted_values e WHERE e.document_id = d.id) AS values "
            "FROM documents d ORDER BY d.id"
        ).fetchall()
        out = []
        for d in docs:
            status, reason = _doc_status(conn, d["id"], version)
            out.append({**d, "status": status, "reason": reason})
    return {"documents": out}


@router.get("/documents/{doc_id}")
def document(doc_id: str, version: str = "v3"):
    with db.pool().connection() as conn:
        d = conn.execute("SELECT * FROM documents WHERE id = %s", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, "Unknown document")
        pages = conn.execute("SELECT page, printed_content FROM pages WHERE document_id = %s "
                             "ORDER BY page", (doc_id,)).fetchall()
        values = conn.execute("SELECT id, page, field, label, value, value_enc, value_type, text_as_read, "
                              "position, confidence FROM extracted_values WHERE document_id = %s "
                              "ORDER BY page, id", (doc_id,)).fetchall()
        landed = conn.execute(
            "SELECT s.version, s.key, s.ev_id, l.label, l.value_num, l.value_text "
            "FROM line_sources s JOIN extracted_values e ON e.id = s.ev_id "
            "JOIN return_lines l ON l.version = s.version AND l.key = s.key "
            "WHERE e.document_id = %s AND s.version = %s ORDER BY s.key", (doc_id, version)
        ).fetchall()
        ev_refs = [f"ev:{v['id']}" for v in values]
        findings = conn.execute(
            "SELECT id, title, status FROM findings WHERE evidence_refs && %s OR EXISTS "
            "(SELECT 1 FROM unnest(evidence_refs) r WHERE r LIKE %s) ORDER BY id",
            (ev_refs, f"doc:{doc_id}#%")
        ).fetchall()
        status, reason = _doc_status(conn, doc_id, version)
    lines = {}
    for r in landed:
        item = lines.setdefault(r["key"], {"key": r["key"], "label": r["label"],
                                           "value": _line_value(r), "ev_ids": []})
        item["ev_ids"].append(r["ev_id"])
    return {
        "document": {k: d[k] for k in ("id", "title", "document_type", "issuer", "belongs_to", "received_at",
                                       "uploaded_by", "page_count", "marked_corrected",
                                       "extraction_status", "extraction_reason")},
        "status": status, "reason": reason,
        "pages": pages,
        "values": [{"id": v["id"], "page": v["page"], "field": v["field"], "label": v["label"],
                    "value": _ev_display(v), "value_type": v["value_type"],
                    "text_as_read": v["text_as_read"], "position": v["position"],
                    "confidence": float(v["confidence"])} for v in values],
        "landed_on": list(lines.values()),
        "findings": findings,
    }


@router.get("/findings")
def findings(area: str | None = None, status: str | None = None):
    sql = "SELECT * FROM findings WHERE true"
    args = []
    if area:
        sql += " AND area_id = %s"
        args.append(area)
    if status:
        sql += " AND status = %s"
        args.append(status)
    sql += " ORDER BY status, abs(coalesce(est_federal,0)) + abs(coalesce(est_ca,0)) DESC"
    with db.pool().connection() as conn:
        rows = conn.execute(sql, args).fetchall()
        # Resolve ev:... refs to their document so the UI can open the page.
        ev_ids = sorted({r.removeprefix("ev:") for f in rows for r in f["evidence_refs"]
                         if r.startswith("ev:")})
        docs = {r["id"]: r["document_id"] for r in conn.execute(
            "SELECT id, document_id FROM extracted_values WHERE id = ANY(%s)", (ev_ids,)
        ).fetchall()}
    return {"findings": rows, "ev_documents": docs}
