"""
Sports League Photo Check-In (Streamlit) — Kiosk-Only + Photo Upload (Google Sheets + Drive)
-------------------------------------------------------------------------------------------
This version removes roster uploads entirely. Families enter all info **directly on the kiosk**,
and a **photo is required** (camera or file upload). Each submission is stored in Google Sheets
and the photo is uploaded to a Google Drive folder you control.

Brand: **Photograph BY TR, LLC**

NEW (per your request)
- ✅ No roster uploads; kiosk collects First/Last/Team/contacts/jersey (optional), package, notes, release, paid
- ✅ **Required photo** (uses device camera with `st.camera_input` or file uploader)
- ✅ Photo stored to **Google Drive**; file link & id saved to `Checkins` sheet
- ✅ Fields kept: Paid toggle, OrgName (from Settings)

----------
QUICK DEPLOY (Streamlit Community Cloud)
----------
1) Google Cloud service account with **Sheets API** + **Drive API** enabled.
2) In Streamlit **Advanced settings → Secrets**, set (TOML table format recommended):

   [GCP_SERVICE_ACCOUNT]
   type = "service_account"
   project_id = "YOUR_PROJECT_ID"
   private_key_id = "xxxxxxxxxxxxxxxx"
   private_key = "-----BEGIN PRIVATE KEY-----\n...PASTE THE VALUE FROM JSON, KEEP \n ESCAPES...\n-----END PRIVATE KEY-----\n"
   client_email = "your-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com"
   client_id = "1234567890"
   token_uri = "https://oauth2.googleapis.com/token"

   GSHEET_ID = "YOUR_SHEET_ID"              # spreadsheet with tabs: Checkins, Settings
   DRIVE_FOLDER_ID = "YOUR_DRIVE_FOLDER_ID" # Google Drive folder where photos will upload
   MANAGER_PIN = "9690"                     # change this
   # LOGO_URL = "https://.../your-logo.png" # optional
   # DEMO_MODE = "1"                        # optional: show UI without Google

3) In Google Sheets, create tabs: **Checkins**, **Settings** (exact spelling).
4) In Google Drive, create a folder for photos; copy its **Folder ID** from the URL.
5) Share BOTH the Sheet and the Folder with the **service account email** as **Editor**.
6) Deploy app → Manager → Settings → **Connection Test** to verify Sheets + Drive.

----------
REQUIREMENTS (requirements.txt)
----------
streamlit
pandas
qrcode[pil]
pillow
gspread
google-auth
google-api-python-client
"""

from __future__ import annotations

import io
import hashlib
import json
from datetime import datetime
from typing import Optional, Tuple
from collections.abc import Mapping

import pandas as pd
import streamlit as st
from PIL import Image
import qrcode

# Google
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ----------------------------- App Config ------------------------------------
st.set_page_config(page_title="Sports Photo Check-In", page_icon="📸", layout="wide")

# Secrets
GCP_SERVICE_ACCOUNT = st.secrets.get("GCP_SERVICE_ACCOUNT", None)
GSHEET_ID = st.secrets.get("GSHEET_ID", "")
DRIVE_FOLDER_ID = st.secrets.get("DRIVE_FOLDER_ID", "")
MANAGER_PIN = st.secrets.get("MANAGER_PIN", "9690")
LOGO_URL = st.secrets.get("LOGO_URL", "")
DEMO_MODE = str(st.secrets.get("DEMO_MODE", "")).strip().lower() in {"1", "true", "yes"}

BRAND_NAME = "Photograph BY TR, LLC"
BRAND_PRIMARY = "#111827"
BRAND_ACCENT = "#f59e0b"
BRAND_EMAILS = "trossiter@photographbytr.com; photographbytr@gmail.com; rosskid0911@gmail.com"

# ----------------------------- Branding --------------------------------------
BRAND_CSS = f"""
<style>
:root {{ --brand-primary:{BRAND_PRIMARY}; --brand-accent:{BRAND_ACCENT}; }}
/* Light mode: brand color headings */
h1,h2,h3,h4,h5,h6 {{ color: var(--brand-primary) !important; }}
/* Dark mode: near-white headings for contrast */
@media (prefers-color-scheme: dark) {{
  h1,h2,h3,h4,h5,h6 {{ color: #f9fafb !important; }}
  .brand-hero {{ background: rgba(245,158,11,0.25) !important; border-left-color: #fbbf24 !important; }}
}}
.stButton>button {{ border-radius: 12px; }}
.brand-hero {{
  padding: .6rem .9rem; border-left: 6px solid var(--brand-accent);
  background: rgba(245,158,11,.07); margin: .6rem 0 .8rem;
}}
.badge {{ display:inline-block; padding:2px 8px; border-radius:999px; background:var(--brand-accent); color:white; font-size:.8rem; margin-left:6px; }}
</style>
"""

# ----------------------------- Helpers ---------------------------------------
def make_qr_image(payload: str, box_size: int = 10) -> Image.Image:
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=box_size, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img

def slugify(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isalnum()).lower()

def gen_player_id(first: str, last: str, team: str) -> str:
    base = f"{first}-{last}-{team}".strip()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]

def short_code(pid: str) -> str:
    return hashlib.sha1(pid.encode("utf-8")).hexdigest()[:6].upper()

def get_mode_param() -> str:
    """Use the modern query params API only (avoid mixing with experimental)."""
    try:
        params = st.query_params  # Streamlit >= 1.30
        val = params.get("mode", "")
        if isinstance(val, list):
            return val[0] if val else ""
        return val or ""
    except Exception:
        # On very old Streamlit, just default to manager view
        return ""

# ----------------------------- Google Clients --------------------------------
@st.cache_resource(show_spinner=False)
def get_google():
    if DEMO_MODE:
        # Minimal stubs for demo without Google
        return {"sh": None, "drive": None}

    if not GSHEET_ID:
        st.error("M

if __name__ == "__main__":
    main()

