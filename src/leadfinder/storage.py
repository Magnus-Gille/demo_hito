from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from leadfinder.models import AggregatedLead, ContactInfo


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect_db(path: str) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma foreign_keys = on")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        create table if not exists runs (
          id integer primary key,
          started_at text not null,
          finished_at text,
          query_count integer not null default 0,
          result_count integer not null default 0
        );

        create table if not exists leads (
          id integer primary key,
          company_key text not null unique,
          company_name text not null,
          linkedin_url text,
          website text,
          best_source_url text,
          employee_band text,
          revenue_band text,
          industry text,
          location text,
          score real not null default 0,
          recent_news text not null default '[]',
          job_postings text not null default '[]',
          trigger_keywords text not null,
          notes text not null,
          created_at text not null,
          updated_at text not null,
          last_seen_at text not null
        );

        create table if not exists contacts (
          id integer primary key,
          lead_id integer not null references leads(id) on delete cascade,
          name text,
          role text,
          email text,
          phone text,
          linkedin_url text,
          created_at text not null,
          updated_at text not null,
          unique(lead_id, name, role)
        );

        create table if not exists evidence (
          id integer primary key,
          run_id integer not null references runs(id) on delete cascade,
          lead_id integer not null references leads(id) on delete cascade,
          provider text not null,
          query text not null,
          rank integer not null,
          title text not null,
          snippet text not null,
          url text not null,
          score real not null,
          discovered_at text not null,
          unique(run_id, url)
        );
        """
    )
    # Migrate existing databases that lack the new columns
    _migrate_add_columns(connection)
    connection.commit()


def _migrate_add_columns(connection: sqlite3.Connection) -> None:
    """Add columns that may be missing from older databases."""
    existing = {
        row[1]
        for row in connection.execute("pragma table_info(leads)").fetchall()
    }
    migrations = {
        "website": "text",
        "industry": "text",
        "location": "text",
        "recent_news": "text not null default '[]'",
        "job_postings": "text not null default '[]'",
    }
    for col, col_type in migrations.items():
        if col not in existing:
            connection.execute(f"alter table leads add column {col} {col_type}")


def start_run(connection: sqlite3.Connection) -> int:
    cursor = connection.execute(
        "insert into runs (started_at, query_count, result_count) values (?, 0, 0)",
        (utc_now(),),
    )
    connection.commit()
    return int(cursor.lastrowid)


def finish_run(connection: sqlite3.Connection, run_id: int, query_count: int, result_count: int) -> None:
    connection.execute(
        """
        update runs
        set finished_at = ?, query_count = ?, result_count = ?
        where id = ?
        """,
        (utc_now(), query_count, result_count, run_id),
    )
    connection.commit()


def persist_aggregated_lead(
    connection: sqlite3.Connection,
    run_id: int,
    lead: AggregatedLead,
) -> None:
    existing = connection.execute(
        "select * from leads where company_key = ?",
        (lead.company_key,),
    ).fetchone()
    now = utc_now()
    trigger_keywords = sorted(lead.trigger_keywords)
    notes = sorted(lead.notes)

    if existing is None:
        cursor = connection.execute(
            """
            insert into leads (
              company_key, company_name, linkedin_url, website,
              best_source_url, employee_band, revenue_band,
              industry, location, score,
              recent_news, job_postings,
              trigger_keywords, notes,
              created_at, updated_at, last_seen_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lead.company_key,
                lead.company_name,
                lead.linkedin_url,
                lead.website,
                lead.best_source_url,
                lead.employee_band,
                lead.revenue_band,
                lead.industry,
                lead.location,
                lead.score,
                json.dumps(lead.recent_news),
                json.dumps(lead.job_postings),
                json.dumps(trigger_keywords),
                json.dumps(notes),
                now, now, now,
            ),
        )
        lead_id = int(cursor.lastrowid)
    else:
        merged_keywords = sorted(set(json.loads(existing["trigger_keywords"])) | set(trigger_keywords))
        merged_notes = sorted(set(json.loads(existing["notes"])) | set(notes))
        merged_news = sorted(set(json.loads(existing["recent_news"])) | set(lead.recent_news))
        merged_jobs = sorted(set(json.loads(existing["job_postings"])) | set(lead.job_postings))
        connection.execute(
            """
            update leads
            set company_name = ?,
                linkedin_url = coalesce(?, linkedin_url),
                website = coalesce(?, website),
                best_source_url = coalesce(?, best_source_url),
                employee_band = coalesce(?, employee_band),
                revenue_band = coalesce(?, revenue_band),
                industry = coalesce(?, industry),
                location = coalesce(?, location),
                score = ?,
                recent_news = ?,
                job_postings = ?,
                trigger_keywords = ?,
                notes = ?,
                updated_at = ?,
                last_seen_at = ?
            where id = ?
            """,
            (
                longer_name(existing["company_name"], lead.company_name),
                lead.linkedin_url,
                lead.website,
                lead.best_source_url,
                lead.employee_band,
                lead.revenue_band,
                lead.industry,
                lead.location,
                max(float(existing["score"]), lead.score),
                json.dumps(merged_news),
                json.dumps(merged_jobs),
                json.dumps(merged_keywords),
                json.dumps(merged_notes),
                now, now,
                int(existing["id"]),
            ),
        )
        lead_id = int(existing["id"])

    # Persist contacts
    for contact in lead.contacts:
        _persist_contact(connection, lead_id, contact, now)

    # Persist evidence
    for hit, signal in lead.hits:
        connection.execute(
            """
            insert or ignore into evidence (
              run_id, lead_id, provider, query, rank,
              title, snippet, url, score, discovered_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, lead_id, hit.provider, hit.query, hit.rank,
                hit.title, hit.snippet, hit.url, signal.score, now,
            ),
        )

    connection.commit()


def _persist_contact(
    connection: sqlite3.Connection,
    lead_id: int,
    contact: ContactInfo,
    now: str,
) -> None:
    existing = connection.execute(
        "select id from contacts where lead_id = ? and name = ? and role = ?",
        (lead_id, contact.name, contact.role),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            insert into contacts (lead_id, name, role, email, phone, linkedin_url, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (lead_id, contact.name, contact.role, contact.email, contact.phone,
             contact.linkedin_url, now, now),
        )
    else:
        connection.execute(
            """
            update contacts
            set email = coalesce(?, email),
                phone = coalesce(?, phone),
                linkedin_url = coalesce(?, linkedin_url),
                updated_at = ?
            where id = ?
            """,
            (contact.email, contact.phone, contact.linkedin_url, now, existing["id"]),
        )


def fetch_top_leads(connection: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return connection.execute(
        """
        select company_name, score, employee_band, revenue_band,
               industry, location, linkedin_url, website, best_source_url,
               recent_news, job_postings
        from leads
        order by score desc, updated_at desc
        limit ?
        """,
        (limit,),
    ).fetchall()


def fetch_contacts_for_lead(connection: sqlite3.Connection, company_key: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        select c.name, c.role, c.email, c.phone, c.linkedin_url
        from contacts c
        join leads l on l.id = c.lead_id
        where l.company_key = ?
        """,
        (company_key,),
    ).fetchall()


def export_leads_csv(connection: sqlite3.Connection, output_path: str, limit: int = 200) -> int:
    """Export top leads to a GitHub-friendly CSV for easy review."""
    rows = connection.execute(
        """
        select
          l.company_name, l.score, l.employee_band, l.revenue_band,
          l.industry, l.location, l.linkedin_url, l.website,
          l.trigger_keywords, l.recent_news, l.job_postings,
          l.created_at, l.updated_at
        from leads l
        order by l.score desc, l.updated_at desc
        limit ?
        """,
        (limit,),
    ).fetchall()

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(
            f,
            delimiter=",",
            quotechar='"',
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        )
        writer.writerow([
            "Company", "Score", "Employee band", "Revenue band", "Industry",
            "Location", "LinkedIn", "Website", "Triggers", "Recent news",
            "Job postings", "Created at", "Updated at",
        ])
        for row in rows:
            writer.writerow([
                row["company_name"],
                f"{row['score']:.1f}",
                row["employee_band"] or "",
                row["revenue_band"] or "",
                row["industry"] or "",
                row["location"] or "",
                row["linkedin_url"] or "",
                row["website"] or "",
                flatten_json_text_list(row["trigger_keywords"]),
                flatten_json_text_list(row["recent_news"]),
                flatten_json_text_list(row["job_postings"]),
                row["created_at"],
                row["updated_at"],
            ])
    return len(rows)


def flatten_json_text_list(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value
    if not isinstance(parsed, list):
        return str(parsed)
    return " | ".join(str(item) for item in parsed if item)


def longer_name(existing: str, candidate: str) -> str:
    return candidate if len(candidate) > len(existing) else existing
