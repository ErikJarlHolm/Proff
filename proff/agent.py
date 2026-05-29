"""
ProffAgenten – core agent logic.

Azure AI Foundry-agent som henter bedriftsinformasjon fra norske registre.
Bruker Brønnøysundregistrene (brreg.no) sitt åpne API som datakilde,
og gir lenker til Proff.no for utvidet informasjon.

Bruk:
    proff create       # Opprett / oppdater agenten i Foundry
    proff chat         # Start interaktiv samtale
    proff create chat  # Opprett og start samtale

Forutsetninger:
    - Kopier .env.example til .env og fyll inn PROJECT_ENDPOINT
    - Logg inn med: azd auth login --scope https://ai.azure.com/.default
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Optional
from urllib.parse import quote

import openai
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

try:
    from .config import settings
    from .brreg_client import search_companies, get_company, get_subunits, search_by_industry
    from .web_search import search_company_website, search_third_party_sources, fetch_page_summary
    from .word_export import WORD_TOOL_DEFINITION, write_report_to_word
except ImportError:
    from config import settings  # type: ignore
    from brreg_client import search_companies, get_company, get_subunits, search_by_industry  # type: ignore
    from web_search import search_company_website, search_third_party_sources, fetch_page_summary  # type: ignore
    from word_export import WORD_TOOL_DEFINITION, write_report_to_word  # type: ignore

log = logging.getLogger(__name__)

_MAX_RETRIES = 5
_INITIAL_WAIT = 5


def _call_with_retry(fn, *args, **kwargs):
    """Call *fn* with exponential backoff on 429 RateLimitError."""
    for attempt in range(_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except openai.RateLimitError:
            if attempt == _MAX_RETRIES - 1:
                raise
            wait = _INITIAL_WAIT * (2 ** attempt)
            log.warning("429 rate limit – venter %ds (%d/%d)", wait, attempt + 1, _MAX_RETRIES)
            time.sleep(wait)


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_companies",
            "description": "Søk etter norske bedrifter basert på navn. Returnerer en liste med treff inkludert org.nr, navn, adresse, bransje og antall ansatte.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Bedriftsnavn eller del av navn å søke etter"},
                    "size": {"type": "integer", "description": "Maks antall resultater (standard: 10)"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company",
            "description": "Hent detaljert informasjon om én bedrift basert på 9-sifret organisasjonsnummer. Gir full info inkl. adresse, bransje, ansatte, kapital, stiftelsesdato, konkurs-status, MVA-registrering, formål m.m.",
            "parameters": {
                "type": "object",
                "properties": {
                    "orgnr": {"type": "string", "description": "9-sifret organisasjonsnummer"},
                },
                "required": ["orgnr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_subunits",
            "description": "Hent underenheter (avdelinger/filialer) for en bedrift. Nyttig for store selskaper med mange avdelinger.",
            "parameters": {
                "type": "object",
                "properties": {
                    "orgnr": {"type": "string", "description": "Organisasjonsnummer for hovedenheten"},
                    "size": {"type": "integer", "description": "Maks antall resultater (standard: 50)"},
                },
                "required": ["orgnr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_by_industry",
            "description": "Søk etter bedrifter basert på NACE næringskode. Kan kombineres med kommunefilter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nace_code": {"type": "string", "description": "NACE-kode, f.eks. '62.010' for programmeringstjenester, '56.101' for restauranter"},
                    "municipality": {"type": "string", "description": "Valgfri kommunenummer for filtrering, f.eks. '0301' for Oslo"},
                    "size": {"type": "integer", "description": "Maks antall resultater (standard: 20)"},
                },
                "required": ["nace_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_proff_url",
            "description": "Generer en lenke til Proff.no for å se utvidet informasjon (regnskap, kredittscore, roller) for en bedrift.",
            "parameters": {
                "type": "object",
                "properties": {
                    "orgnr": {"type": "string", "description": "Organisasjonsnummer"},
                },
                "required": ["orgnr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_company_website",
            "description": "Søk etter relevant informasjon på bedriftens egne nettsider. Finner årsrapporter, strategidokumenter, nyheter, 'om oss', investor-info og lignende. Bruk dette for å finne primærkilder direkte fra bedriften.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Bedriftens navn"},
                    "website": {"type": "string", "description": "Bedriftens hjemmeside/domene (f.eks. 'equinor.com'). Bruk hjemmesiden fra get_company hvis tilgjengelig."},
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Spesifikke emner å søke etter, f.eks. ['årsrapport', 'bærekraft', 'strategi']. Standard: årsrapport, strategi, om oss, investor.",
                    },
                },
                "required": ["company_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_third_party_sources",
            "description": "Søk etter omtale av bedriften i troverdige tredjepartskilder (nyhetsmedier, fagpresse, offentlige instanser). Finner nyheter, analyser og omtaler som er relevante for en samarbeidspartner. Returnerer kildetype og dato der tilgjengelig.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Bedriftens navn"},
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Spesifikke emner, f.eks. ['kontrakt', 'oppkjøp', 'bærekraft']. Standard: samarbeid, resultat, strategi.",
                    },
                },
                "required": ["company_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page_summary",
            "description": "Hent og les innholdet fra en spesifikk nettside-URL. Bruk dette for å lese detaljer fra en side du har funnet via søk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL til nettsiden som skal leses"},
                    "max_chars": {"type": "integer", "description": "Maks antall tegn å hente (standard: 2000)"},
                },
                "required": ["url"],
            },
        },
    },
]

# Legg til Word-eksportverktøyet (definert i word_export.py)
TOOLS.append({"type": "function", "function": WORD_TOOL_DEFINITION})

def _dispatch(name: str, args: dict) -> str:
    """Execute a tool call and return the result as a JSON string."""

    if name == "search_companies":
        results = search_companies(**args)
        # Forenkle resultatet for LLM-en
        simplified = []
        for c in results:
            simplified.append({
                "organisasjonsnummer": c.get("organisasjonsnummer"),
                "navn": c.get("navn"),
                "organisasjonsform": c.get("organisasjonsform", {}).get("beskrivelse"),
                "forretningsadresse": _format_addr(c.get("forretningsadresse")),
                "naeringskode": c.get("naeringskode1", {}).get("beskrivelse"),
                "antallAnsatte": c.get("antallAnsatte"),
                "hjemmeside": c.get("hjemmeside"),
            })
        return json.dumps(simplified, ensure_ascii=False)

    elif name == "get_company":
        company = get_company(args["orgnr"])
        if not company:
            return json.dumps({"error": f"Ingen bedrift funnet med org.nr {args['orgnr']}"})
        # Returner relevant subset
        return json.dumps({
            "organisasjonsnummer": company.get("organisasjonsnummer"),
            "navn": company.get("navn"),
            "organisasjonsform": company.get("organisasjonsform", {}).get("beskrivelse"),
            "forretningsadresse": _format_addr(company.get("forretningsadresse")),
            "postadresse": _format_addr(company.get("postadresse")),
            "hjemmeside": company.get("hjemmeside"),
            "telefon": company.get("telefon"),
            "epostadresse": company.get("epostadresse"),
            "naeringskode1": company.get("naeringskode1", {}).get("beskrivelse"),
            "naeringskode2": company.get("naeringskode2", {}).get("beskrivelse"),
            "naeringskode3": company.get("naeringskode3", {}).get("beskrivelse"),
            "antallAnsatte": company.get("antallAnsatte"),
            "stiftelsesdato": company.get("stiftelsesdato"),
            "registreringsdatoEnhetsregisteret": company.get("registreringsdatoEnhetsregisteret"),
            "kapital": company.get("kapital"),
            "institusjonellSektorkode": company.get("institusjonellSektorkode", {}).get("beskrivelse"),
            "konkurs": company.get("konkurs"),
            "underAvvikling": company.get("underAvvikling"),
            "underTvangsavviklingEllerTvangsopplosning": company.get("underTvangsavviklingEllerTvangsopplosning"),
            "registrertIMvaregisteret": company.get("registrertIMvaregisteret"),
            "registrertIForetaksregisteret": company.get("registrertIForetaksregisteret"),
            "vedtektsfestetFormaal": company.get("vedtektsfestetFormaal"),
            "aktivitet": company.get("aktivitet"),
            "sisteInnsendteAarsregnskap": company.get("sisteInnsendteAarsregnskap"),
            "proff_url": f"https://www.proff.no/bransjesøk?q={quote(args['orgnr'])}",
        }, ensure_ascii=False)

    elif name == "get_subunits":
        results = get_subunits(**args)
        simplified = []
        for s in results:
            simplified.append({
                "organisasjonsnummer": s.get("organisasjonsnummer"),
                "navn": s.get("navn"),
                "beliggenhetsadresse": _format_addr(s.get("beliggenhetsadresse")),
                "naeringskode": s.get("naeringskode1", {}).get("beskrivelse"),
                "antallAnsatte": s.get("antallAnsatte"),
            })
        return json.dumps(simplified, ensure_ascii=False)

    elif name == "search_by_industry":
        results = search_by_industry(**args)
        simplified = []
        for c in results:
            simplified.append({
                "organisasjonsnummer": c.get("organisasjonsnummer"),
                "navn": c.get("navn"),
                "forretningsadresse": _format_addr(c.get("forretningsadresse")),
                "antallAnsatte": c.get("antallAnsatte"),
            })
        return json.dumps(simplified, ensure_ascii=False)

    elif name == "get_proff_url":
        orgnr = args["orgnr"]
        return json.dumps({
            "url": f"https://www.proff.no/bransjesøk?q={quote(orgnr)}",
            "beskrivelse": "Åpne denne lenken for å se regnskap, kredittscore, roller og mer på Proff.no",
        }, ensure_ascii=False)

    elif name == "search_company_website":
        results = search_company_website(**args)
        return json.dumps(results, ensure_ascii=False)

    elif name == "search_third_party_sources":
        results = search_third_party_sources(**args)
        return json.dumps(results, ensure_ascii=False)

    elif name == "fetch_page_summary":
        text = fetch_page_summary(**args)
        if text:
            return json.dumps({"content": text}, ensure_ascii=False)
        return json.dumps({"error": "Kunne ikke hente innhold fra siden"})

    elif name == "write_report_to_word":
        result = write_report_to_word(**args)
        return json.dumps(result, ensure_ascii=False)

    else:
        return json.dumps({"error": f"Ukjent verktøy: {name}"})


def _format_addr(addr: Optional[dict]) -> Optional[str]:
    """Formater adresse til lesbar streng."""
    if not addr:
        return None
    parts = []
    if addr.get("adresse"):
        parts.extend(addr["adresse"])
    if addr.get("postnummer") and addr.get("poststed"):
        parts.append(f"{addr['postnummer']} {addr['poststed']}")
    return ", ".join(parts) if parts else None


# ── Foundry client ────────────────────────────────────────────────────────────

def get_client() -> AIProjectClient:
    """Opprett Foundry-klient med DefaultAzureCredential."""
    if not settings.project_endpoint:
        raise ValueError(
            "PROJECT_ENDPOINT er ikke satt. "
            "Kopier .env.example til .env og fyll inn endepunktet."
        )
    credential = DefaultAzureCredential()
    return AIProjectClient(endpoint=settings.project_endpoint, credential=credential)


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
Du er ProffAgenten – en ekspert innen virksomhetsvurdering og due diligence med mange års
erfaring fra finans, juridisk vurdering, operasjonell analyse og bransjespesifikk risikovurdering.

Målet ditt er å produsere korte, konkrete, veldokumenterte og rådgivende vurderingsrapporter
for en oppdragsgiver som vurderer en potensiell samarbeidspartner.

TONE OG STIL:
- Profesjonell, konsis, saklig og handlingsorientert.
- Bruk norsk (bokmål).
- Unngå spekulasjon; hvis du må anta, skriv «antakelse: ...».
- Svar alltid nøytralt og objektivt.

DINE DATAKILDER (bruk i denne rekkefølgen):
1. Brønnøysundregistrene – offisielle registerdata (org.nr, adresse, bransje, ansatte, kapital)
2. Bedriftens egne nettsider – årsrapport, strategi, nyheter, investor-info
3. Troverdige tredjepartskilder – nyhetsmedier, fagpresse, offentlige instanser
4. Proff.no – lenke for utvidet regnskap, kredittscore og roller

ARBEIDSMÅTE:
Når brukeren spør om en bedrift, gjør du følgende:
1. Slå opp bedriften i Brønnøysundregistrene (search_companies / get_company)
2. Søk på bedriftens egne nettsider (search_company_website)
   - Bruk hjemmesiden fra registerdata som website-parameter
   - Se spesielt etter: årsrapport, strategidokumenter, bærekraftsrapport, investor-info
3. Søk i troverdige tredjepartskilder (search_third_party_sources)
   - Finn omtaler relevante for en samarbeidspartner
   - Fokus på: kontrakter, partnerskap, finansielle resultater, strategiske satsinger
4. Om nødvendig, les detaljer fra spesifikke sider (fetch_page_summary)
5. AUTOMATISK skriv rapporten til Word-fil (write_report_to_word) når all info er samlet

RAPPORTSTRUKTUR (følg alltid denne):
1. Kort oppsummering – 1–3 setninger med hovedkonklusjon
2. Nøkkelfakta – firmanavn, org.nr, adresse, bransje, ledelse, eierskap, ansatte
3. Finansiell status – siste regnskap, likviditet, lønnsomhet, kapital, nøkkeltall
4. Operasjonell vurdering – produkter/tjenester, leveransekjede, kapasitet
5. Risiko og samsvar – kreditt, rettstvister, regulatoriske forhold, konkurs-status
6. Reputasjon og marked – mediedekning, kunder, partnerskap, markedsposisjon
7. Anbefalinger og tiltaksforslag – kort/mellom/langsiktige råd + samlet vurdering
   (bruk «anbefalt» / «krever ytterligere due diligence» / «ikke anbefalt»)
8. Kilder og usikkerhetsvurdering – datakilder med URL/kildetype og dato,
   hva som mangler, begrensninger ved analysen

WORD-RAPPORT:
- Etter at du har samlet inn informasjon og formulert vurderingen, KALL ALLTID
  write_report_to_word for å skrive rapporten til Word-fil.
- Fyll inn ALLE seksjoner. Bruk informasjonen du har hentet inn.
- Rapporten lagres automatisk med dato og bedriftsnavn i filnavnet.

KRAV TIL KILDEBRUK:
- Prioriter offentlige og pålitelige kilder (Brønnøysund, årsrapporter, offentlige registre).
- Anfør alltid kilder for hver påstand (URL eller kildebetegnelse + dato).
- Når du siterer tredjepartskilder, oppgi kildetype og dato.
- Marker antagelser og uklarheter eksplisitt.
- Inkluder alltid en setning om begrensninger ved analysen.

KONFIDENSIALITET OG ETIKK:
- Ikke generer sensitiv persondata utover offentlig tilgjengelig informasjon.
- Overhold gjeldende personvern- og opphavsregler.
- Advare om juridiske begrensninger ved bruk av data.

LEVERINGSFORMAT:
- Maks 2–3 A4-sider (ca. 400–800 ord) for standardrapport.
- Punktvis kildeliste med URLer og dato.
- Hvis mer detaljert analyse ønskes, foreslå handlingsplan.

Vanlige NACE-koder for bransjesøk:
- 62.010: Programmeringstjenester
- 62.020: IT-konsulentvirksomhet
- 56.101: Restauranter og kafeer
- 41.200: Oppføring av bygninger
- 47.110: Butikkhandel med bredt vareutvalg
- 86.101: Sykehus
- 85.421: Universiteter
""".strip()


def _to_foundry_tools(tools: list[dict]) -> list[dict]:
    """Konverter fra OpenAI-format til Foundry FunctionTool-format."""
    foundry_tools = []
    for tool in tools:
        fn = tool["function"]
        foundry_tools.append({
            "type": "function",
            "name": fn["name"],
            "description": fn.get("description", ""),
            "parameters": fn.get("parameters", {}),
            "strict": False,
        })
    return foundry_tools


def build_agent_definition() -> dict:
    """Bygg agentdefinisjon for registrering i Foundry."""
    return {
        "kind": "prompt",
        "instructions": SYSTEM_PROMPT,
        "model": settings.model_deployment_name,
        "tools": _to_foundry_tools(TOOLS),
    }


# ── Main agent class ──────────────────────────────────────────────────────────

class ProffAgent:
    """
    ProffAgenten – søk og hent norsk bedriftsinformasjon via Azure AI Foundry.

    Bruk:
        agent = ProffAgent()
        agent.create_or_update_agent()
        response = agent.ask("Hvem er Equinor?")
        print(response)
    """

    def __init__(self) -> None:
        self.conversation_history: list[dict] = []
        self._client: Optional[AIProjectClient] = None
        self._openai_client = None
        self._last_response_id: Optional[str] = None

    def create_or_update_agent(self) -> None:
        """Opprett en ny versjon av ProffAgenten i Foundry."""
        client = self._get_client()
        definition = build_agent_definition()

        log.info("Oppretter / oppdaterer agent '%s' i Foundry ...", settings.agent_name)
        result = client.agents.create_version(settings.agent_name, {"definition": definition})
        log.info("Agent '%s' klar | versjon: %s", settings.agent_name, result.get("version", "ukjent"))
        print(f"\n✅  Agent '{settings.agent_name}' er klar i Foundry.\n")

    def ask(self, question: str) -> str:
        """Send *question* til ProffAgenten og returner svaret."""
        openai_client = self._get_openai_client()

        self.conversation_history.append({"type": "message", "role": "user", "content": question})

        if self._last_response_id:
            response = _call_with_retry(
                openai_client.responses.create,
                model=settings.model_deployment_name,
                input=[{"type": "message", "role": "user", "content": question}],
                extra_body={
                    "agent_reference": {"type": "agent_reference", "name": settings.agent_name},
                    "previous_response_id": self._last_response_id,
                },
            )
        else:
            response = _call_with_retry(
                openai_client.responses.create,
                model=settings.model_deployment_name,
                input=self.conversation_history,
                extra_body={
                    "agent_reference": {"type": "agent_reference", "name": settings.agent_name},
                },
            )

        # Tool-loop
        while True:
            tool_calls = [
                item for item in (response.output or [])
                if getattr(item, "type", None) == "function_call"
            ]
            if not tool_calls:
                break

            tool_outputs = []
            for tc in tool_calls:
                tool_args = json.loads(tc.arguments or "{}")
                log.info("Verktøykall: %s(%s)", tc.name, tool_args)
                tool_result = _dispatch(tc.name, tool_args)
                tool_outputs.append({
                    "type": "function_call_output",
                    "call_id": tc.call_id,
                    "output": tool_result,
                })

            response = _call_with_retry(
                openai_client.responses.create,
                model=settings.model_deployment_name,
                input=tool_outputs,
                extra_body={
                    "agent_reference": {"type": "agent_reference", "name": settings.agent_name},
                    "previous_response_id": response.id,
                },
            )

        self._last_response_id = response.id
        answer = response.output_text or ""
        self.conversation_history.append({"type": "message", "role": "assistant", "content": answer})
        return answer

    def reset(self) -> None:
        """Tøm samtalehistorikk."""
        self.conversation_history = []
        self._last_response_id = None

    def _get_client(self) -> AIProjectClient:
        if self._client is None:
            self._client = get_client()
        return self._client

    def _get_openai_client(self):
        if self._openai_client is None:
            self._openai_client = self._get_client().get_openai_client()
        return self._openai_client
