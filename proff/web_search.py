"""
Web-søk – henter informasjon fra bedrifters egne nettsider og troverdige tredjepartskilder.

Bruker Bing Web Search API (via Azure) for å finne:
- Bedriftens egne sider (årsrapport, om oss, nyheter)
- Troverdige kilder som omtaler bedriften (DN, E24, NRK, Finansavisen, etc.)
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

_CLIENT_KWARGS = {"timeout": 15.0, "headers": {"User-Agent": "ProffAgent/0.1 (ErikJarlHolm)"}}

# Troverdige norske og internasjonale kilder
TRUSTED_SOURCES = {
    "dn.no": "Dagens Næringsliv",
    "e24.no": "E24",
    "nrk.no": "NRK",
    "finansavisen.no": "Finansavisen",
    "tu.no": "Teknisk Ukeblad",
    "digi.no": "Digi.no",
    "shifter.no": "Shifter",
    "kapital.no": "Kapital",
    "hegnar.no": "Hegnar",
    "borsen.no": "Børsen",
    "reuters.com": "Reuters",
    "bloomberg.com": "Bloomberg",
    "ft.com": "Financial Times",
    "regjeringen.no": "Regjeringen",
    "stortinget.no": "Stortinget",
    "ssb.no": "SSB",
    "datatilsynet.no": "Datatilsynet",
    "konkurransetilsynet.no": "Konkurransetilsynet",
    "arbeidstilsynet.no": "Arbeidstilsynet",
}


def _identify_source_type(url: str) -> str:
    """Identifiser kildetype basert på URL."""
    domain = urlparse(url).netloc.lower().removeprefix("www.")

    for trusted_domain, name in TRUSTED_SOURCES.items():
        if domain.endswith(trusted_domain):
            return f"Nyhetsmedium / fagpresse ({name})"

    if any(ext in domain for ext in [".gov", "regjeringen.no", "stortinget.no"]):
        return "Offentlig kilde"
    if any(ext in domain for ext in ["ssb.no", "brreg.no", "skatteetaten.no"]):
        return "Offentlig register"
    if any(ext in domain for ext in [".edu", "uio.no", "ntnu.no", "nhhno"]):
        return "Akademisk kilde"

    return "Nettkilde"


def search_company_website(company_name: str, website: Optional[str] = None, topics: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """
    Søk etter relevant informasjon på bedriftens egne nettsider.

    Args:
        company_name: Bedriftens navn.
        website: Bedriftens hjemmeside (domene), f.eks. "equinor.com".
        topics: Spesifikke emner å søke etter, f.eks. ["årsrapport", "bærekraft"].

    Returns:
        Liste med funn (tittel, url, snippet, dato).
    """
    if not topics:
        topics = ["årsrapport", "annual report", "strategi", "om oss", "investor"]

    results = []
    for topic in topics:
        if website:
            query = f"site:{website} {topic}"
        else:
            query = f"{company_name} {topic} site:{company_name.lower().replace(' ', '')}.no OR site:{company_name.lower().replace(' ', '')}.com"

        hits = _web_search(query, count=3)
        results.extend(hits)

    # Dedupliser basert på URL
    seen_urls = set()
    unique_results = []
    for r in results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique_results.append(r)

    return unique_results


def search_third_party_sources(company_name: str, topics: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """
    Søk etter omtale av bedriften i troverdige tredjepartskilder.

    Fokuserer på nyhetsmedier, fagpresse og offentlige kilder som er
    relevante for en samarbeidspartner.

    Args:
        company_name: Bedriftens navn.
        topics: Valgfrie spesifikke emner, f.eks. ["kontrakt", "samarbeid", "oppkjøp"].

    Returns:
        Liste med funn inkl. kildetype og dato.
    """
    base_topics = topics or [
        "samarbeid OR kontrakt OR partnerskap",
        "resultat OR omsetning OR vekst",
        "strategi OR satsing OR investering",
    ]

    # Søk i troverdige kilder
    trusted_sites = " OR ".join(f"site:{s}" for s in list(TRUSTED_SOURCES.keys())[:10])

    results = []
    for topic in base_topics:
        query = f"{company_name} {topic} ({trusted_sites})"
        hits = _web_search(query, count=5)
        for hit in hits:
            hit["kildetype"] = _identify_source_type(hit["url"])
        results.extend(hits)

    # Dedupliser
    seen_urls = set()
    unique_results = []
    for r in results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique_results.append(r)

    return unique_results


def _web_search(query: str, count: int = 5) -> list[dict[str, Any]]:
    """
    Utfør et websøk via DuckDuckGo HTML (fallback – krever ingen API-nøkkel).

    Returns:
        Liste med {title, url, snippet, date}.
    """
    url = "https://html.duckduckgo.com/html/"
    params = {"q": query}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        with httpx.Client(timeout=15.0, headers=headers, follow_redirects=True) as client:
            r = client.post(url, data=params)
            r.raise_for_status()
            html = r.text

        results = _parse_ddg_html(html, count)
        log.info("Websøk '%s': %d treff", query, len(results))
        return results

    except Exception as exc:
        log.warning("Websøk feilet for '%s': %s", query, exc)
        return []


def _parse_ddg_html(html: str, max_results: int) -> list[dict[str, Any]]:
    """Parse DuckDuckGo HTML-resultater."""
    results = []

    # Finn resultat-blokker
    result_pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    # Alternativt mønster
    alt_pattern = re.compile(
        r'<h2[^>]*class="result__title"[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</(?:a|span)',
        re.DOTALL,
    )

    matches = result_pattern.findall(html) or alt_pattern.findall(html)

    for match in matches[:max_results]:
        url_raw, title_raw, snippet_raw = match

        # Rens HTML-tagger
        title = re.sub(r'<[^>]+>', '', title_raw).strip()
        snippet = re.sub(r'<[^>]+>', '', snippet_raw).strip()
        result_url = url_raw

        # Prøv å trekke ut dato fra snippet
        date_match = re.search(r'(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})', snippet)
        date_str = None
        if date_match:
            try:
                d, m, y = date_match.groups()
                date_str = f"{y}-{int(m):02d}-{int(d):02d}"
            except (ValueError, IndexError):
                pass

        if not date_str:
            # Prøv år-måned-dag format
            date_match2 = re.search(r'(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})', snippet)
            if date_match2:
                date_str = f"{date_match2.group(1)}-{int(date_match2.group(2)):02d}-{int(date_match2.group(3)):02d}"

        if title and result_url:
            results.append({
                "title": title,
                "url": result_url,
                "snippet": snippet[:300] if snippet else "",
                "date": date_str,
            })

    return results


def fetch_page_summary(url: str, max_chars: int = 2000) -> Optional[str]:
    """
    Hent og oppsummer innholdet på en nettside.

    Args:
        url: URL å hente.
        max_chars: Maks antall tegn å returnere.

    Returns:
        Tekstinnhold fra siden eller None ved feil.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        with httpx.Client(timeout=15.0, headers=headers, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()

        # Fjern HTML-tagger og hent tekst
        text = re.sub(r'<script[^>]*>.*?</script>', '', r.text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text[:max_chars] if text else None

    except Exception as exc:
        log.warning("Kunne ikke hente %s: %s", url, exc)
        return None
