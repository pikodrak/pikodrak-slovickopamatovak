# SlovíčkoPamatovák

Webová aplikace na procvičování slovíček v jakémkoli jazyce. Optimalizováno pro mobilní zařízení.

## Funkce

- **Registrace a přihlášení** — každý uživatel má své vlastní sady
- **Správa sad slovíček** — vytváření, editace, mazání, import ze souboru nebo textu
- **Vícejazyčnost** — 19 předdefinovaných jazyků, konfigurovatelné v `config.ini`
- **Procvičovací režim** — kartičky s flip animací, volba směru (A→B, B→A, Mix), opakování špatně zodpovězených
- **Sdílení** — veřejný link na sadu, procvičování bez přihlášení, import do vlastního účtu
- **REST API** — kompletní CRUD přes Bearer tokeny (Read / Read & Write)
- **Changelog** — zobrazitelný přímo v aplikaci

## Instalace

```bash
pip install -r requirements.txt
```

## Spuštění

```bash
python app.py
```

Nebo přes skript:

```bash
./run.sh
```

Aplikace běží na `http://localhost:5001` (konfigurovatelné v `config.ini`).

## Konfigurace

Veškeré nastavení je v souboru `config.ini`:

| Sekce | Klíč | Popis |
|-------|------|-------|
| `app` | `name` | Název aplikace |
| `app` | `version` | Verze zobrazená v UI |
| `app` | `port` | Port serveru |
| `app` | `debug` | Debug mód (true/false) |
| `database` | `uri` | SQLAlchemy URI databáze |
| `languages` | `kód = Název` | Seznam dostupných jazyků |
| `defaults` | `lang_a`, `lang_b` | Výchozí jazyky pro novou sadu |
| `defaults` | `min_password_length` | Minimální délka hesla |

## API

Dokumentace API je dostupná na `/api/docs` v běžící aplikaci. Tokeny se generují v sekci **API** po přihlášení.

## Struktura

```
├── app.py              # Flask backend
├── config.ini          # konfigurace
├── requirements.txt    # Python závislosti
├── run.sh              # spouštěcí skript
├── CHANGELOG.md        # historie změn
├── static/
│   └── style.css       # mobilní responzivní CSS
└── templates/          # Jinja2 šablony
```

## Technologie

- Python 3, Flask, SQLAlchemy, Flask-Login
- SQLite
- Vanilla HTML/CSS/JS (žádný framework)
