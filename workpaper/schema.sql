-- =====================================================================
-- Miraflores workpaper schema
--
-- Two layers:
--   PACKET LAYER  loaded once from the JSON, never updated by the app.
--   HUMAN LAYER   everything people do. History tables only grow.
--
-- A "ref" is one text address for anything a note, finding, attachment
-- or verification can point at. It reuses the packet's own formats:
--   line:v3:F1040.1a   ev:ev-0498   doc:D11#page2   qa:qa-25   msg:msg-07
--   asset:SAC-BLDG     py:/carryovers_into_2025/capital_loss_short
-- The API validates refs (the database cannot: a ref can point at any table).
-- =====================================================================


-- ---------------------------------------------------------------------
-- PACKET LAYER
-- ---------------------------------------------------------------------

-- The packet exactly as delivered, kept as proof. It contains SSNs and
-- account numbers, so it is stored ENCRYPTED, plus a SHA-256 of the
-- original bytes so anyone can verify it was never altered.
CREATE TABLE packet_raw (
    client_id        text PRIMARY KEY,            -- CL-20417
    content_enc      bytea       NOT NULL,        -- encrypted original file
    sha256           text        NOT NULL,        -- fingerprint of the original
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

-- Small read-whole sections with no sensitive data: readme, engine
-- reference, what-ifs, planning reference, post-filing rates, fx rates.
-- JSONB because the app reads each one whole and never joins on them.
CREATE TABLE packet_sections (
    name             text PRIMARY KEY,            -- 'engine_reference', 'what_if', ...
    content          jsonb NOT NULL
);

-- Review areas = the firm's 9 budget areas. Lines, sign-offs, decisions
-- and time all hang off these, so "time against budget" comes for free.
CREATE TABLE areas (
    id               text PRIMARY KEY,            -- 'wages_and_stock_compensation'
    name             text NOT NULL,
    budget_hours     numeric(5,2) NOT NULL,
    sort_order       smallint NOT NULL
);

-- Staff and client users. Keys are the packet's IDs (st-01, cu-01) so the
-- audit trail reads the same as the packet.
CREATE TABLE users (
    id                    text PRIMARY KEY,
    name                  text NOT NULL,
    role                  text NOT NULL CHECK (role IN
                              ('preparer','reviewer','partner','firm_administrator',
                               'quality_reviewer','client')),
    credential            text,
    sensitive_clearance   boolean NOT NULL DEFAULT false,
    active_from           date
);

-- Household members. Sensitive fields are split three ways:
--   *_enc    encrypted full value (decrypt only on a logged unmask)
--   *_last4  plain, for display:  ***-**-3390
--   *_hmac   keyed fingerprint, to compare two SSNs without decrypting
CREATE TABLE household_people (
    id                    text PRIMARY KEY,       -- 'ngozi', 'theo'
    role                  text NOT NULL,          -- taxpayer | spouse | dependent
    name                  text NOT NULL,
    dob                   date,
    relationship          text,
    months_lived_with_you smallint,
    full_time_student     boolean,
    ssn_enc               bytea,
    ssn_last4             char(4),
    ssn_hmac              text,
    ip_pin_enc            bytea
);

CREATE TABLE documents (
    id                 text PRIMARY KEY,          -- D01..D74
    title              text NOT NULL,
    document_type      text NOT NULL,
    issuer             text,
    belongs_to         text NOT NULL,             -- taxpayer | spouse | joint | dependent:<id>
    tax_year           smallint,
    received_at        timestamptz NOT NULL,
    uploaded_by        text NOT NULL,
    file_name          text,
    page_count         smallint NOT NULL,
    marked_corrected   boolean NOT NULL DEFAULT false,
    extraction_status  text NOT NULL CHECK (extraction_status IN
                           ('extracted','partial','not_extracted')),
    extraction_reason  text
);

-- One row per page. The simulated document view renders printed_content.
-- A real scanned page could later be added as an image column here
-- without changing anything that points at (document_id, page).
CREATE TABLE pages (
    document_id      text     NOT NULL REFERENCES documents(id),
    page             smallint NOT NULL,
    printed_content  text     NOT NULL,
    PRIMARY KEY (document_id, page)
);

-- Every value the pipeline read. "value" is JSONB because its type varies
-- (money, date, text, boolean). value_num is a plain number copy for
-- money/integer/quantity/percent, so checks can do math with SQL.
-- SSN and account-number values are stored encrypted (value is NULL).
CREATE TABLE extracted_values (
    id             text PRIMARY KEY,              -- ev-0001
    document_id    text     NOT NULL,
    page           smallint NOT NULL,
    field          text     NOT NULL,             -- issuer's box/field name
    label          text     NOT NULL,
    value          jsonb,
    value_num      numeric(14,2),
    value_enc      bytea,
    value_type     text     NOT NULL,
    text_as_read   text,
    position       jsonb,                         -- {x0,y0,x1,y1} for highlights
    confidence     numeric(3,2) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    FOREIGN KEY (document_id, page) REFERENCES pages(document_id, page)
);
CREATE INDEX extracted_values_document_idx ON extracted_values(document_id);

-- One row per computed return: '2024' (prior year as filed), 'v1','v2','v3'.
-- Prior year lives here too, so "this year vs last year" is the same query
-- as "v2 vs v3".
CREATE TABLE return_versions (
    version              text PRIMARY KEY,
    computed_at          timestamptz,
    trigger              text,
    summary              jsonb,
    tax_effect_rates     jsonb,                   -- per-dollar rates by category
    diagnostics          jsonb,                   -- engine's own warnings
    documents_used       text[],
    documents_superseded text[]
);

CREATE TABLE return_lines (
    version        text NOT NULL REFERENCES return_versions(version),
    key            text NOT NULL,                 -- F1040.11, SchE.21A, F8949.B.N1
    jurisdiction   text NOT NULL CHECK (jurisdiction IN ('federal','california')),
    form           text NOT NULL,
    line           text NOT NULL,
    label          text,
    value_num      numeric(14,2),                 -- numeric lines
    value_text     text,                          -- 'Yes', dates, ratios as text
    rule           text,                          -- engine rule id
    note           text,
    area_id        text REFERENCES areas(id),     -- set by the loader's mapping
    PRIMARY KEY (version, key)
);
CREATE INDEX return_lines_area_idx ON return_lines(version, area_id);

-- Line -> line links ("F1040.11 is built from F1040.9 and F1040.10").
-- A separate table, not an array, so we can walk the map BOTH ways:
-- down (what built this?) and up (what does this feed?).
CREATE TABLE line_inputs (
    version     text NOT NULL,
    key         text NOT NULL,
    input_key   text NOT NULL,
    PRIMARY KEY (version, key, input_key),
    FOREIGN KEY (version, key)       REFERENCES return_lines(version, key),
    FOREIGN KEY (version, input_key) REFERENCES return_lines(version, key)
);
CREATE INDEX line_inputs_reverse_idx ON line_inputs(version, input_key);

-- Line -> evidence links. A source can be an extracted value, a prior-year
-- pointer, an asset, a questionnaire answer or a parameter, so it is a ref.
-- When it IS an extracted value, ev_id is filled in too: that gives a real
-- foreign key and makes "document -> every line it landed on" one join.
CREATE TABLE line_sources (
    version      text NOT NULL,
    key          text NOT NULL,
    source_ref   text NOT NULL,
    ev_id        text REFERENCES extracted_values(id),
    PRIMARY KEY (version, key, source_ref),
    FOREIGN KEY (version, key) REFERENCES return_lines(version, key)
);
CREATE INDEX line_sources_ev_idx ON line_sources(ev_id);

-- Questionnaire answers, messages and call notes in one table: each one is
-- "the client told us X", and findings cite them the same way (qa-25, msg-07).
CREATE TABLE client_communications (
    id            text PRIMARY KEY,               -- qa-25, msg-07, call-01
    kind          text NOT NULL CHECK (kind IN ('questionnaire','message','call_note')),
    at            timestamptz,
    author        text,
    recipient     text,
    question      text,                           -- questionnaire only
    body          text NOT NULL,                  -- answer, message text, or notes joined
    participants  text[]
);

-- IRS transcript lines, FTB payments, e-file results, notices: the outside
-- records that payments and filings are reconciled against.
CREATE TABLE agency_records (
    id            bigserial PRIMARY KEY,
    agency        text NOT NULL CHECK (agency IN ('IRS','FTB')),
    record_type   text NOT NULL CHECK (record_type IN
                      ('transcript','payment','efile','notice')),
    as_of         date,                           -- snapshot date for transcripts
    tx_date       date,
    code          text,                           -- IRS 670, 150, ... or e-file code
    description   text,
    amount        numeric(14,2),
    tax_year      smallint,
    details       jsonb                           -- errors, notice items, notes
);

-- The scripted season events from the packet (engagement signed ... 2028 letter).
CREATE TABLE timeline (
    id        text PRIMARY KEY,                   -- tl-04, extension-2026-04-14
    at        timestamptz NOT NULL,
    event     text NOT NULL,
    actor_id  text REFERENCES users(id),
    detail    text,
    refs      text[]
);

-- Assets, with depreciation in LONG format: one row per asset, year and
-- system. Long format makes "depreciation by asset, federal vs California
-- vs AMT, by year" a simple filter instead of parsing nested JSON.
CREATE TABLE assets (
    id                 text PRIMARY KEY,          -- SAC-BLDG
    description        text NOT NULL,
    activity           text,
    cost               numeric(14,2),
    land_value         numeric(14,2),
    placed_in_service  date,
    method             text,
    life_years         numeric(5,2),
    disposed           jsonb
);

CREATE TABLE asset_depreciation (
    asset_id   text NOT NULL REFERENCES assets(id),
    tax_year   smallint NOT NULL,
    system     text NOT NULL CHECK (system IN ('federal','california','amt')),
    amount     numeric(14,2) NOT NULL,
    source     text NOT NULL,                     -- 'prior_years' or 'v3'
    PRIMARY KEY (asset_id, tax_year, system)
);


-- ---------------------------------------------------------------------
-- HUMAN LAYER
-- ---------------------------------------------------------------------

-- Every action, in order. Rows are only ever added (see the trigger below).
-- Powers: audit trail, "changed since I last looked", live updates.
CREATE TABLE events (
    id           bigserial PRIMARY KEY,
    occurred_at  timestamptz NOT NULL DEFAULT now(),
    actor_id     text NOT NULL REFERENCES users(id),
    type         text NOT NULL,                   -- 'adjustment.created', 'signoff.reopened'
    ref          text,
    payload      jsonb NOT NULL DEFAULT '{}'      -- never contains sensitive values
);
CREATE INDEX events_ref_idx ON events(ref);

-- Number changes. The engine's value stays in return_lines untouched;
-- the screen shows the latest approved adjustment if one exists.
-- Undo = a new adjustment that reverses an earlier one.
CREATE TABLE adjustments (
    id              bigserial PRIMARY KEY,
    version         text NOT NULL,
    line_key        text NOT NULL,
    original_value  numeric(14,2),
    new_value       numeric(14,2) NOT NULL,
    reason          text NOT NULL CHECK (length(trim(reason)) > 0),
    effect_federal  numeric(14,2),                -- change x rate
    effect_ca       numeric(14,2),
    status          text NOT NULL CHECK (status IN
                        ('pending_review','needs_partner','approved','rejected')),
    created_by      text NOT NULL REFERENCES users(id),
    approved_by     text REFERENCES users(id),
    reverses_id     bigint REFERENCES adjustments(id),
    filing_id       bigint,                       -- set when part of an amendment
    finding_id      text,                         -- set when it came from a finding
    created_at      timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (version, line_key) REFERENCES return_lines(version, key),
    CHECK (approved_by IS NULL OR approved_by <> created_by)   -- no self-approval
);

-- Results of the independent checks (rules and AI).
CREATE TABLE findings (
    id                 text PRIMARY KEY,          -- F-001
    check_id           text NOT NULL,             -- 'duplicate_payer', 'ai_included_elsewhere'
    title              text NOT NULL,
    detail             text,
    area_id            text REFERENCES areas(id),
    evidence_refs      text[] NOT NULL,
    est_federal        numeric(14,2),
    est_ca             numeric(14,2),
    found_by           text NOT NULL,             -- 'rule:duplicate_payer' or 'ai:<model>@<date>'
    status             text NOT NULL DEFAULT 'open' CHECK (status IN
                           ('open','accepted','dismissed')),
    resolution_reason  text,
    resolved_by        text REFERENCES users(id),
    resolved_at        timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    CHECK (status = 'open' OR resolution_reason IS NOT NULL)  -- closing needs a reason
);
ALTER TABLE adjustments
    ADD FOREIGN KEY (finding_id) REFERENCES findings(id);

-- Review notes, colleague questions, client questions. Threads via parent_id.
CREATE TABLE notes (
    id             bigserial PRIMARY KEY,
    ref            text NOT NULL,
    kind           text NOT NULL CHECK (kind IN
                       ('review_note','colleague_question','client_question','reply')),
    body           text NOT NULL,
    author_id      text NOT NULL REFERENCES users(id),
    assignee_id    text REFERENCES users(id),
    blocks_filing  boolean NOT NULL DEFAULT false,
    status         text NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
    parent_id      bigint REFERENCES notes(id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    resolved_by    text REFERENCES users(id),
    resolved_at    timestamptz
);
CREATE INDEX notes_open_blocking_idx ON notes(status) WHERE blocks_filing;

-- Judgments, elections, due diligence and penalty choices: same shape.
-- authority is NOT NULL because the firm rule says every judgment records it.
CREATE TABLE decisions (
    id              bigserial PRIMARY KEY,
    kind            text NOT NULL CHECK (kind IN
                        ('judgment','election','due_diligence','penalty')),
    area_id         text REFERENCES areas(id),
    question        text NOT NULL,
    options         jsonb NOT NULL,               -- [{label, effect_federal, effect_ca}]
    chosen          text  NOT NULL,
    rationale       text  NOT NULL,
    authority       text  NOT NULL,
    checklist       jsonb,                        -- due diligence answers
    refs            text[] NOT NULL DEFAULT '{}',
    effect_federal  numeric(14,2),
    effect_ca       numeric(14,2),
    decided_by      text NOT NULL REFERENCES users(id),
    approved_by     text REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (approved_by IS NULL OR approved_by <> decided_by)
);

-- "Agreed to source document", "confirmed with client", ...
-- method is NOT a CHECK list: the firm admin can edit the allowed types,
-- so the API validates it against settings instead.
CREATE TABLE verifications (
    id             bigserial PRIMARY KEY,
    ref            text NOT NULL,
    method         text NOT NULL,
    evidence_refs  text[] NOT NULL DEFAULT '{}',
    verified_by    text NOT NULL REFERENCES users(id),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX verifications_ref_idx ON verifications(ref);

-- Approvals. fingerprint = hash of the current values of covered_refs at
-- signing. If it no longer matches, the sign-off is reopened.
-- Client approval is a row with level 'client' and area_id NULL (whole return).
CREATE TABLE signoffs (
    id                 bigserial PRIMARY KEY,
    area_id            text REFERENCES areas(id),
    level              text NOT NULL CHECK (level IN
                           ('preparer','reviewer','partner','client')),
    user_id            text NOT NULL REFERENCES users(id),
    covered_refs       text[] NOT NULL,
    fingerprint        text   NOT NULL,
    status             text   NOT NULL DEFAULT 'valid' CHECK (status IN ('valid','reopened')),
    reopened_event_id  bigint REFERENCES events(id),
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- Extensions, originals and amendments. snapshot = every line value at the
-- moment of filing (a frozen photo, read whole, so JSONB is right here).
CREATE TABLE filings (
    id               bigserial PRIMARY KEY,
    jurisdiction     text NOT NULL CHECK (jurisdiction IN ('federal','california')),
    kind             text NOT NULL CHECK (kind IN ('extension','original','amendment')),
    status           text NOT NULL CHECK (status IN
                         ('draft','submitted','rejected','accepted')),
    submission_id    text,
    errors           jsonb,
    amount_paid      numeric(14,2),
    snapshot         jsonb,
    snapshot_sha256  text,
    submitted_by     text REFERENCES users(id),
    submitted_at     timestamptz,
    amends_id        bigint REFERENCES filings(id)
);
ALTER TABLE adjustments
    ADD FOREIGN KEY (filing_id) REFERENCES filings(id);

CREATE TABLE attachments (
    id           bigserial PRIMARY KEY,
    ref          text NOT NULL,
    file_name    text NOT NULL,
    mime_type    text NOT NULL,
    size_bytes   integer NOT NULL CHECK (size_bytes <= 5 * 1024 * 1024),
    content      bytea NOT NULL,
    uploaded_by  text NOT NULL REFERENCES users(id),
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Who unmasked what, and when. Deliberately NO value column.
CREATE TABLE view_log (
    id         bigserial PRIMARY KEY,
    user_id    text NOT NULL REFERENCES users(id),
    ref        text NOT NULL,
    viewed_at  timestamptz NOT NULL DEFAULT now()
);

-- Firm standards, deadlines, budget and other editable config.
-- Every change is also written to events, so standards have a history.
CREATE TABLE settings (
    key         text PRIMARY KEY,                 -- 'firm_standards', 'deadlines'
    value       jsonb NOT NULL,
    updated_by  text REFERENCES users(id),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Engagement deadlines (filing dates, internal hand-offs, outside filings).
-- A table, not settings JSON, because the inbox filters them by date:
-- "what is due in the next 7 days?"
CREATE TABLE deadlines (
    id         bigserial PRIMARY KEY,
    what       text NOT NULL,
    due_date   date NOT NULL,
    kind       text NOT NULL CHECK (kind IN ('filing','internal','outside_engagement')),
    area_id    text REFERENCES areas(id),             -- NULL = whole engagement
    done_at    timestamptz
);
CREATE INDEX deadlines_due_idx ON deadlines(due_date) WHERE done_at IS NULL;

-- Who owns which area, at which level. Ownership changes (Marcus joins on
-- 2026-03-24), and the audit trail must show who owned an area WHEN, so a
-- reassignment ends the old row and inserts a new one instead of editing it.
CREATE TABLE assignments (
    id            bigserial PRIMARY KEY,
    area_id       text NOT NULL REFERENCES areas(id),
    level         text NOT NULL CHECK (level IN ('preparer','reviewer','partner')),
    user_id       text NOT NULL REFERENCES users(id),
    due_date      date,
    assigned_by   text NOT NULL REFERENCES users(id),
    started_at    timestamptz NOT NULL DEFAULT now(),
    ended_at      timestamptz,
    CHECK (ended_at IS NULL OR ended_at > started_at)
);
-- At most ONE current owner per area and level. A partial unique index:
-- it only applies to rows where ended_at IS NULL, so history can hold
-- many past owners while the present can hold only one.
CREATE UNIQUE INDEX assignments_one_current_idx
    ON assignments(area_id, level) WHERE ended_at IS NULL;

-- Hours worked, compared with areas.budget_hours.
-- Unlike events, entries CAN be corrected (people mistype hours), but every
-- change is also written to events, so corrections are still traceable.
CREATE TABLE time_entries (
    id          bigserial PRIMARY KEY,
    user_id     text NOT NULL REFERENCES users(id),
    area_id     text NOT NULL REFERENCES areas(id),
    work_date   date NOT NULL,
    hours       numeric(4,2) NOT NULL CHECK (hours > 0 AND hours <= 24),
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX time_entries_area_idx ON time_entries(area_id);

-- Last event each user has seen: "what changed since I last looked".
CREATE TABLE user_seen (
    user_id        text PRIMARY KEY REFERENCES users(id),
    last_event_id  bigint NOT NULL DEFAULT 0
);


-- ---------------------------------------------------------------------
-- RULES THE DATABASE ENFORCES ITSELF
-- ---------------------------------------------------------------------

-- 1. History cannot be rewritten: events and view_log are insert-only.
CREATE FUNCTION forbid_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER events_append_only
    BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

CREATE TRIGGER view_log_append_only
    BEFORE UPDATE OR DELETE ON view_log
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

-- 2. Nothing can be adjusted once an accepted original return exists,
--    unless the adjustment belongs to an amendment.
CREATE FUNCTION forbid_adjust_after_filing() RETURNS trigger AS $$
BEGIN
    IF NEW.filing_id IS NULL AND EXISTS (
        SELECT 1 FROM filings WHERE kind = 'original' AND status = 'accepted'
    ) THEN
        RAISE EXCEPTION 'Return is filed and frozen: open an amendment to change it';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER adjustments_freeze
    BEFORE INSERT ON adjustments
    FOR EACH ROW EXECUTE FUNCTION forbid_adjust_after_filing();
