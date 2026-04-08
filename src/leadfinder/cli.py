from __future__ import annotations

import argparse
import time
from collections import OrderedDict

from leadfinder.scoring import aggregate_hits
from leadfinder.search import discovery_queries, enrichment_queries, search_web
from leadfinder.storage import (
    connect_db,
    export_leads_csv,
    fetch_top_leads,
    finish_run,
    init_db,
    persist_aggregated_lead,
    start_run,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lead Finder – hitta rekryteringskunder bland Stockholms techbolag"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Kör discovery och uppdatera databasen")
    run_parser.add_argument("--db", default="data/leads.db", help="Sökväg till SQLite-databas")
    run_parser.add_argument("--limit-per-query", type=int, default=5, help="Resultat per sökleverantör och fråga")
    run_parser.add_argument("--company-limit", type=int, default=15, help="Antal bolag att enricha efter discovery")
    run_parser.add_argument("--top", type=int, default=15, help="Antal leads att visa efter körning")
    run_parser.add_argument("--export-csv", default=None, help="Exportera till CSV efter körning")
    run_parser.add_argument("--delay", type=float, default=2.0, help="Fördröjning mellan sökningar (sekunder)")

    export_parser = subparsers.add_parser("export", help="Exportera leads till CSV")
    export_parser.add_argument("--db", default="data/leads.db", help="Sökväg till SQLite-databas")
    export_parser.add_argument("--output", default="data/leads_export.csv", help="Sökväg till CSV-fil")
    export_parser.add_argument("--limit", type=int, default=200, help="Max antal leads att exportera")

    top_parser = subparsers.add_parser("top", help="Visa topp-leads")
    top_parser.add_argument("--db", default="data/leads.db", help="Sökväg till SQLite-databas")
    top_parser.add_argument("--limit", type=int, default=15, help="Antal leads att visa")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run":
        return run_command(args)
    elif args.command == "export":
        return export_command(args)
    elif args.command == "top":
        return top_command(args)
    parser.error("Okänt kommando")
    return 2


def run_command(args: argparse.Namespace) -> int:
    connection = connect_db(args.db)
    init_db(connection)
    run_id = start_run(connection)

    queries_executed = 0
    all_hits = []

    print("=== Lead Finder – Stockholm Tech ===")
    print(f"Mål: 100-1000 anställda, 100 MSEK - 2 Mdr SEK omsättning")
    print()

    # Phase 1: Discovery
    print("▸ Fas 1: Discovery-sökning...")
    for query in discovery_queries():
        queries_executed += 1
        print(f"  Söker: {query[:70]}...")
        hits = search_web(query, limit_per_provider=args.limit_per_query)
        all_hits.extend(hits)
        print(f"    → {len(hits)} träffar")
        time.sleep(args.delay)

    # Phase 2: Select companies for enrichment
    initial_leads = aggregate_hits(all_hits)
    selected_companies = select_company_names(initial_leads, args.company_limit)
    print(f"\n▸ Fas 2: Enrichment av {len(selected_companies)} bolag...")

    for company_name in selected_companies:
        print(f"  Enrichar: {company_name}")
        for query in enrichment_queries(company_name):
            queries_executed += 1
            hits = search_web(query, limit_per_provider=args.limit_per_query)
            all_hits.extend(hits)
            time.sleep(args.delay)

    # Phase 3: Aggregate and persist
    print(f"\n▸ Fas 3: Aggregering och lagring...")
    aggregated = aggregate_hits(all_hits)
    for lead in aggregated:
        persist_aggregated_lead(connection, run_id, lead)

    finish_run(connection, run_id, queries_executed, len(all_hits))

    print(f"\n✓ Klart! {queries_executed} sökningar, {len(all_hits)} träffar, {len(aggregated)} leads sparade.")
    print()
    print_summary(connection, args.top)

    if args.export_csv:
        count = export_leads_csv(connection, args.export_csv)
        print(f"\n✓ Exporterade {count} leads till {args.export_csv}")

    return 0


def export_command(args: argparse.Namespace) -> int:
    connection = connect_db(args.db)
    init_db(connection)
    count = export_leads_csv(connection, args.output, limit=args.limit)
    print(f"✓ Exporterade {count} leads till {args.output}")
    return 0


def top_command(args: argparse.Namespace) -> int:
    connection = connect_db(args.db)
    init_db(connection)
    print_summary(connection, args.limit)
    return 0


def select_company_names(aggregated_leads, company_limit: int) -> list[str]:
    names = OrderedDict()
    for lead in aggregated_leads:
        if lead.company_name not in names:
            names[lead.company_name] = True
        if len(names) >= company_limit:
            break
    return list(names.keys())


def print_summary(connection, limit: int) -> None:
    rows = fetch_top_leads(connection, limit=limit)
    if not rows:
        print("Inga leads hittades.")
        return

    print(f"Topp {min(limit, len(rows))} leads:")
    print("-" * 80)
    for i, row in enumerate(rows, 1):
        parts = [
            f"{i:2d}. {row['company_name']}",
            f"score={row['score']:.1f}",
        ]
        if row["industry"]:
            parts.append(f"bransch={row['industry']}")
        if row["location"]:
            parts.append(f"plats={row['location']}")
        if row["employee_band"]:
            parts.append(f"storlek={row['employee_band']}")
        if row["revenue_band"]:
            parts.append(f"oms={row['revenue_band']}")
        if row["linkedin_url"]:
            parts.append(f"linkedin={row['linkedin_url']}")
        elif row["website"]:
            parts.append(f"web={row['website']}")
        print("  " + " | ".join(parts))
    print("-" * 80)
