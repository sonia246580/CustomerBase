# Data Chat MVP - baza klientów

Cel: Excel/Google Sheets -> Gmail -> PDF/treść maila -> NIP/REGON -> SQLite katalog -> eksport wyniku z informacją o źródle.

## Co przygotować
1. W Google Cloud utwórz OAuth Client dla Desktop app i pobierz `credentials.json`.
2. Włącz Gmail API i Google Sheets API.
3. Włóż `credentials.json` do folderu projektu.
4. Zainstaluj zależności:

```bash
pip install -r requirements.txt
```

5. Skopiuj `.env.example` jako `.env` i uzupełnij:
- `SPREADSHEET_ID`
- `SHEET_NAME`

## Uruchomienie

```bash
python main.py --start-row 2 --end-row 30
```

## Jak działa
- najpierw szuka firmy w Gmailu,
- zapisuje surowe maile i PDF-y do `raw_cache`,
- tekst zapisuje w SQLite,
- wyciąga NIP i REGON z maili/PDF,
- jeśli ma NIP albo REGON, dociąga drugi numer z publicznego API MF,
- wpisuje wynik do arkusza,
- zachowuje źródło w kolumnie STATUS.

## Kolumny arkusza
Zakładane kolumny:
- B: KLIENT2
- D: NIP
- E: REGON
- H: STATUS

