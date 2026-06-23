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
        queries = [f ' "{company}']
        
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
            



    
    
    


                
 

