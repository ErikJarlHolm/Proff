"""
ProffAgenten - Henter bedriftsinformasjon fra norske registre.

Bruker Brønnøysundregistrene (brreg.no) sitt åpne API for bedriftsdata
og genererer lenker til Proff.no for ytterligere detaljer.
"""

import sys
import json
import requests
from urllib.parse import quote

BRREG_BASE = "https://data.brreg.no/enhetsregisteret/api"


def search_companies(query: str, size: int = 5) -> list[dict]:
    """Søk etter bedrifter basert på navn."""
    url = f"{BRREG_BASE}/enheter"
    params = {"navn": query, "size": size}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("_embedded", {}).get("enheter", [])


def get_company_by_orgnr(orgnr: str) -> dict | None:
    """Hent bedrift basert på organisasjonsnummer."""
    url = f"{BRREG_BASE}/enheter/{orgnr}"
    resp = requests.get(url, timeout=10)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def get_subunits(orgnr: str) -> list[dict]:
    """Hent underenheter for en bedrift."""
    url = f"{BRREG_BASE}/underenheter"
    params = {"overordnetEnhet": orgnr, "size": 20}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("_embedded", {}).get("underenheter", [])


def proff_url(name: str, orgnr: str) -> str:
    """Generer en Proff.no søkelenke for bedriften."""
    return f"https://www.proff.no/bransjesøk?q={quote(orgnr)}"


def format_address(addr: dict | None) -> str:
    """Formater en adresse til lesbar streng."""
    if not addr:
        return "Ukjent"
    parts = []
    if addr.get("adresse"):
        parts.extend(addr["adresse"])
    if addr.get("postnummer") and addr.get("poststed"):
        parts.append(f"{addr['postnummer']} {addr['poststed']}")
    return ", ".join(parts) if parts else "Ukjent"


def format_company(company: dict) -> str:
    """Formater bedriftsinformasjon til lesbar tekst."""
    lines = []
    name = company.get("navn", "Ukjent")
    orgnr = company.get("organisasjonsnummer", "")

    lines.append(f"{'═' * 60}")
    lines.append(f"  {name}")
    lines.append(f"  Org.nr: {orgnr}")
    lines.append(f"{'═' * 60}")

    org_form = company.get("organisasjonsform", {})
    if org_form:
        lines.append(f"  Selskapsform:    {org_form.get('beskrivelse', 'Ukjent')} ({org_form.get('kode', '')})")

    forretningsadresse = company.get("forretningsadresse")
    if forretningsadresse:
        lines.append(f"  Forretningsadr.: {format_address(forretningsadresse)}")

    postadresse = company.get("postadresse")
    if postadresse:
        lines.append(f"  Postadresse:     {format_address(postadresse)}")

    if company.get("hjemmeside"):
        lines.append(f"  Hjemmeside:      {company['hjemmeside']}")

    if company.get("telefon"):
        lines.append(f"  Telefon:         {company['telefon']}")

    if company.get("epostadresse"):
        lines.append(f"  E-post:          {company['epostadresse']}")

    nace1 = company.get("naeringskode1", {})
    if nace1:
        lines.append(f"  Bransje:         {nace1.get('beskrivelse', '')} ({nace1.get('kode', '')})")

    nace2 = company.get("naeringskode2", {})
    if nace2:
        lines.append(f"  Bransje 2:       {nace2.get('beskrivelse', '')} ({nace2.get('kode', '')})")

    if company.get("antallAnsatte") is not None:
        lines.append(f"  Ansatte:         {company['antallAnsatte']}")

    if company.get("stiftelsesdato"):
        lines.append(f"  Stiftet:         {company['stiftelsesdato']}")

    if company.get("registreringsdatoEnhetsregisteret"):
        lines.append(f"  Registrert:      {company['registreringsdatoEnhetsregisteret']}")

    kapital = company.get("kapital", {})
    if kapital:
        belop = kapital.get("belop", 0)
        valuta = kapital.get("valuta", "NOK")
        lines.append(f"  Kapital:         {belop:,.0f} {valuta}".replace(",", " "))

    sektor = company.get("institusjonellSektorkode", {})
    if sektor:
        lines.append(f"  Sektor:          {sektor.get('beskrivelse', '')}")

    # Status
    status_items = []
    if company.get("konkurs"):
        status_items.append("⚠️  KONKURS")
    if company.get("underAvvikling"):
        status_items.append("⚠️  Under avvikling")
    if company.get("underTvangsavviklingEllerTvangsopplosning"):
        status_items.append("⚠️  Under tvangsavvikling")
    if company.get("registrertIMvaregisteret"):
        status_items.append("✓ MVA-registrert")
    if company.get("registrertIForetaksregisteret"):
        status_items.append("✓ Foretaksregisteret")

    if status_items:
        lines.append(f"  Status:          {', '.join(status_items)}")

    formaal = company.get("vedtektsfestetFormaal", [])
    if formaal:
        formaal_text = " ".join(formaal)
        if len(formaal_text) > 200:
            formaal_text = formaal_text[:200] + "..."
        lines.append(f"  Formål:          {formaal_text}")

    lines.append(f"  Proff.no:        {proff_url(name, orgnr)}")
    lines.append("")

    return "\n".join(lines)


def format_search_results(companies: list[dict]) -> str:
    """Formater søkeresultater som kort liste."""
    if not companies:
        return "  Ingen treff."

    lines = []
    for i, c in enumerate(companies, 1):
        name = c.get("navn", "Ukjent")
        orgnr = c.get("organisasjonsnummer", "")
        org_form = c.get("organisasjonsform", {}).get("kode", "")
        kommune = c.get("forretningsadresse", {}).get("kommune", "")
        ansatte = c.get("antallAnsatte", "")
        nace = c.get("naeringskode1", {}).get("beskrivelse", "")

        lines.append(f"  {i}. {name} ({org_form})")
        lines.append(f"     Org.nr: {orgnr} | {kommune} | {nace}")
        if ansatte:
            lines.append(f"     Ansatte: {ansatte}")
        lines.append("")

    return "\n".join(lines)


def interactive_mode():
    """Kjør agenten i interaktiv modus."""
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║              ProffAgenten - Bedriftsinformasjon             ║")
    print("║                                                            ║")
    print("║  Kommandoer:                                               ║")
    print("║    søk <navn>        - Søk etter bedrift                   ║")
    print("║    info <org.nr>     - Detaljer om en bedrift              ║")
    print("║    under <org.nr>    - Vis underenheter                    ║")
    print("║    json <org.nr>     - Rå JSON-data                        ║")
    print("║    hjelp             - Vis denne hjelpeteksten             ║")
    print("║    avslutt           - Avslutt programmet                  ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    while True:
        try:
            user_input = input("ProffAgent> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nHa det!")
            break

        if not user_input:
            continue

        parts = user_input.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        try:
            if cmd in ("søk", "sok", "search", "s"):
                if not arg:
                    print("  Bruk: søk <bedriftsnavn>")
                    continue
                print(f"\n  Søker etter '{arg}'...\n")
                results = search_companies(arg)
                print(format_search_results(results))

            elif cmd in ("info", "i", "detaljer"):
                if not arg:
                    print("  Bruk: info <organisasjonsnummer>")
                    continue
                orgnr = arg.replace(" ", "")
                print(f"\n  Henter info for {orgnr}...\n")
                company = get_company_by_orgnr(orgnr)
                if company:
                    print(format_company(company))
                else:
                    print(f"  Fant ingen bedrift med org.nr {orgnr}")

            elif cmd in ("under", "underenheter", "sub"):
                if not arg:
                    print("  Bruk: under <organisasjonsnummer>")
                    continue
                orgnr = arg.replace(" ", "")
                print(f"\n  Henter underenheter for {orgnr}...\n")
                subs = get_subunits(orgnr)
                if subs:
                    for s in subs:
                        name = s.get("navn", "Ukjent")
                        sub_orgnr = s.get("organisasjonsnummer", "")
                        kommune = s.get("beliggenhetsadresse", {}).get("kommune", "")
                        nace = s.get("naeringskode1", {}).get("beskrivelse", "")
                        print(f"  • {name} ({sub_orgnr}) - {kommune} - {nace}")
                    print()
                else:
                    print("  Ingen underenheter funnet.\n")

            elif cmd in ("json", "raw"):
                if not arg:
                    print("  Bruk: json <organisasjonsnummer>")
                    continue
                orgnr = arg.replace(" ", "")
                company = get_company_by_orgnr(orgnr)
                if company:
                    print(json.dumps(company, indent=2, ensure_ascii=False))
                else:
                    print(f"  Fant ingen bedrift med org.nr {orgnr}")

            elif cmd in ("hjelp", "help", "h", "?"):
                print("\n  Tilgjengelige kommandoer:")
                print("    søk <navn>        - Søk etter bedrift basert på navn")
                print("    info <org.nr>     - Vis detaljert info om en bedrift")
                print("    under <org.nr>    - Vis underenheter/avdelinger")
                print("    json <org.nr>     - Vis rå JSON-data fra API")
                print("    avslutt           - Avslutt\n")

            elif cmd in ("avslutt", "exit", "quit", "q"):
                print("Ha det!")
                break

            else:
                # Default: treat as search
                print(f"\n  Søker etter '{user_input}'...\n")
                results = search_companies(user_input)
                print(format_search_results(results))

        except requests.exceptions.Timeout:
            print("  ⚠️  Tidsavbrudd - prøv igjen.")
        except requests.exceptions.RequestException as e:
            print(f"  ⚠️  Nettverksfeil: {e}")


def main():
    """Hovedfunksjon - håndterer CLI-argumenter eller starter interaktiv modus."""
    if len(sys.argv) < 2:
        interactive_mode()
        return

    cmd = sys.argv[1].lower()

    if cmd in ("søk", "sok", "search") and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        results = search_companies(query)
        print(format_search_results(results))

    elif cmd in ("info",) and len(sys.argv) > 2:
        orgnr = sys.argv[2].replace(" ", "")
        company = get_company_by_orgnr(orgnr)
        if company:
            print(format_company(company))
        else:
            print(f"Fant ingen bedrift med org.nr {orgnr}")
            sys.exit(1)

    elif cmd in ("json",) and len(sys.argv) > 2:
        orgnr = sys.argv[2].replace(" ", "")
        company = get_company_by_orgnr(orgnr)
        if company:
            print(json.dumps(company, indent=2, ensure_ascii=False))
        else:
            sys.exit(1)

    else:
        # Default: search
        query = " ".join(sys.argv[1:])
        results = search_companies(query)
        print(format_search_results(results))


if __name__ == "__main__":
    main()
