# Status

## Phase

Initial demo scaffold complete and published.

## Current Work

Python demo for lead discovery is in place with:

- web search providers (DuckDuckGo + Brave fallback for LinkedIn-heavy searches)
- local SQLite persistence in `data/leads.db`
- CLI entrypoint via `python -m leadfinder run`
- wrapper script via `scripts/run_leadfinder.sh`
- public GitHub repo at `https://github.com/Magnus-Gille/demo_hito`
- tracked sample data in `demo-data/` for public demo purposes

## Repo State

- branch: `main`
- latest commit: `9a6dfdf` (`Initial lead finder demo`)
- remote: `origin -> https://github.com/Magnus-Gille/demo_hito.git`

## Verified

- Project bootstrapped with `.venv`, `requirements.txt`, and `pyproject.toml`
- Code compiles with `python3 -m compileall src`
- A live run produced leads before Brave rate limiting kicked in during repeated test cycles

## Known Risks

- Public search scraping is inherently brittle
- Brave can return HTTP 429 if queried too aggressively
- Revenue matching is heuristic and should be treated as lead qualification support, not source of truth

## Next Steps

- Tune discovery queries against Swedish target sectors
- Add stricter filtering for competitor/recruitment-vendor false positives
- Consider replacing HTML scraping with a paid search API if this moves beyond demo stage
