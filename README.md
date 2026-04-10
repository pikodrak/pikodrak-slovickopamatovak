# SlovíčkoPamatovák

Webová aplikace na procvičování slovíček v jakémkoli jazyce. PWA optimalizovaná pro mobilní zařízení s offline podporou a AI funkcemi.

## Funkce

- **Registrace a přihlášení** — každý uživatel má své slovníky
- **Správa slovníků** — vytváření, editace, mazání, import ze souboru nebo textu
- **Vícejazyčnost** — 19 předdefinovaných jazyků, konfigurovatelné v `config.ini`
- **Procvičování**
  - Kartičky s flip animací, volba směru (A→B, B→A, Mix)
  - AI režim "Psaní" — píšete překlad, AI vyhodnotí (přijímá synonyma, překlepy)
  - Opakování špatně zodpovězených slovíček
  - Statistiky chybovosti u každého slovíčka
  - Stránka "Opakování" — procvičování nejobtížnějších slov ze všech slovníků
- **AI funkce** (OpenAI GPT)
  - Generování slovíček z tématu
  - Auto-překlad při přidávání slovíček
  - Vysvětlení slovíčka (všechny významy, příklady, poznámky) — cachováno v DB
  - Nápověda při procvičování
  - Kontrola duplicit při generování (prohledá všechny slovníky)
- **Sdílení** — veřejný link na slovník, procvičování bez přihlášení, import do vlastního účtu
- **PWA / offline**
  - Instalace na domovskou obrazovku (Android, iOS)
  - Offline procvičování kartičkami (data v IndexedDB)
  - Výsledky se ukládají offline a synchronizují po připojení
  - Indikátor sync stavu v menu
- **REST API** — kompletní CRUD přes Bearer tokeny (Read / Read & Write)
- **Changelog** — zobrazitelný přímo v aplikaci, verzování

## Instalace

```bash
cp config.ini.example config.ini
# Upravte config.ini (OpenAI API klíč, port, ...)
pip install -r requirements.txt
```

## Spuštění

```bash
python app.py
```

Aplikace běží na `http://localhost:5001` (konfigurovatelné v `config.ini`).

## Konfigurace

Veškeré nastavení je v souboru `config.ini` (není v gitu — šablona: `config.ini.example`):

| Sekce | Klíč | Popis |
|-------|------|-------|
| `app` | `name` | Název aplikace |
| `app` | `version` | Verze zobrazená v UI |
| `app` | `port` | Port serveru |
| `app` | `debug` | Debug mód (true/false) |
| `database` | `uri` | SQLAlchemy URI databáze |
| `openai` | `api_key` | OpenAI API klíč (volitelné) |
| `openai` | `model` | Model (default: gpt-4o-mini) |
| `languages` | `kód = Název` | Seznam dostupných jazyků |
| `defaults` | `lang_a`, `lang_b` | Výchozí jazyky pro nový slovník |
| `defaults` | `min_password_length` | Minimální délka hesla |

## API

Dokumentace API je dostupná na `/api/docs` v běžící aplikaci. Tokeny se generují v menu uživatele → API Tokeny.

## Struktura

```
├── app.py               # Flask backend (modely, routy, API, AI)
├── config.ini.example    # šablona konfigurace
├── requirements.txt      # Python závislosti
├── run.sh                # spouštěcí skript
├── CHANGELOG.md          # historie změn
├── static/
│   ├── style.css         # mobilní responzivní CSS
│   ├── offline.js        # IndexedDB sync, offline queue
│   ├── sw.js             # service worker
│   ├── manifest.json     # PWA manifest
│   └── icon.*            # ikony (SVG, PNG)
└── templates/            # Jinja2 šablony
    ├── base.html         # layout s navbarem
    ├── login/register    # autentizace
    ├── dashboard         # přehled slovníků
    ├── view_set          # detail slovníku + slovíčka
    ├── practice          # procvičování (kartičky + AI psaní)
    ├── difficult         # opakování obtížných
    ├── shared            # veřejný sdílený slovník
    ├── offline           # offline procvičování z IndexedDB
    ├── ai_generate       # AI generování slovíček
    ├── tokens            # správa API tokenů
    ├── api_docs          # API dokumentace
    ├── changelog         # changelog v UI
    └── error             # chybové stránky (404, 403, 500)
```

## Technologie

- Python 3, Flask, SQLAlchemy, Flask-Login
- SQLite
- Vanilla HTML/CSS/JS (žádný framework)
- OpenAI API (volitelné)
- PWA (Service Worker, IndexedDB)
