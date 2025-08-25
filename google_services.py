# utils/google_services.py
import io
import json
import logging
from pathlib import Path
from PIL import Image
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from config import GS_CRED_PATH, GS_SHEET_NAME, GS_TAB

def load_inventory_by_upc():
    """Build a dict of *many* UPC variants -> the same row list."""
    from utils.upc_helpers import upc_variants_from_sheet
    
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(str(GS_CRED_PATH), scopes=scopes)
    gc = gspread.authorize(creds)
    logging.info("Connecting to Google Sheet: %s / Tab: %s", GS_SHEET_NAME, GS_TAB)

    try:
        ws = gc.open(GS_SHEET_NAME).worksheet(GS_TAB)
        rows = ws.get_all_values()
    except Exception as e:
        logging.error("PriceCheck: sheet open/read error: %s", e)
        return {}

    logging.info("PriceCheck: loaded %d rows from sheet", len(rows))
    if not rows:
        return {}

    header = rows[0]
    logging.info("PriceCheck: header row: %s", header)

    index = {}
    collisions = 0
    for r in rows[1:]:
        if not r:
            continue
        raw_upc = (r[0] if len(r) > 0 else "").strip()
        if not raw_upc:
            continue
        for v in upc_variants_from_sheet(raw_upc):
            if v in index and index[v] is not r:
                collisions += 1
            index[v] = r

    logging.info("PriceCheck: indexed %d UPC keys (including variants), collisions=%d",
                 len(index), collisions)
    for i, k in enumerate(list(index.keys())[:5]):
        logging.info("PriceCheck: sample key %d: %r", i+1, k)
    return index
