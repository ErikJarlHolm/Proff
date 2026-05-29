# ProffAgenten 🇳🇴

En agent for å hente bedriftsinformasjon fra norske registre.

## Datakilde

Bruker **Brønnøysundregistrene** (brreg.no) sitt åpne API – gratis, ingen autentisering nødvendig.
Gir lenker til **Proff.no** for ytterligere detaljer (regnskap, kredittscore, roller).

## Installasjon

```bash
pip install -r requirements.txt
```

## Bruk

### Interaktiv modus
```bash
python proff_agent.py
```

### Kommandolinje
```bash
# Søk etter bedrift
python proff_agent.py søk Equinor

# Hent detaljer med org.nr
python proff_agent.py info 923609016

# Rå JSON-data
python proff_agent.py json 923609016
```

### Kommandoer i interaktiv modus

| Kommando | Beskrivelse |
|----------|-------------|
| `søk <navn>` | Søk etter bedrift basert på navn |
| `info <org.nr>` | Vis detaljert info om en bedrift |
| `under <org.nr>` | Vis underenheter/avdelinger |
| `json <org.nr>` | Vis rå JSON-data fra API |
| `hjelp` | Vis hjelpetekst |
| `avslutt` | Avslutt programmet |

## Tilgjengelig data

- Bedriftsnavn og organisasjonsnummer
- Selskapsform (AS, ASA, ENK, etc.)
- Forretnings- og postadresse
- Bransje (NACE-koder)
- Antall ansatte
- Stiftelsesdato
- Aksjekapital
- MVA- og foretaksregisterstatus
- Konkurs-/avviklingsstatus
- Vedtektsfestet formål
- Underenheter/avdelinger

## API-referanse

- [Brønnøysundregistrene API-dokumentasjon](https://data.brreg.no/enhetsregisteret/api/docs/index.html)
- [Proff.no](https://www.proff.no) (for utvidet info som regnskap og kreditt)
