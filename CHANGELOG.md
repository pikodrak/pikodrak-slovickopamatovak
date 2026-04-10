# Changelog

## 0.1.0 — 2026-04-10

### Přidáno
- Verzování aplikace (v config.ini, zobrazeno v navbaru a na login stránce)
- Stránka s changelogem (/changelog) přístupná z navbaru i login stránky
- README.md s popisem projektu, instalací a konfigurací

## 2026-04-10 (2)

### Přidáno
- Jednotná navigační lišta (navbar) na všech stránkách
  - Název aplikace vlevo (odkaz na dashboard)
  - Odkazy: Sady, API, uživatel, Odhlásit
  - Šipka zpět na stránkách s kontextem (detail sady, import, tokeny, API docs, procvičování)
  - Na login/register stránkách se navbar nezobrazuje
- Nadpis stránky (page-header) pod navbarem pro lepší orientaci

## 2026-04-10

### Přidáno
- Základní aplikace Flask s SQLite databází
- Registrace a přihlášení uživatelů (hashovaná hesla)
- CRUD správa sad slovíček (vytváření, editace, mazání)
- CRUD správa slovíček v sadách (přidávání, editace přes modal, mazání)
- Procvičovací režim s kartičkami (flip animace)
  - Volba směru procvičování (A→B, B→A, Mix)
  - Opakování špatně zodpovězených slovíček v dalších kolech
  - Progress bar a statistiky na konci
- Import slovíček z textového formátu (středník/tabulátor) a ze souboru
- REST API s tokenovou autentizací (Bearer token)
  - CRUD endpointy pro sady a slovíčka
  - Hromadný import přes API (JSON pole i textový formát)
  - Tokeny s oprávněním Read nebo Read & Write
  - Stránka s API dokumentací (/api/docs)
- Správa API tokenů v UI (generování, mazání)
- Podpora více jazyků - uživatel si volí zdrojový a cílový jazyk pro každou sadu
  - 19 předdefinovaných jazyků (konfigurovatelné v config.ini)
- Veřejné sdílení sad přes unikátní link
  - Sdílená stránka se seznamem slovíček
  - Procvičování ze sdíleného linku (bez přihlášení)
  - Import sdílené sady do vlastního účtu (vyžaduje přihlášení)
- Konfigurace přes config.ini (název aplikace, port, databáze, jazyky, defaulty)
- Mobilní responzivní UI optimalizované pro telefony

### Přejmenováno
- Aplikace přejmenována z "Español" na "SlovíčkoPamatovák"
