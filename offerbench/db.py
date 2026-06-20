import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from offerbench import config

_SCHEMA_SQL = (config.REPO_ROOT / "offerbench" / "schema.sql").read_text()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate_if_needed(conn: sqlite3.Connection) -> None:
    """One-off migration: older schema versions had extracted_offers without
    offer_index (and a UNIQUE(topic_id, extraction_version) constraint that
    would block multi-offer rows even if the column were just added). If
    detected, drop and let the schema script below recreate it fresh."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(extracted_offers)").fetchall()}
    if cols and "offer_index" not in cols:
        conn.execute("DROP VIEW IF EXISTS current_offers")
        conn.execute("DROP TABLE IF EXISTS extracted_offers")
        conn.commit()


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    _migrate_if_needed(conn)
    conn.executescript(_SCHEMA_SQL)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def raw_post_exists(topic_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM raw_posts WHERE topic_id = ?", (str(topic_id),)
        ).fetchone()
        return row is not None


def upsert_raw_post_list_fields(node: dict) -> None:
    author = node.get("author") or {}
    tags = node.get("tags") or []
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO raw_posts (
                topic_id, uuid, slug, title, summary,
                author_username, author_realname, is_anonymous,
                created_at, updated_at, hit_count, tags_json,
                raw_list_json, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic_id) DO NOTHING
            """,
            (
                str(node["topicId"]),
                node.get("uuid"),
                node.get("slug"),
                node.get("title"),
                node.get("summary"),
                author.get("userName"),
                author.get("realName"),
                1 if node.get("isAnonymous") else 0,
                node.get("createdAt"),
                node.get("updatedAt"),
                node.get("hitCount"),
                json.dumps(tags),
                json.dumps(node),
                _now(),
            ),
        )


def topic_ids_missing_detail() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT topic_id FROM raw_posts WHERE content IS NULL"
        ).fetchall()
        return [r["topic_id"] for r in rows]


def update_raw_post_detail(topic_id: str, detail: dict) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE raw_posts
            SET content = ?, raw_detail_json = ?, detail_fetched_at = ?
            WHERE topic_id = ?
            """,
            (detail.get("content"), json.dumps(detail), _now(), str(topic_id)),
        )


def posts_needing_extraction(version: int, force: bool = False, limit: int | None = None):
    query = "SELECT * FROM raw_posts WHERE content IS NOT NULL"
    params: list = []
    if not force:
        query += (
            " AND topic_id NOT IN "
            "(SELECT topic_id FROM extracted_offers WHERE extraction_version = ?)"
        )
        params.append(version)
    query += " ORDER BY created_at"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    with connect() as conn:
        return conn.execute(query, params).fetchall()


def insert_extraction(
    topic_id: str,
    version: int,
    model: str,
    status: str,
    payload: dict | None,
    error: str | None = None,
    offer_index: int = 0,
) -> None:
    payload = payload or {}
    with connect() as conn:
        post = conn.execute(
            "SELECT slug, created_at, tags_json FROM raw_posts WHERE topic_id = ?",
            (str(topic_id),),
        ).fetchone()
        source_url = (
            f"https://leetcode.com/discuss/post/{topic_id}/{post['slug']}/"
            if post
            else None
        )
        conn.execute(
            """
            INSERT INTO extracted_offers (
                topic_id, offer_index, extraction_status, extraction_model, extraction_version,
                extracted_at, confidence, error_message,
                organization, role_title, level_grade, years_experience, location, post_kind,
                currency_raw, total_ctc_raw, fixed_base_raw, variable_bonus_raw,
                stock_rsu_raw, signing_bonus_raw, retirement_benefits_raw,
                total_ctc_inr_lakhs, total_ctc_usd,
                source_url, posted_at, tags_json, extraction_raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic_id, extraction_version, offer_index) DO UPDATE SET
                extraction_status=excluded.extraction_status,
                extraction_model=excluded.extraction_model,
                extracted_at=excluded.extracted_at,
                confidence=excluded.confidence,
                error_message=excluded.error_message,
                organization=excluded.organization,
                role_title=excluded.role_title,
                level_grade=excluded.level_grade,
                years_experience=excluded.years_experience,
                location=excluded.location,
                post_kind=excluded.post_kind,
                currency_raw=excluded.currency_raw,
                total_ctc_raw=excluded.total_ctc_raw,
                fixed_base_raw=excluded.fixed_base_raw,
                variable_bonus_raw=excluded.variable_bonus_raw,
                stock_rsu_raw=excluded.stock_rsu_raw,
                signing_bonus_raw=excluded.signing_bonus_raw,
                retirement_benefits_raw=excluded.retirement_benefits_raw,
                total_ctc_inr_lakhs=excluded.total_ctc_inr_lakhs,
                total_ctc_usd=excluded.total_ctc_usd,
                source_url=excluded.source_url,
                posted_at=excluded.posted_at,
                tags_json=excluded.tags_json,
                extraction_raw_json=excluded.extraction_raw_json
            """,
            (
                str(topic_id),
                offer_index,
                status,
                model,
                version,
                _now(),
                payload.get("confidence"),
                error,
                payload.get("organization"),
                payload.get("role_title"),
                payload.get("level_grade"),
                payload.get("years_experience"),
                payload.get("location"),
                payload.get("post_kind"),
                payload.get("currency"),
                payload.get("total_ctc"),
                payload.get("fixed_base"),
                payload.get("variable_bonus"),
                payload.get("stock_rsu"),
                payload.get("signing_bonus"),
                payload.get("retirement_benefits"),
                payload.get("total_ctc_inr_lakhs"),
                payload.get("total_ctc_usd"),
                source_url,
                post["created_at"] if post else None,
                post["tags_json"] if post else None,
                json.dumps(payload),
            ),
        )


def status_counts() -> dict:
    with connect() as conn:
        raw_total = conn.execute("SELECT COUNT(*) c FROM raw_posts").fetchone()["c"]
        missing_detail = conn.execute(
            "SELECT COUNT(*) c FROM raw_posts WHERE content IS NULL"
        ).fetchone()["c"]
        extracted_total = conn.execute(
            "SELECT COUNT(*) c FROM current_offers"
        ).fetchone()["c"]
        by_status = conn.execute(
            "SELECT extraction_status, COUNT(*) c FROM current_offers GROUP BY extraction_status"
        ).fetchall()
        return {
            "raw_posts": raw_total,
            "missing_detail": missing_detail,
            "extracted_total": extracted_total,
            "by_status": {r["extraction_status"]: r["c"] for r in by_status},
        }


def query_current_offers(filters: dict) -> list[sqlite3.Row]:
    clauses = []
    params: list = []

    if filters.get("role"):
        clauses.append("role_title LIKE ?")
        params.append(f"%{filters['role']}%")
    if filters.get("organization"):
        clauses.append("organization LIKE ?")
        params.append(f"%{filters['organization']}%")
    if filters.get("location"):
        clauses.append("location LIKE ?")
        params.append(f"%{filters['location']}%")
    if filters.get("post_kind"):
        clauses.append("post_kind = ?")
        params.append(filters["post_kind"])
    if filters.get("currency"):
        clauses.append("currency_raw = ?")
        params.append(filters["currency"])
    if filters.get("min_ctc_lakhs") is not None:
        clauses.append("total_ctc_inr_lakhs >= ?")
        params.append(filters["min_ctc_lakhs"])
    if filters.get("max_ctc_lakhs") is not None:
        clauses.append("total_ctc_inr_lakhs <= ?")
        params.append(filters["max_ctc_lakhs"])
    if not filters.get("include_no_data"):
        clauses.append("extraction_status != 'no_data'")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sort = filters.get("sort", "posted_at_desc")
    order_by = {
        "posted_at_desc": "posted_at DESC",
        "ctc_desc": "total_ctc_inr_lakhs DESC",
        "ctc_asc": "total_ctc_inr_lakhs ASC",
    }.get(sort, "posted_at DESC")

    with connect() as conn:
        return conn.execute(
            f"SELECT * FROM current_offers {where} ORDER BY {order_by} LIMIT 500", params
        ).fetchall()


def get_offer_detail(topic_id: str):
    with connect() as conn:
        post = conn.execute(
            "SELECT * FROM raw_posts WHERE topic_id = ?", (str(topic_id),)
        ).fetchone()
        offers = conn.execute(
            "SELECT * FROM current_offers WHERE topic_id = ? ORDER BY offer_index",
            (str(topic_id),),
        ).fetchall()
        return post, offers
