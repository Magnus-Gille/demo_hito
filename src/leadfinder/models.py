from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SearchHit:
    provider: str
    query: str
    rank: int
    title: str
    snippet: str
    url: str


@dataclass
class ContactInfo:
    name: str | None = None
    role: str | None = None  # VD, HR-chef, CTO, etc.
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None


@dataclass
class LeadSignal:
    company_name: str
    company_key: str
    score: float
    source_url: str
    linkedin_url: str | None = None
    website: str | None = None
    employee_band: str | None = None
    revenue_band: str | None = None
    industry: str | None = None
    location: str | None = None
    contacts: list[ContactInfo] = field(default_factory=list)
    recent_news: list[str] = field(default_factory=list)
    job_postings: list[str] = field(default_factory=list)
    trigger_keywords: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class AggregatedLead:
    company_name: str
    company_key: str
    score: float = 0.0
    linkedin_url: str | None = None
    website: str | None = None
    employee_band: str | None = None
    revenue_band: str | None = None
    industry: str | None = None
    location: str | None = None
    contacts: list[ContactInfo] = field(default_factory=list)
    recent_news: list[str] = field(default_factory=list)
    job_postings: list[str] = field(default_factory=list)
    best_source_url: str | None = None
    trigger_keywords: set[str] = field(default_factory=set)
    notes: set[str] = field(default_factory=set)
    hits: list[tuple[SearchHit, LeadSignal]] = field(default_factory=list)
