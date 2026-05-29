"""
Brønnøysundregistrene API-klient – henter bedriftsdata fra det åpne Enhetsregisteret.

API-dokumentasjon: https://data.brreg.no/enhetsregisteret/api/docs/index.html
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

BRREG_BASE = "https://data.brreg.no/enhetsregisteret/api"
_CLIENT_KWARGS = {"timeout": 15.0, "headers": {"User-Agent": "ProffAgent/0.1 (ErikJarlHolm)"}}


def search_companies(name: str, size: int = 10) -> list[dict[str, Any]]:
    """
    Søk etter enheter (bedrifter) basert på navn.

    Args:
        name: Bedriftsnavn eller del av navn.
        size: Maks antall resultater (1-100).

    Returns:
        Liste med bedriftsobjekter fra Enhetsregisteret.
    """
    url = f"{BRREG_BASE}/enheter"
    params = {"navn": name, "size": min(size, 100)}
    try:
        with httpx.Client(**_CLIENT_KWARGS) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            results = data.get("_embedded", {}).get("enheter", [])
            log.info("Søk '%s': %d treff", name, len(results))
            return results
    except Exception as exc:
        log.warning("Søk feilet for '%s': %s", name, exc)
        return []


def get_company(orgnr: str) -> Optional[dict[str, Any]]:
    """
    Hent detaljert informasjon om én bedrift basert på organisasjonsnummer.

    Args:
        orgnr: 9-sifret organisasjonsnummer.

    Returns:
        Bedriftsobjekt eller None hvis ikke funnet.
    """
    url = f"{BRREG_BASE}/enheter/{orgnr}"
    try:
        with httpx.Client(**_CLIENT_KWARGS) as client:
            r = client.get(url)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            log.info("Hentet bedrift: %s", orgnr)
            return r.json()
    except Exception as exc:
        log.warning("Oppslag feilet for %s: %s", orgnr, exc)
        return None


def get_subunits(orgnr: str, size: int = 50) -> list[dict[str, Any]]:
    """
    Hent underenheter (avdelinger/filialer) for en overordnet enhet.

    Args:
        orgnr: Organisasjonsnummer for hovedenheten.
        size: Maks antall resultater.

    Returns:
        Liste med underenhet-objekter.
    """
    url = f"{BRREG_BASE}/underenheter"
    params = {"overordnetEnhet": orgnr, "size": size}
    try:
        with httpx.Client(**_CLIENT_KWARGS) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            results = data.get("_embedded", {}).get("underenheter", [])
            log.info("Underenheter for %s: %d stk", orgnr, len(results))
            return results
    except Exception as exc:
        log.warning("Underenheter feilet for %s: %s", orgnr, exc)
        return []


def search_by_industry(nace_code: str, municipality: Optional[str] = None, size: int = 20) -> list[dict[str, Any]]:
    """
    Søk etter bedrifter basert på næringskode (NACE).

    Args:
        nace_code: NACE-kode, f.eks. "62.010" for programmeringstjenester.
        municipality: Valgfri kommunefiltrering.
        size: Maks antall resultater.

    Returns:
        Liste med bedriftsobjekter.
    """
    url = f"{BRREG_BASE}/enheter"
    params: dict[str, Any] = {"naeringskode": nace_code, "size": size}
    if municipality:
        params["kommunenummer"] = municipality
    try:
        with httpx.Client(**_CLIENT_KWARGS) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            results = data.get("_embedded", {}).get("enheter", [])
            log.info("Bransjesøk NACE %s: %d treff", nace_code, len(results))
            return results
    except Exception as exc:
        log.warning("Bransjesøk feilet for NACE %s: %s", nace_code, exc)
        return []
