CREATE TABLE IF NOT EXISTS raw_posts (
    topic_id          TEXT PRIMARY KEY,
    uuid              TEXT NOT NULL,
    slug              TEXT NOT NULL,
    title             TEXT NOT NULL,
    content           TEXT,
    summary           TEXT,
    author_username   TEXT,
    author_realname   TEXT,
    is_anonymous      INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT,
    hit_count         INTEGER,
    tags_json         TEXT,
    raw_list_json     TEXT,
    raw_detail_json   TEXT,
    fetched_at        TEXT NOT NULL,
    detail_fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS extracted_offers (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id                TEXT NOT NULL REFERENCES raw_posts(topic_id),
    extraction_status       TEXT NOT NULL,
    extraction_model        TEXT NOT NULL,
    extraction_version      INTEGER NOT NULL,
    extracted_at            TEXT NOT NULL,
    confidence              REAL,
    error_message           TEXT,

    organization            TEXT,
    role_title              TEXT,
    level_grade             TEXT,
    years_experience        REAL,
    location                TEXT,
    post_kind               TEXT,

    currency_raw                TEXT,
    total_ctc_raw                REAL,
    fixed_base_raw                REAL,
    variable_bonus_raw            REAL,
    stock_rsu_raw                  REAL,
    signing_bonus_raw              REAL,
    retirement_benefits_raw        REAL,

    total_ctc_inr_lakhs     REAL,
    total_ctc_usd           REAL,

    source_url              TEXT,
    posted_at               TEXT,
    tags_json               TEXT,
    extraction_raw_json     TEXT NOT NULL,

    UNIQUE(topic_id, extraction_version)
);

CREATE INDEX IF NOT EXISTS idx_offers_topic  ON extracted_offers(topic_id);
CREATE INDEX IF NOT EXISTS idx_offers_org    ON extracted_offers(organization);
CREATE INDEX IF NOT EXISTS idx_offers_role   ON extracted_offers(role_title);
CREATE INDEX IF NOT EXISTS idx_offers_ctc    ON extracted_offers(total_ctc_inr_lakhs);

CREATE VIEW IF NOT EXISTS current_offers AS
SELECT eo.* FROM extracted_offers eo
WHERE eo.extraction_version = (
    SELECT MAX(extraction_version) FROM extracted_offers WHERE topic_id = eo.topic_id
);
