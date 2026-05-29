# ProffAgenten 🏢

En Azure AI Foundry-agent som henter bedriftsinformasjon fra norske registre.

## Datakilde

Bruker **Brønnøysundregistrene** (brreg.no) sitt åpne API – gratis, ingen autentisering.
Gir lenker til **Proff.no** for utvidet informasjon (regnskap, kredittscore, roller).

## Oppsett

### 1. Installer

```bash
pip install -e .
```

### 2. Konfigurer

```bash
cp .env.example .env
# Fyll inn PROJECT_ENDPOINT i .env
```

### 3. Logg inn Azure

```bash
azd auth login --scope https://ai.azure.com/.default
```

### 4. Registrer agenten

```bash
proff create
```

### 5. Chat

```bash
proff chat
```

## Kommandoer

| Kommando | Beskrivelse |
|----------|-------------|
| `proff create` | Registrer/oppdater agenten i Azure AI Foundry |
| `proff chat` | Start interaktiv chat |
| `proff info` | Vis konfigurasjon |

## Hva agenten kan

- **Søke etter bedrifter** basert på navn
- **Hente detaljert info** om en bedrift (adresse, bransje, ansatte, kapital, formål)
- **Finne underenheter** (avdelinger/filialer)
- **Bransjesøk** basert på NACE-kode
- **Generere Proff.no-lenker** for utvidet info

## Eksempler

```
Du: Finn info om Equinor
Du: Hvor mange ansatte har DNB?
Du: Søk etter IT-selskaper i Oslo
Du: Hva er formålet til org.nr 923609016?
```

## Arkitektur

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Bruker    │────▶│  Azure AI Foundry │────▶│  Brreg.no API   │
│   (CLI)     │◀────│  (GPT + Tools)   │◀────│  (Åpne data)    │
└─────────────┘     └──────────────────┘     └─────────────────┘
                                                      │
                                              ┌───────▼───────┐
                                              │   Proff.no    │
                                              │   (Lenker)    │
                                              └───────────────┘
```

## API-referanser

- [Brønnøysundregistrene API](https://data.brreg.no/enhetsregisteret/api/docs/index.html)
- [Proff.no](https://www.proff.no) – regnskap, kreditt, roller
