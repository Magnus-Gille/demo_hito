from __future__ import annotations

import re
from urllib.parse import urlparse

from leadfinder.models import AggregatedLead, ContactInfo, LeadSignal, SearchHit

RECRUITMENT_KEYWORDS = {
    "hiring",
    "recruitment",
    "recruiting",
    "rekryterar",
    "rekrytering",
    "jobb",
    "careers",
    "career",
    "talent acquisition",
}
GROWTH_KEYWORDS = {
    "growth",
    "växer",
    "expansion",
    "expands",
    "growing",
    "scaleup",
    "scaling",
    "new office",
    "nytt kontor",
    "tillväxt",
    "investering",
    "förvärv",
    "series b",
    "series c",
}
TECH_KEYWORDS = {
    "tech",
    "technology",
    "saas",
    "fintech",
    "healthtech",
    "medtech",
    "software",
    "it",
    "digital",
    "ai",
    "cloud",
    "data",
    "platform",
    "edtech",
    "proptech",
    "cleantech",
    "cybersecurity",
    "devops",
}
STOCKHOLM_KEYWORDS = {
    "stockholm",
    "kista",
    "solna",
    "sundbyberg",
    "nacka",
    "södermalm",
    "vasastan",
    "norrmalm",
    "östermalm",
    "hammarby sjöstad",
}
CONTACT_ROLES = {
    "vd": "VD",
    "ceo": "VD",
    "chief executive": "VD",
    "hr": "HR",
    "hr-chef": "HR-chef",
    "head of people": "HR-chef",
    "people & culture": "HR-chef",
    "cto": "CTO",
    "chief technology": "CTO",
    "head of talent": "Head of Talent",
    "talent acquisition": "Head of Talent",
    "cfo": "CFO",
}
TARGET_EMPLOYEE_BANDS = {
    "51-200 employees",
    "201-500 employees",
    "501-1000 employees",
    "51-200 anställda",
    "201-500 anställda",
    "501-1000 anställda",
}
OUTSIDE_EMPLOYEE_BANDS = {
    "1-10 employees",
    "11-50 employees",
    "1001-5000 employees",
    "5001-10,000 employees",
}
REVENUE_PATTERN = re.compile(
    r"(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>msek|mkr|mnkr|mdkr|miljard(?:er)?|miljoner)",
    re.IGNORECASE,
)
LINKEDIN_COMPANY_PATH = re.compile(r"/company/([^/?#]+)/?", re.IGNORECASE)
LINKEDIN_PERSON_PATH = re.compile(r"/in/([^/?#]+)/?", re.IGNORECASE)
COMPETITOR_KEYWORDS = {
    "recruitment",
    "rekrytering",
    "staffing",
    "bemanning",
    "headhunting",
    "headhunt",
    "we are hiring",
    "rekryteringsföretag",
    "bemanningsföretag",
}
NON_TARGET_LINKEDIN_PATHS = ("/jobs/", "/pulse/", "/showcase/", "/learning/")
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_PATTERN = re.compile(r"(?:\+46|0)\s*(?:\d[\s-]*){7,10}")


def aggregate_hits(hits: list[SearchHit]) -> list[AggregatedLead]:
    leads: dict[str, AggregatedLead] = {}
    for hit in hits:
        signal = score_hit(hit)
        if signal is None:
            continue
        lead = leads.get(signal.company_key)
        if lead is None:
            lead = AggregatedLead(
                company_name=signal.company_name,
                company_key=signal.company_key,
            )
            leads[signal.company_key] = lead
        lead.company_name = choose_company_name(lead.company_name, signal.company_name)
        lead.score += signal.score
        if lead.linkedin_url is None and signal.linkedin_url is not None:
            lead.linkedin_url = signal.linkedin_url
        if lead.website is None and signal.website is not None:
            lead.website = signal.website
        if lead.employee_band is None and signal.employee_band is not None:
            lead.employee_band = signal.employee_band
        if lead.revenue_band is None and signal.revenue_band is not None:
            lead.revenue_band = signal.revenue_band
        if lead.industry is None and signal.industry is not None:
            lead.industry = signal.industry
        if lead.location is None and signal.location is not None:
            lead.location = signal.location
        if lead.best_source_url is None or signal.score >= 4:
            lead.best_source_url = signal.source_url
        lead.trigger_keywords.update(signal.trigger_keywords)
        lead.notes.update(signal.notes)
        lead.contacts.extend(signal.contacts)
        lead.recent_news.extend(signal.recent_news)
        lead.job_postings.extend(signal.job_postings)
        lead.hits.append((hit, signal))
    # Deduplicate contacts per lead
    for lead in leads.values():
        lead.contacts = _dedupe_contacts(lead.contacts)
        lead.recent_news = list(dict.fromkeys(lead.recent_news))[:10]
        lead.job_postings = list(dict.fromkeys(lead.job_postings))[:10]
    return sorted(leads.values(), key=lambda lead: lead.score, reverse=True)


def _dedupe_contacts(contacts: list[ContactInfo]) -> list[ContactInfo]:
    seen: set[str] = set()
    unique: list[ContactInfo] = []
    for c in contacts:
        key = f"{(c.name or '').lower()}|{(c.role or '').lower()}"
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def score_hit(hit: SearchHit) -> LeadSignal | None:
    combined = f"{hit.title} {hit.snippet}".strip()
    company_name = extract_company_name(hit)
    if not company_name:
        return None
    if is_non_target_linkedin_url(hit.url):
        return None
    if any(keyword in company_name.lower() for keyword in COMPETITOR_KEYWORDS):
        return None

    score = 0.0
    notes: list[str] = []
    trigger_keywords: list[str] = []
    contacts: list[ContactInfo] = []
    recent_news: list[str] = []
    job_postings: list[str] = []
    linkedin_url = hit.url if is_linkedin_company_url(hit.url) else None
    website = extract_website(hit)

    # LinkedIn signals
    if linkedin_url:
        score += 3.0
        notes.append("LinkedIn-signal")
    elif is_linkedin_person_url(hit.url):
        contact = extract_contact_from_linkedin(hit)
        if contact:
            contacts.append(contact)
            score += 1.5
            notes.append(f"Kontakt: {contact.role or 'okänd roll'}")
    elif "linkedin.com" in hit.url:
        score += 0.5
        notes.append("LinkedIn-omnämnande")

    # Employee band
    employee_band = extract_employee_band(combined)
    if employee_band in TARGET_EMPLOYEE_BANDS:
        score += 2.0
        notes.append(f"Målstorlek via {employee_band}")
    elif employee_band in OUTSIDE_EMPLOYEE_BANDS:
        score -= 1.5
        notes.append(f"Storlek utanför mål via {employee_band}")

    # Revenue
    revenue_band = extract_revenue_band(combined)
    if revenue_band:
        score += 2.0
        notes.append(f"Omsättningssignal via {revenue_band}")

    # Tech/industry signals
    text_lower = combined.lower()
    industry = extract_industry(text_lower)

    # Stockholm signals
    location = extract_location(text_lower)
    if location:
        score += 1.0
        notes.append(f"Plats: {location}")

    # Recruitment signals
    for keyword in sorted(RECRUITMENT_KEYWORDS):
        if keyword in text_lower:
            score += 1.25
            trigger_keywords.append(keyword)
    for keyword in sorted(GROWTH_KEYWORDS):
        if keyword in text_lower:
            score += 0.75
            trigger_keywords.append(keyword)

    # Job posting detection
    if any(kw in text_lower for kw in {"jobb", "careers", "hiring", "lediga tjänster"}):
        job_postings.append(hit.title[:120])

    # News detection
    if any(kw in text_lower for kw in {"nyheter", "förvärv", "investering", "expansion", "lanserar"}):
        recent_news.append(hit.title[:120])

    # Contact info extraction from snippets
    emails = EMAIL_PATTERN.findall(combined)
    phones = PHONE_PATTERN.findall(combined)
    if emails or phones:
        contact = ContactInfo(
            email=emails[0] if emails else None,
            phone=phones[0].strip() if phones else None,
        )
        contacts.append(contact)

    if score <= 0:
        return None

    return LeadSignal(
        company_name=company_name,
        company_key=normalize_company_name(company_name),
        score=round(score, 2),
        source_url=hit.url,
        linkedin_url=linkedin_url,
        website=website,
        employee_band=employee_band,
        revenue_band=revenue_band,
        industry=industry,
        location=location,
        contacts=contacts,
        recent_news=recent_news,
        job_postings=job_postings,
        trigger_keywords=dedupe_preserve_order(trigger_keywords),
        notes=dedupe_preserve_order(notes),
    )


def extract_contact_from_linkedin(hit: SearchHit) -> ContactInfo | None:
    """Extract contact info from a LinkedIn /in/ profile URL."""
    match = LINKEDIN_PERSON_PATH.search(hit.url)
    if not match:
        return None
    slug = match.group(1).replace("-", " ").title()
    text_lower = f"{hit.title} {hit.snippet}".lower()
    role = None
    for keyword, role_name in CONTACT_ROLES.items():
        if keyword in text_lower:
            role = role_name
            break
    return ContactInfo(
        name=slug,
        role=role,
        linkedin_url=hit.url,
    )


def extract_website(hit: SearchHit) -> str | None:
    """Extract company website if the URL is not LinkedIn/allabolag/search engine."""
    parsed = urlparse(hit.url)
    skip_domains = {"linkedin.com", "allabolag.se", "google.com", "bing.com",
                    "duckduckgo.com", "brave.com", "facebook.com", "twitter.com"}
    if any(d in parsed.netloc for d in skip_domains):
        return None
    if parsed.scheme in ("http", "https"):
        return f"{parsed.scheme}://{parsed.netloc}"
    return None


def extract_industry(text_lower: str) -> str | None:
    """Detect tech industry from text."""
    industry_map = {
        "fintech": "Fintech",
        "healthtech": "Healthtech",
        "medtech": "Medtech",
        "edtech": "Edtech",
        "proptech": "Proptech",
        "cleantech": "Cleantech",
        "saas": "SaaS",
        "cybersecurity": "Cybersecurity",
        "ai ": "AI",
        "artificial intelligence": "AI",
        "cloud": "Cloud/Infrastructure",
        "e-commerce": "E-commerce",
        "ecommerce": "E-commerce",
        "gaming": "Gaming",
        "it-konsult": "IT-konsult",
        "it konsult": "IT-konsult",
    }
    for keyword, label in industry_map.items():
        if keyword in text_lower:
            return label
    if any(kw in text_lower for kw in TECH_KEYWORDS):
        return "Tech"
    return None


def extract_location(text_lower: str) -> str | None:
    for keyword in STOCKHOLM_KEYWORDS:
        if keyword in text_lower:
            return keyword.title()
    return None


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def choose_company_name(current_name: str, new_name: str) -> str:
    if len(new_name) > len(current_name):
        return new_name
    return current_name


def normalize_company_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", name.lower())
    return normalized.strip("-")


def extract_company_name(hit: SearchHit) -> str | None:
    linkedin_match = LINKEDIN_COMPANY_PATH.search(hit.url)
    if linkedin_match:
        slug = linkedin_match.group(1).replace("-", " ").replace("_", " ")
        return clean_company_name(slug.title())

    title = hit.title
    for separator in (" | ", " - ", " – ", " — ", ": "):
        if separator in title:
            title = title.split(separator, 1)[0]
            break
    return clean_company_name(title)


def clean_company_name(name: str) -> str | None:
    name = re.sub(r"\s+", " ", name).strip(" -|")
    if not name or len(name) < 3:
        return None
    if name.lower() in {"linkedin", "bing", "duckduckgo", "brave", "google"}:
        return None
    return name


def is_linkedin_company_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("linkedin.com") and "/company/" in parsed.path


def is_linkedin_person_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("linkedin.com") and "/in/" in parsed.path


def is_non_target_linkedin_url(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.netloc.endswith("linkedin.com"):
        return False
    return any(fragment in parsed.path for fragment in NON_TARGET_LINKEDIN_PATHS)


def extract_employee_band(text: str) -> str | None:
    normalized = text.lower()
    for band in sorted(TARGET_EMPLOYEE_BANDS | OUTSIDE_EMPLOYEE_BANDS):
        if band.lower() in normalized:
            return band
    return None


def extract_revenue_band(text: str) -> str | None:
    matches = list(REVENUE_PATTERN.finditer(text))
    if not matches:
        return None
    for match in matches:
        number = parse_number(match.group("number"))
        unit = match.group("unit").lower()
        revenue_sek = number_to_sek(number, unit)
        if 100_000_000 <= revenue_sek <= 2_000_000_000:
            return f"{format_amount(revenue_sek)} SEK"
    first = matches[0]
    revenue_sek = number_to_sek(parse_number(first.group("number")), first.group("unit").lower())
    return f"{format_amount(revenue_sek)} SEK"


def parse_number(raw: str) -> float:
    return float(raw.replace(",", "."))


def number_to_sek(number: float, unit: str) -> int:
    if unit in {"mdkr", "miljard", "miljarder"}:
        return int(number * 1_000_000_000)
    return int(number * 1_000_000)


def format_amount(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B".rstrip("0").rstrip(".")
    return f"{value / 1_000_000:.0f}M"
