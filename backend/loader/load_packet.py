"""Load the packet into Postgres, exactly as delivered.

Usage (from the project root):
    python -m backend.loader.load_packet data/packet.json --reset

Environment:
    DATABASE_URL_UNPOOLED  direct (non-pooled) Neon connection, used for bulk
                           loads. Falls back to DATABASE_URL.
    ENCRYPTION_KEY         Fernet key for sensitive values.

What it does, in order:
  1. Reads the file without changing it; stores an encrypted copy + SHA-256.
  2. Masks sensitive values (SSNs, account numbers, PINs) everywhere they
     appear in text; stores full values only encrypted.
  3. Fills the packet tables.
  4. Seeds firm data: areas, users, deadlines, assignments, settings.
  5. Loads the findings from the offline sweep.
  6. Prints row counts so you can verify the load.

--reset empties every table first (TRUNCATE skips the append-only triggers,
which guard row-by-row UPDATE/DELETE). Use it only to rebuild from scratch.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from backend.app import security
from backend.loader.area_map import AREAS, area_for

NUMERIC_TYPES = {"money", "integer", "quantity", "percent"}
SENSITIVE_EV_TYPES = {"ssn", "account_number"}
SENSITIVE_EV_FIELDS = {"ip_pin"}

ALL_TABLES = [
    # human layer first (they reference packet tables)
    "user_seen", "time_entries", "assignments", "deadlines", "settings",
    "view_log", "attachments", "signoffs", "verifications", "decisions",
    "notes", "adjustments", "findings", "filings", "events",
    # packet layer
    "asset_depreciation", "assets", "timeline", "agency_records",
    "client_communications", "line_sources", "line_inputs", "return_lines",
    "return_versions", "extracted_values", "pages", "documents",
    "household_people", "users", "areas", "packet_sections", "packet_raw",
]


def ref_for_source(source: str) -> tuple[str, str | None]:
    """Convert a packet source id to our ref format. Returns (ref, ev_id)."""
    if source.startswith("ev-"):
        return f"ev:{source}", source
    for prefix in ("qa-", "msg-", "call-"):
        if source.startswith(prefix):
            return f"{prefix[:-1]}:{source}", None
    return source, None  # py:/..., asset:..., ref:..., household:..., timeline:...


def split_value(value):
    """Return (value_num, value_text) for a return line value."""
    if isinstance(value, bool) or value is None:
        return None, None if value is None else str(value)
    if isinstance(value, (int, float)):
        return value, None
    return None, str(value)


def collect_secrets(p: dict) -> list[str]:
    """Every sensitive literal we must never show unmasked in text."""
    secrets = []
    for person in p["household"]["people"]:
        for k in ("ssn", "ip_pin"):
            if person.get(k):
                secrets.append(person[k])
    bank = p["household"].get("bank_account_for_refund_or_payment") or {}
    secrets += [bank.get("account", ""), bank.get("routing", "")]
    for e in p["extracted_values"]:
        if e["value_type"] in SENSITIVE_EV_TYPES or e["field"] in SENSITIVE_EV_FIELDS:
            secrets.append(str(e["value"]))
    ero_pin = p["firm"]["firm_identity"].get("ero_pin")
    if ero_pin:
        secrets.append(ero_pin)
    return [s for s in secrets if s]


def load(conn: psycopg.Connection, raw_bytes: bytes, findings_path: Path) -> None:
    p = json.loads(raw_bytes)
    secrets = collect_secrets(p)
    mask = lambda text: security.mask_text(text, secrets)  # noqa: E731
    cur = conn.cursor()

    # 1. Raw copy, encrypted, with the fingerprint of the exact bytes.
    sha = hashlib.sha256(raw_bytes).hexdigest()
    cur.execute(
        "INSERT INTO packet_raw (client_id, content_enc, sha256) VALUES (%s, %s, %s)",
        (p["packet"]["client_id"], security.encrypt(raw_bytes), sha),
    )

    # Read-whole sections without sensitive data.
    household_meta = {
        k: v for k, v in p["household"].items()
        if k not in ("people", "bank_account_for_refund_or_payment")
    }
    bank = p["household"].get("bank_account_for_refund_or_payment") or {}
    household_meta["bank_account_for_refund_or_payment"] = {
        "bank": bank.get("bank"), "type": bank.get("type"),
        "account_last4": security.last4(bank.get("account", "")),
    }
    firm_identity = dict(p["firm"]["firm_identity"])
    firm_identity["ero_pin"] = "*****"
    sections = {
        "packet": p["packet"],
        "readme": p["readme"],
        "household": household_meta,
        "firm_identity": firm_identity,
        "engine_reference": p["engine_reference"],
        "what_if": p["what_if"],
        "planning_reference_2026": p["planning_reference_2026"],
        "post_filing_rates": p["post_filing_rates"],
        "fx_rates": p["fx_rates"],
        "prior_years": {k: v for k, v in p["prior_years"].items() if k != "return_2024"},
        "return_2024_meta": {k: v for k, v in p["prior_years"]["return_2024"].items()
                             if k not in ("lines", "line_labels", "line_sources", "dependents")},
    }
    for name, content in sections.items():
        cur.execute("INSERT INTO packet_sections (name, content) VALUES (%s, %s)",
                    (name, Jsonb(json.loads(mask(json.dumps(content))))))

    # 2. Areas from the firm's budget.
    budget = p["firm"]["budget_hours"]
    for order, (area_id, name) in enumerate(AREAS, start=1):
        cur.execute("INSERT INTO areas VALUES (%s, %s, %s, %s)",
                    (area_id, name, budget[area_id], order))

    # 3. Users: staff + client users.
    for s in p["firm"]["staff"]:
        cur.execute(
            "INSERT INTO users (id, name, role, credential, sensitive_clearance, active_from) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (s["id"], s["name"], s["role"], s.get("credential"),
             s.get("sensitive_data_clearance", False), s.get("active_from")),
        )
    for c in p["firm"]["client_users"]:
        cur.execute("INSERT INTO users (id, name, role) VALUES (%s, %s, 'client')",
                    (c["id"], c["name"]))

    # 4. Household people: SSN split into encrypted / last4 / fingerprint.
    for person in p["household"]["people"]:
        ssn = person.get("ssn")
        cur.execute(
            "INSERT INTO household_people (id, role, name, dob, relationship, "
            "months_lived_with_you, full_time_student, ssn_enc, ssn_last4, ssn_hmac, ip_pin_enc) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (person["id"], person["role"], person["name"], person.get("dob"),
             person.get("relationship"), person.get("months_lived_with_you"),
             person.get("full_time_student"),
             security.encrypt(ssn) if ssn else None,
             security.last4(ssn) if ssn else None,
             security.fingerprint(ssn) if ssn else None,
             security.encrypt(person["ip_pin"]) if person.get("ip_pin") else None),
        )

    # 5. Documents and pages (page text masked).
    for d in p["documents"]:
        ex = d["extraction"]
        cur.execute(
            "INSERT INTO documents VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (d["id"], d["title"], d["document_type"], d.get("issuer"), d["belongs_to"],
             d.get("tax_year"), d["received_at"], d["uploaded_by"], d.get("file_name"),
             d["page_count"], bool(d.get("marked_corrected")), ex["status"], ex.get("reason")),
        )
        with cur.copy("COPY pages (document_id, page, printed_content) FROM STDIN") as copy:
            for pg in d["pages"]:
                copy.write_row((d["id"], pg["page"], mask(pg["printed_content"])))

    # 6. Extracted values. Sensitive values: encrypted, value/text masked.
    with cur.copy(
        "COPY extracted_values (id, document_id, page, field, label, value, value_num, "
        "value_enc, value_type, text_as_read, position, confidence) FROM STDIN"
    ) as copy:
        for e in p["extracted_values"]:
            sensitive = e["value_type"] in SENSITIVE_EV_TYPES or e["field"] in SENSITIVE_EV_FIELDS
            value = e["value"]
            value_num = None
            if (e["value_type"] in NUMERIC_TYPES and isinstance(value, (int, float))
                    and not isinstance(value, bool)):
                value_num = value
            copy.write_row((
                e["id"], e["document_id"], e["page"], e["field"], e["label"],
                None if sensitive else json.dumps(value),
                value_num,
                security.encrypt(str(value)) if sensitive and value is not None else None,
                e["value_type"],
                mask(e["text_as_read"]) if e["text_as_read"] else e["text_as_read"],
                json.dumps(e["position"]) if e.get("position") else None,
                e["confidence"],
            ))

    # 7. Return versions: the 2024 return as filed, then v1..v3.
    r24 = p["prior_years"]["return_2024"]
    cur.execute(
        "INSERT INTO return_versions (version, computed_at, trigger) VALUES (%s, %s, %s)",
        ("2024", r24["filed"] + "T00:00:00Z", f"Filed by {r24['prepared_by']}"),
    )
    for v in p["return_versions"]:
        cur.execute(
            "INSERT INTO return_versions VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (v["version"], v["computed_at"], v["trigger"], Jsonb(v["summary"]),
             Jsonb(v["tax_effect_rates"]), Jsonb(v["diagnostics"]),
             v["documents_used"], v["documents_superseded"]),
        )

    # 8. Return lines + their links. Lines first, then links (foreign keys).
    line_rows, input_rows, source_rows = [], [], []
    for key, value in r24["lines"].items():
        jur = "california" if key.startswith("CA540") else "federal"
        form, _, line = key.partition(".")
        num, text = split_value(value)
        line_rows.append(("2024", key, jur, form, line, r24["line_labels"].get(key),
                          num, text, None, (r24.get("notes") or {}).get(key), area_for(key, jur)))
        src = r24["line_sources"].get(key)
        for s in ([src] if isinstance(src, str) else (src or [])):
            ref, ev_id = ref_for_source(s)
            source_rows.append(("2024", key, ref, ev_id))
    for v in p["return_versions"]:
        for ln in v["lines"]:
            num, text = split_value(ln["value"])
            line_rows.append((v["version"], ln["key"], ln["jurisdiction"], ln["form"], ln["line"],
                              ln.get("label"), num, text, ln.get("rule"), ln.get("note"),
                              area_for(ln["key"], ln["jurisdiction"])))
            for inp in ln.get("inputs") or []:
                input_rows.append((v["version"], ln["key"], inp))
            for s in ln.get("sources") or []:
                ref, ev_id = ref_for_source(s)
                source_rows.append((v["version"], ln["key"], ref, ev_id))
    with cur.copy("COPY return_lines (version, key, jurisdiction, form, line, label, value_num, "
                  "value_text, rule, note, area_id) FROM STDIN") as copy:
        for row in line_rows:
            copy.write_row(row)
    with cur.copy("COPY line_inputs (version, key, input_key) FROM STDIN") as copy:
        for row in dict.fromkeys(input_rows):          # de-duplicate, keep order
            copy.write_row(row)
    with cur.copy("COPY line_sources (version, key, source_ref, ev_id) FROM STDIN") as copy:
        seen = set()
        for row in source_rows:
            if row[:3] not in seen:
                seen.add(row[:3])
                copy.write_row(row)

    # 9. Client communications.
    for q in p["client"]["questionnaire"]:
        cur.execute(
            "INSERT INTO client_communications (id, kind, at, author, question, body) "
            "VALUES (%s, 'questionnaire', %s, %s, %s, %s)",
            (q["id"], q["answered_at"], q["answered_by"], q["question"], mask(q["answer"])),
        )
    for m in p["client"]["messages"]:
        cur.execute(
            "INSERT INTO client_communications (id, kind, at, author, recipient, body) "
            "VALUES (%s, 'message', %s, %s, %s, %s)",
            (m["id"], m["sent_at"], m["from"], m["to"], mask(m["text"])),
        )
    for c in p["client"]["call_notes"]:
        cur.execute(
            "INSERT INTO client_communications (id, kind, at, body, participants) "
            "VALUES (%s, 'call_note', %s, %s, %s)",
            (c["id"], c["date"], mask("\n".join(c["notes"])), c["participants"]),
        )

    # 10. Agency records.
    ar = p["tax_agency_records"]
    for snap in ar["irs_account_transcript_2025"]:
        for t in snap["transactions"]:
            amt = t["amount"] if isinstance(t["amount"], (int, float)) else None
            details = None if amt is not None else {"amount_text": t["amount"]}
            cur.execute(
                "INSERT INTO agency_records (agency, record_type, as_of, tx_date, code, "
                "description, amount, tax_year, details) "
                "VALUES ('IRS','transcript',%s,%s,%s,%s,%s,2025,%s)",
                (snap["as_of"], t["date"], t["code"], t["description"], amt,
                 Jsonb(details) if details else None),
            )
    ftb = ar["ftb_account"]
    for year_key, year in (("tax_year_2025_payments", 2025),
                           ("tax_year_2024_payments_after_filing", 2024)):
        for t in ftb.get(year_key, []):
            cur.execute(
                "INSERT INTO agency_records (agency, record_type, as_of, tx_date, description, "
                "amount, tax_year, details) VALUES ('FTB','payment',%s,%s,%s,%s,%s,%s)",
                (ftb["as_of"], t["date"], t.get("note", "Payment"), t["amount"], year,
                 Jsonb({"note": t["note"]}) if t.get("note") else None),
            )
    for n in ar["notices"]:
        cur.execute(
            "INSERT INTO agency_records (agency, record_type, tx_date, code, description, "
            "tax_year, details) VALUES (%s,'notice',%s,%s,%s,%s,%s)",
            ("IRS" if n["agency"] == "IRS" else "FTB", n["dated"], n["id"], n["type"],
             n["tax_year"], Jsonb(n)),
        )
    for e in ar["efile"]:
        cur.execute(
            "INSERT INTO agency_records (agency, record_type, tx_date, code, description, "
            "tax_year, details) VALUES (%s,'efile',%s,%s,%s,2025,%s)",
            ("IRS" if e["jurisdiction"] == "federal" else "FTB", e["date"][:10], e["status"],
             f"{e['jurisdiction']} e-file {e['status']}", Jsonb(e)),
        )

    # 11. Timeline (detail masked: it contains e-signature PINs).
    for t in p["timeline"]:
        cur.execute("INSERT INTO timeline VALUES (%s,%s,%s,%s,%s,%s)",
                    (t["id"], t["at"], t["event"], t.get("actor"), mask(t.get("detail")),
                     t.get("refs") or []))

    # 12. Assets + depreciation in long format (one row per asset/year/system).
    assets = {}
    for a in p["prior_years"]["asset_records"]:
        assets[a["asset_id"]] = a
    v3 = next(v for v in p["return_versions"] if v["version"] == "v3")
    for a in v3["assets"]:
        assets.setdefault(a["asset_id"], {}).update({k: v for k, v in a.items() if k not in ("federal", "california", "amt")})
    for asset_id, a in assets.items():
        cur.execute(
            "INSERT INTO assets VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (asset_id, a["description"], a.get("activity"), a.get("cost"),
             a.get("land_value", a.get("land_value_not_depreciated")), a.get("placed_in_service"),
             a.get("method"), a.get("life_years"),
             Jsonb(a["disposed"]) if a.get("disposed") else None),
        )
    for a in p["prior_years"]["asset_records"]:
        for system in ("federal", "california"):
            for year, amount in (a.get(system) or {}).items():
                cur.execute("INSERT INTO asset_depreciation VALUES (%s,%s,%s,%s,'prior_years')",
                            (a["asset_id"], int(year), system, amount))
    for a in v3["assets"]:
        for system in ("federal", "california", "amt"):
            amount = (a.get(system) or {}).get("depreciation_2025")
            if amount is not None:
                cur.execute("INSERT INTO asset_depreciation VALUES (%s,2025,%s,%s,'v3')",
                            (a["asset_id"], system, amount))

    # 13. Firm settings, deadlines, starting assignments, user_seen.
    cur.execute("INSERT INTO settings (key, value) VALUES ('firm_standards', %s)",
                (Jsonb(p["firm"]["starter_standards"]),))
    for dl in p["firm"]["deadlines"]:
        what = dl["what"]
        kind = ("outside_engagement" if "outside engagement" in what
                else "internal" if what.startswith("Internal") else "filing")
        cur.execute("INSERT INTO deadlines (what, due_date, kind) VALUES (%s, %s, %s)",
                    (what, dl["date"], kind))
    start = p["firm"]["assignment_at_start"]
    work_started = next((t["at"] for t in p["timeline"] if t["event"] == "work_started"),
                        datetime.now(timezone.utc).isoformat())
    admin = next(s["id"] for s in p["firm"]["staff"] if s["role"] == "firm_administrator")
    for area_id, _ in AREAS:
        levels = ["partner"] if area_id == "partner_review" else ["preparer", "reviewer", "partner"]
        for level in levels:
            cur.execute(
                "INSERT INTO assignments (area_id, level, user_id, assigned_by, started_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (area_id, level, start[level], admin, work_started),
            )
    cur.execute("INSERT INTO user_seen (user_id) SELECT id FROM users")

    # 14. Findings from the offline sweep.
    seed = json.loads(findings_path.read_text())
    for f in seed["findings"]:
        detail = f["detail"]
        extras = {k: f[k] for k in ("payment_effect_federal", "payment_effect_ca") if k in f}
        if extras:
            detail += " Payment effect: " + json.dumps(extras)
        cur.execute(
            "INSERT INTO findings (id, check_id, title, detail, area_id, evidence_refs, "
            "est_federal, est_ca, found_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (f["id"], f["check_id"], f["title"], detail, f["area_id"], f["evidence_refs"],
             f["est_federal"], f["est_ca"], seed["found_by"]),
        )

    # 15. The load itself is the first event in the history.
    cur.execute(
        "INSERT INTO events (actor_id, type, ref, payload) VALUES (%s, 'packet.loaded', %s, %s)",
        (admin, f"packet:{p['packet']['client_id']}",
         Jsonb({"sha256": sha, "findings_seeded": len(seed["findings"])})),
    )


def report(conn: psycopg.Connection) -> None:
    checks = [
        ("documents", "SELECT count(*) FROM documents", 74),
        ("pages", "SELECT count(*) FROM pages", None),
        ("extracted values", "SELECT count(*) FROM extracted_values", 3012),
        ("return lines v3", "SELECT count(*) FROM return_lines WHERE version = 'v3'", 627),
        ("return lines 2024", "SELECT count(*) FROM return_lines WHERE version = '2024'", None),
        ("line sources (all versions)", "SELECT count(*) FROM line_sources", None),
        ("line inputs (all versions)", "SELECT count(*) FROM line_inputs", None),
        ("client communications", "SELECT count(*) FROM client_communications", 56),
        ("users", "SELECT count(*) FROM users", 8),
        ("findings", "SELECT count(*) FROM findings", None),
        ("unmasked SSNs left in page text",
         r"SELECT count(*) FROM pages WHERE printed_content ~ '\d{3}-\d{2}-\d{4}'", 0),
    ]
    print("\nLoad report")
    ok = True
    for name, sql, expected in checks:
        n = conn.execute(sql).fetchone()[0]
        flag = "" if expected is None else ("  ok" if n == expected else f"  EXPECTED {expected}")
        ok &= expected is None or n == expected
        print(f"  {name:32s} {n:>6}{flag}")
    print("All checks passed." if ok else "Some checks FAILED.")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("packet", type=Path)
    parser.add_argument("--findings", type=Path, default=Path("data/findings_seed.json"))
    parser.add_argument("--reset", action="store_true", help="empty all tables first")
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL_UNPOOLED (direct Neon connection) or DATABASE_URL.")
    raw_bytes = args.packet.read_bytes()

    # One transaction: either everything loads or nothing does.
    with psycopg.connect(url) as conn:
        if args.reset:
            conn.execute("TRUNCATE " + ", ".join(ALL_TABLES) + " RESTART IDENTITY CASCADE")
        elif conn.execute("SELECT count(*) FROM packet_raw").fetchone()[0]:
            sys.exit("Packet already loaded. Re-run with --reset to rebuild from scratch.")
        load(conn, raw_bytes, args.findings)
    with psycopg.connect(url) as conn:
        report(conn)


if __name__ == "__main__":
    main()
