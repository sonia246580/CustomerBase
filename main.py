import argparse
import base64
import os
import re
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from pypdf import PdfReader

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "htpps://www.googleapis.com/auth/spreadsheets",
]

RAW_DIR = Path("raw_cache")
DB_PATH = Path("catalog.sqlite")

COL_CLIENT = 2
COL_NIP = 4
COL_REGON = 5
COL_PHONE = 6
COL_STATUS = 8

BLOCKED_SENDERS = {
    "ubezpieczeniamsleasing.com.pl",
    "dok@msleasing.com.pl",
    "kredyty@msleasing.com.pl",
    "synerglease@msleasing.com.pl",
    "ksiegowosc@msleasing.com.pl",
}

BANK_DOMAINS = [ 
    "santander.pl",
    "ing.pl",
    "mbank.pl",
    "phobp.pl",
    "pekao.com.pl",
    "alior.pl",
    "bnpparibas.pl",
    "credit-agricole,pl",
    "millenium.pl",
    "velobank.pl",
    "velo.pl",
    "nestbank.pl",
    "bosbank.pl",
    "citibank.pl",
    "citi.com",
    "bankmillenium.pl",
    "bank.pl",
    "wznowienia.pl"
]

def get_creds():
    creds = None

    if Path("token.json").exists():
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
                creds = flow.run_local_server(port=0)

                Path("token.json").write_text(creds.to_json(), encoding="utf-8")

            return creds
        

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMNT,
        company TEXT, 
        source_type TEXT, 
        raw_path TEXT, 
        text TEXT, 
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    return conn

def clean_num(x): 
    return re.sub(r"\D", "", str(x or ""))

def normalize_phone(phone):
    digits = clean_num(phone)

    if digits.startswith("48") and len(digits) == 11: 
        digits = digits[2:]

    if len(digits) == 9:
        return f"{digits[0:3]} {digits[3:6]} {digits[6:9]}"
    
    return ""

def extract_email_address(raw_sender):
    raw_sender = (raw_sender or "").lower()
    match = re.search(r"[\w\.-]+@[\w\.-]+", raw_sender)
    return match.group(0) if match else raw_sender.strip()

def is_internal_or_bank_sender(sender):
    sender_raw = (sender or "").lower()
    sender_email = extract_email_address(sender_raw)

    if sender_email.endswith("@msleasing.com.pl"):
        return True
    
    if sender_email in BLOCKED_SENDERS: 
        return True 
    
    for domain in BANK_DOMAINS: 
        if sender_email.endswith("@" + domain) or domain in sender_email:
            return True 
        
    return False

def remove_footer(text): 
    if not text: 
        return "" 
    
    footer_markers = [
        "pozdrawiam", 
        "z powazżaniem", 
        "z powazaniem", 
        "ms leasing", 
        "msleasing",
        "specjalista", 
        "doradca", 
        "kierownik",
        "rodo", 
        "administratorem danych", 
        "ubezpieczenia",
        "ubezpieczenia msleasing",
        "aleja bohaterów monte cassino",
        "aleja bohaterow monte cassino",
    ]
    
    lowered = text.lower()
    positions = [] 

    for marker in footer_markers: 
        pos = lowered.find(marker)
        if pos != -1:
            positions.append(pos)

    if positions: 
        return text[:min(positions)]
    
    return text 

def context_is_footer(text,start,end):
    before = text[max(0, start - 250):start].lower()
    after = text[end:min(len(text), end + 250)].lower()
    context = before + " " + after

    footer_words = [
        "pozdrawiam",
        "z poważaniem",
        "z powazaniem",
        "ms leasing",
        "msleasing",
        "specjalista",
        "doradca", 
        "kierownik",
        "rodo", 
        "administratorem danych", 
        "ubezpieczenia",
        "ubezpieczenia msleasing",
        "aleja bohaterów monte cassino",
        "aleja bohaterow monte cassino",
    ]

    return any(word in context for word in footer_words)

def find_phone(text, forbidden_numbers=None):
    if not text:
        return ""
    
    forbidden_numbers = forbidden_numbers or set()
    text = remove_footer(text)

    patterns = [
        re.compile(
            r"(tel\.?|telefon|kom\.?|komórka|komorka|mobile|phone)[^0-9+]{0,30}(\+?48[\s\-]?)?([0-9][0-9\s\-]{7,20})",
        re.I
        ), 
        re.compile(
            r"(?<!\d)(\+?48[\s\-]?)?([0-9][0-9\s\-]{8,14})(?!\d)",
            re.I
        )
    ]

    for pattern in patterns: 
        for match in pattern.finditer(text): 
            start, end = match.span()
            raw = match.group(0)

            before = text[max(0, start - 40):start].lower()

            if "nip" in before or "regon" in before:
                continue

            if context_is_footer(text, start, end):
                continue

            phone = normalize_phone(raw) 

            if phone and clean_num(phone) not in forbidden_numbers:
                return phone
            
        return ""
    
def search_queries(company): 
    words = company.strip().split()
    queries = [f' "{company}']
        
    if len(words) >= 3:
        queries.append(f'"{words[0]} {words[1]} {words[2]}"')

    if len(words) >= 2:
        queries.append(f'"{words[0]} {words[1]}"')

    return queries
    
def gmail_search(gmail, company, max_threads = 10):
    seen = set()
    out = [] 

    for q in search_queries(company):
        res = gmail.users().messages().list(
            userId = "me",
            q = q,
            maxResults = max_threads 
        
        ).execute()

        for item in res.get("messages", []):
            mid = item["id"]

            if mid not in seen: 
                seen.add(mid)
                out.append(mid)

            if out: 
                break 

        return out 
    
def decode_part_body(part):
    data = part.get("body", {}).get("data")

    if not data:
         return ""
        
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors = "ignore")
    
def walk_parts(payload):
    yield payload 

    for p in payload.get("parts", []) or []:
        yield from walk_parts(p)

def extract_message_text_and_pdfs(gmail, msg_id, company):
    msg = gmail.users().messages().get(
        userId = "me",
        id = msg_id,
        format = "full"
    ).execute()

    payload = msg.get("payload", {})

    subject = ""
    sender = ""

    for h in payload.get("headers", []):
        name = h.get("name", "").lower()

        if name == "subject":
                subject = h.get("value", "")

        if name == "from":
                sender = h.get("value", "")
        
    if is_internal_or_bank_sender(sender):
            return "", [], subject, sender, True
        
    texts = [subject]
    pdf_paths = []

    for part in walk_parts(payload):
        mime = part.get("mimeType", "")
        filename = part.get("filename", "") or ""

        if mime == "text/plain":
            texts.append(decode_part_body(part))

        if filename.lower().endswith(".pdf") and part.get("body", {}).get("attachmentId"):
            att_id = part["body"]["attachmentId"]

            att = gmail.users().messages().attachments().get(
                userId = "me",
                messageId = "msg_id",
                id = att_id
            ).execute()

        data = base64.urlsafe_b64decode(att["data"].encode())

        safe_company = re.sub(r"[A-Za-z0-9_.-]+", "_", company[:40])
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)

        path = RAW_DIR / safe_company / f"{msg_id}_{safe_name}"
        path.parent.mkdir(parents = True, exist_ok = True)
        path.write_bytes(data)

        pdf_paths.append(path)

    return"\n".join(texts), pdf_paths, subject, sender, False
    
def pdf_texts(path):
    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""
        

def catalog_doc(conn, comapny, source_type, source_ref, raw_path, text):
    conn.execute(
        "INSERT INTO documents(company, soruce_type, source_ref, raw_path, text) VALUES (?, ?, ?, ?, ?)", 
        (comapny, source_type, source_ref, str(raw_path or ""), text or ""),
    )
    conn.commit()

def read_sheet_rows(sheets, spreadsheet_id, sheet_name, start, end):
    rng = f"{sheet_name}!A{start}:H{end}"

    return sheets.spreadsheets().values().get(
        spreadsheetId = spreadsheet_id,
        range = rng 
    ).execute().get("values", [])
    
def update_many_cells(sheets, spreadsheet_id, sheet_name, row, updates):
    data = []

    for col_letter, value in updates.items():
        data.append({
            "range": f"{sheet_name}!{col_letter}{row}",
            "values": [[value]]
        })
        
    if not data:
        return 
        
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId = spreadsheet_id,
        body = {
            "valueInputOption": "USER_ENTERED",
            "data": data
        }
    ).execute()

def phone_exists_in_sheet(sheets, spreadsheet_id, sheet_name, phone, current_row):
    result = sheets.spreadsheets().values().get(
        spreadsheetId = spreadsheet_id,
        range = f"{sheet_name}!F2:F"
    ).execute()

    values = result.get("values", [])
    searched = clean_num(phone)

    for idx, row in enumerate(values, start = 2):
        if idx == current_row:
            continue

        value = clean_num(row[0]) if row else ""

        if value and value == searched:
            return True
        
        return False
    
def process_row (conn, gmail, sheets, spreadsheet_id, sheet_name, row_num, row_values):
    company = row_values[COL_CLIENT - 1] if len(row_values) >= COL_CLIENT else ""

    if not company: 
        return
        
    exisiting_nip = clean_num(row_values[COL_NIP - 1]) if len(row_values) >= COL_NIP else ""
    exisiting_regon = clean_num(row_values[COL_REGON] - 1) if len(row_values) >= COL_REGON else ""
    exisiting_phone = row_values[COL_PHONE - 1] if len(row_values) >= COL_PHONE else "" 

    forbidden_numbers = set()

    if exisiting_nip:
        forbidden_numbers.add(exisiting_nip)

    if exisiting_regon:
        forbidden_numbers.add(exisiting_regon)
        
    if exisiting_phone:
        if phone_exists_in_sheet(sheets, spreadsheet_id, sheet_name, exisiting_phone, row_num):
            print(f"{row_num}: {company} - OBECNY TELEFON POWTARZA SIĘ, SZUKAM NOWEGO")

        else:
            print(f"{row_num}: {company} - TELEFON JUŻ JEST OK")
            return 
            
    msg_id = gmail_search(gmail, company)

    if not msg_id:
        update_many_cells(
            sheets,
            spreadsheet_id,
            sheet_name,
            row_num,
            {"H": "BRAK FIRMY W GMAILU"}
        )
        print(f"{row_num}: {company} - BRAK FIRMY W GMAILU")
        return
    
    phone = "" 
    sources = []
    skipped_count = 0

    for mid in msg_id:
        mail_text, pdf, subject, sender, skipped = extract_message_text_and_pdfs(gmail, mid, company)

        if skipped:
            skipped_count += 1
            continue
        
        catalog_doc(conn, company, "gmail", mid, "", mail_text)

        #PDF
        for p in pdf: 
            txt = pdf_texts(p)
            catalog_doc(conn, company, "pdf", mid, p, txt)

            phone = find_phone(txt, forbidden_numbers)

            if phone: 
                sources.append(f"TELEFON Z PDF: {p.name}")
                break

        if phone: 
            break 

        #MAIL BEZ STOPKI
        phone = find_phone(mail_text, forbidden_numbers)

        if phone:
            sources.append(f"TELEFON Z MAILA: {subject[:80]}")
            break 

    if phone: 
        if phone_exists_in_sheet(sheets, spreadsheet_id, sheet_name, phone, row_num):
            update_many_cells(
                sheets, 
                spreadsheet_id,
                sheet_name, 
                row_num,
                {
                    "H": f"TELEFON POWTARZA SIĘ - PRAWDOPODOBNIE STOPKA/BANKA/MS: {phone}"
                }
            )

            print(f"{row_num}: {company} - TELEFON POWTARZA SIĘ, NIE WPISANO {phone}")

        else: 
            status = "FIRMA JEST, BRAK TELEFONU W MAILU/PDF"

            if skipped_count:
                status += f" / POMINIĘTO MAILE WEWNĘTRZNE: {skipped_count}"

            update_many_cells(
                sheets,
                spreadsheet_id,
                sheet_name,
                row_num,
                {"H": status}
            )

            print(f"{row_num}: {company} - BRAK TELEFONU")

def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--start-row", type = int, required = True)
    parser.add_argument("--end-row", type = int, required = True)
    args = parser.parse_args()

    spreadsheet_id = os.environ["SPREADSHEET_ID"]
    sheet_name = os.environ.get("SHEET_NAME, Arkusz1")

    RAW_DIR.mkdir(exist_ok = True)

    conn = init_db()
    creds = get_creds()

    gmail = build("gmail", "v1", credentials = creds)
    sheets = build("sheets", "v4", credentials = creds)

    rows = read_sheet_rows(
        sheets, 
        spreadsheet_id,
        sheet_name,
        args.start_row,
        args.end_row,
    )

    for idx, row in enumerate(rows, start = args.start_row):
        print(f"Processing row {idx}")