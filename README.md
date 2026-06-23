# Data Chat MVP – Automated Client Database Creation Using Gmail and Google Sheets

## Project Overview

Data Chat MVP is an automation project designed to automatically collect, verify, and enrich client data stored in Google Sheets using information available in Gmail and PDF attachments.

The main objective of the project is to reduce the manual effort required to search for client information in emails and documents while accelerating the creation of a complete and accurate contact database.

## Scope

The system retrieves a list of companies from a Google Sheets file and, for each client, performs the following actions:

* searches for related email messages,
* analyzes email content,
* downloads and processes PDF attachments,
* identifies relevant client information,
* saves the extracted data directly to the spreadsheet.

## Data Processed

The project automatically extracts and updates:

* company name,
* NIP (Tax Identification Number),
* REGON (Business Registry Number),
* contact phone number,
* data source information,
* verification status.

## Integrations

### Gmail API

Used to search client-related email conversations and retrieve message content and attachments.

### Google Sheets API

Used to read input data and automatically update results in the spreadsheet.

### PDF Documents

The system analyzes attached PDF files to identify business and contact information.

## Data Extraction Logic

### NIP and REGON

NIP and REGON numbers are searched for in:

* email content,
* PDF documents.

If only one identifier is found, public registries may be used to retrieve the missing information.

### Contact Phone Numbers

Phone numbers are extracted with the following priority:

1. PDF documents,
2. email content.

This approach reduces the risk of collecting phone numbers that appear only in email signatures.

## Data Quality Controls

To improve data accuracy, the system includes several validation and filtering mechanisms.

### Internal Email Filtering

Messages originating from MS Leasing domains are excluded from phone number extraction to prevent employee contact details from being assigned to clients.

### Bank Email Filtering

Emails from banks and financial institutions are also excluded, as they often contain contact details of bank representatives rather than clients.

### Signature Detection

The system recognizes common email signature elements and ignores phone numbers found within them.

### Duplicate Detection

If the same phone number appears for multiple companies, the record is flagged for verification to reduce the risk of storing employee, intermediary, or institution contact numbers.

## Expected Outcome

The result is a continuously updated and verified client database containing accurate identification and contact information extracted automatically from organizational emails and documents.

The project significantly reduces the time required for manual data collection, minimizes human errors, and improves the overall quality and reliability of client information.
