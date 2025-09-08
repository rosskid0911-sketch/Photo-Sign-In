"""
Sports League Photo Check-In (Streamlit) — Kiosk-Only + Photo Upload (Google Sheets + Drive)
-------------------------------------------------------------------------------------------
Families enter all info directly on the kiosk and a photo is required (camera or upload).
Each submission writes a row to Google Sheets and uploads the photo to a Drive folder.

Brand: Photograph BY TR, LLC
"""
from __future__ import annotations

import base64, io
from pathlib import Path
import requests  # add 'requests' to requirements.txt

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.cloud import storage

import io
import hashlib
import json
from datetime import datetime
from datetime import timedelta

from typing import Tuple
from collections.abc import Mapping

import pandas as pd
import streamlit as st
from PIL import Image
import qrcode

from pathlib import Path


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
CASHAPP_URL = st.secrets.get("CASHAPP_URL", "") or "https://cash.app/$photobyTR"
PAYPAL_URL  = st.secrets.get("PAYPAL_URL", "")  or "https://paypal.me/photographbytr/0"



# Branding
BRAND_NAME = "Photograph BY TR, LLC"
BRAND_PRIMARY = "#111827"
BRAND_ACCENT = "#f59e0b"
BRAND_EMAILS = "trossiter@photographbytr.com; photographbytr@gmail.com; rosskid0911@gmail.com"

# ----------------------------- Branding CSS ----------------------------------
# NOTE: This is an f-string; all literal CSS braces must be doubled {{ }}
BRAND_CSS = f"""
<style>
:root {{ --brand-primary:{BRAND_PRIMARY}; --brand-accent:{BRAND_ACCENT}; }}
/* Light mode: brand color headings */
h1,h2,h3,h4,h5,h6 {{ color: var(--brand-primary) !important; }}
/* Dark mode: near-white headings for contrast */
@media (prefers-color-scheme: dark) {{
  /* keep title readable on dark backgrounds */
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
    """Use modern query params API (avoid mixing experimental APIs)."""
    try:
        val = st.query_params.get("mode", "")
        if isinstance(val, list):
            return val[0] if val else ""
        return val or ""
    except Exception:
        return ""
def display_logo(width: int = 220):
    """Show logo from LOGO_URL first; if that fails, try common local paths."""
    src = (LOGO_URL or "").strip()
    tried = []
    if src:
        try:
            st.image(src, width=width)
            return
        except Exception as e:
            tried.append(("LOGO_URL", src, str(e)))

    for p in ("assets/logo.png", "assets/logo.jpg", "logo.png", "logo.jpg"):
        if Path(p).exists():
            try:
                st.image(p, width=width)
                return
            except Exception as e:
                tried.append(("local", p, str(e)))

    # If nothing worked, show a gentle hint once
    if tried:
        st.caption(
          "Logo failed to load. Ensure LOGO_URL is a public, direct image link "
          "(e.g., Drive ‘uc?export=view&id=…’ or a GitHub raw URL), "
          "or add assets/logo.png to your repo."
        )
@st.cache_data(show_spinner=False)
def load_logo_bytes() -> tuple[bytes | None, str | None]:
    """Front-load the logo once and reuse it everywhere."""
    # Prefer local assets (most reliable)
    for p in ("assets/logo.png", "assets/logo.jpg", "logo.png", "logo.jpg"):
        if Path(p).exists():
            return Path(p).read_bytes(), ("image/png" if p.lower().endswith(".png") else "image/jpeg")
    # Fallback to LOGO_URL
    url = (LOGO_URL or "").strip()
    if url:
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            ct = r.headers.get("content-type", "image/png")
            return r.content, ct
        except Exception:
            return None, None
    return None, None

def display_logo(width: int = 220):
    data, ct = load_logo_bytes()
    if data:
        st.image(io.BytesIO(data), width=width)
    else:
        st.caption("Logo failed to load. Use a public direct image URL in LOGO_URL, "
                   "or add assets/logo.png to the repo.")
def payment_footer():
    # simple styling for nice buttons
    st.markdown("""
    <style>
      .pay-wrap { display:flex; gap:16px; flex-wrap:wrap; margin: 1rem 0 0; }
      .pay-btn {
        display:inline-block; padding:10px 14px; border-radius:12px;
        font-weight:700; text-decoration:none; color:white;
        box-shadow: 0 2px 6px rgba(0,0,0,.15);
      }
      .pay-btn.cashapp { background:#16a34a; } /* green */
      .pay-btn.paypal  { background:#0070ba; } /* paypal blue */
      .pay-note { font-size:.9rem; opacity:.8; margin-top:.25rem; }
    </style>
    """, unsafe_allow_html=True)

    st.divider()
    st.subheader("Pay for your photo package")
    st.caption("Tap a button or scan a code to pay. Be sure to toggle **Paid** in the form above.")

    col1, col2 = st.columns(2)
    if CASHAPP_URL:
        with col1:
            st.markdown(f'<a class="pay-btn cashapp" href="{CASHAPP_URL}" target="_blank" rel="noopener">Pay with Cash App</a>', unsafe_allow_html=True)
            st.image(make_qr_image(CASHAPP_URL, box_size=6), caption="Scan to pay (Cash App)", width=160)
            st.text(CASHAPP_URL)
    else:
        col1.caption("Cash App link not set.")

    if PAYPAL_URL:
        with col2:
            st.markdown(f'<a class="pay-btn paypal" href="{PAYPAL_URL}" target="_blank" rel="noopener">Pay with PayPal</a>', unsafe_allow_html=True)
            st.image(make_qr_image(PAYPAL_URL, box_size=6), caption="Scan to pay (PayPal)", width=160)
            st.text(PAYPAL_URL)
    else:
        col2.caption("PayPal link not set.")


# --------------------- Robust service account parsing -------------------------
def parse_service_account(raw) -> dict:
    """
    Accepts:
      - TOML table under [GCP_SERVICE_ACCOUNT] (Mapping)
      - JSON string, optionally inside ```json fences or quoted
    Returns dict or raises ValueError with clear guidance.
    """
    if raw is None:
        raise ValueError("GCP_SERVICE_ACCOUNT is missing. In Secrets, add a [GCP_SERVICE_ACCOUNT] table or a triple-quoted JSON block.")
    if isinstance(raw, Mapping):
        return dict(raw)

    s = str(raw).strip()
    if not s:
        raise ValueError("GCP_SERVICE_ACCOUNT is empty. Paste the JSON or use the TOML table format.")

    # Strip accidental code fences: ```json ... ```  or  ``` ... ```
    if s.startswith("```"):
        stripped = s.strip().strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
        s = stripped

    # Remove accidental outer quotes if present
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        inner = s[1:-1].strip()
        if inner.startswith("{"):
            s = inner

    if not s.startswith("{"):
        raise ValueError("GCP_SERVICE_ACCOUNT is not valid JSON. Use [GCP_SERVICE_ACCOUNT] TOML table or wrap the exact JSON in triple quotes.")

    try:
        return json.loads(s)
    except Exception as e:
        raise ValueError(f"Could not parse JSON in GCP_SERVICE_ACCOUNT: {e}")

# ----------------------------- Google Clients --------------------------------
@st.cache_resource(show_spinner=False)
def get_google():
    if DEMO_MODE:
        return {"sh": None, "drive": None}

    if not GSHEET_ID:
        st.error("Missing **GSHEET_ID** secret.")
        st.stop()
    if not DRIVE_FOLDER_ID:
        st.error("Missing **DRIVE_FOLDER_ID** secret (Google Drive folder for photos).")
        st.stop()

    try:
        creds_info = parse_service_account(st.secrets.get("GCP_SERVICE_ACCOUNT", None))
    except ValueError as e:
        st.error(str(e))
        st.stop()

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(GSHEET_ID)
        drive = build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error("Failed to authenticate or open Google resources. Check sharing, IDs, and enabled APIs.")
        st.exception(e)
        st.stop()

    # Ensure worksheets & headers
    for ws_name, cols in [
        ("Checkins", [
            "ts","player_id","short_code","first_name","last_name","team","parent_email","parent_phone",
            "confirmed_email","confirmed_phone","jersey","confirmed_jersey","package","notes","release_accepted",
            "paid","org_name","brand","brand_emails",
            "photo_filename","photo_drive_id","photo_link"
        ]),
        ("Settings", ["key","value"]),
    ]:
        try:
            ws = sh.worksheet(ws_name)
            values = ws.get_all_values()
            if not values:
                ws.update([cols])
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=ws_name, rows=1000, cols=max(20, len(cols)))
            ws.update([cols])

    return {"sh": sh, "drive": drive}

@st.cache_data(ttl=20, show_spinner=False)
def gs_read_df(sheet_name: str) -> pd.DataFrame:
    if DEMO_MODE:
        return pd.DataFrame()
    sh = get_google()["sh"]
    ws = sh.worksheet(sheet_name)
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame()
    header, rows = values[0], values[1:]
    df = pd.DataFrame(rows, columns=header).replace({"": pd.NA})
    return df

def gs_write_df(sheet_name: str, df: pd.DataFrame):
    if DEMO_MODE:
        return
    sh = get_google()["sh"]
    ws = sh.worksheet(sheet_name)
    df2 = df.copy().where(pd.notnull(df), "")
    data = [list(df2.columns)] + df2.astype(str).values.tolist()
    ws.clear()
    ws.update(data)

# Settings KV
SETTINGS_SHEET = "Settings"

def gs_get_setting(key: str, default: str = "") -> str:
    df = gs_read_df(SETTINGS_SHEET)
    if df.empty or "key" not in df.columns:
        return default
    hit = df[df["key"] == key]
    if not hit.empty:
        return str(hit.iloc[0]["value"]) if pd.notna(hit.iloc[0]["value"]) else default
    return default

def gs_set_setting(key: str, value: str):
    df = gs_read_df(SETTINGS_SHEET)
    if df.empty:
        df = pd.DataFrame([[key, value]], columns=["key","value"])
    else:
        if key in df["key"].values:
            df.loc[df["key"] == key, "value"] = value
        else:
            df = pd.concat([df, pd.DataFrame([[key, value]], columns=["key","value"])], ignore_index=True)
    gs_write_df(SETTINGS_SHEET, df)

# Check-ins
def sb_insert_checkin(row: dict):
    existing = gs_read_df("Checkins")
    if existing.empty:
        new_df = pd.DataFrame([row])
    else:
        for col in [c for c in row.keys() if c not in existing.columns]:
            existing[col] = pd.NA
        new_df = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    gs_write_df("Checkins", new_df)

@st.cache_data(ttl=20, show_spinner=False)
def sb_load_checkins() -> pd.DataFrame:
    return gs_read_df("Checkins")

# Google Drive upload
def gcs_upload_photo(filename: str, data: bytes, mimetype: str = "image/jpeg"):
    creds_info = parse_service_account(st.secrets.get("GCP_SERVICE_ACCOUNT"))
    client = storage.Client.from_service_account_info(creds_info)
    bucket_name = st.secrets["GCS_BUCKET"]
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(filename)

    # Upload
    blob.upload_from_string(data, content_type=mimetype)

    # Try to make public; if UBLA blocks ACLs, fall back to a signed URL (max 7 days)
    try:
        blob.make_public()
        url = blob.public_url
    except Exception:
        # Configurable TTL via Secrets; clamp to [1, 7] days to satisfy GCS limits
        raw = st.secrets.get("GCS_SIGNED_URL_TTL_DAYS", 7)
        try:
            ttl_days = int(str(raw))
        except Exception:
            ttl_days = 7
        ttl_days = max(1, min(7, ttl_days))
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(days=ttl_days),
            method="GET",
        )
    return blob.name, url


    # Make public (simple). If you prefer signed URLs, ask me and I’ll swap to signed URLs.
    try:
        blob.make_public()
        url = blob.public_url
    except Exception:
        # Fallback: long-lived signed URL if public ACLs are restricted
        url = blob.generate_signed_url(version="v4", expiration=60*60*24*365, method="GET")
    return blob.name, url
def drive_upload_photo(filename: str, data: bytes, mimetype: str = "image/jpeg"):
    # If a GCS bucket is configured, use it instead of Drive
    if st.secrets.get("GCS_BUCKET"):
        return gcs_upload_photo(filename, data, mimetype)
    if DEMO_MODE:
        return (f"demo_{filename}", f"https://example.com/{filename}")
    drive = get_google()["drive"]
    body = {"name": filename, "parents": [DRIVE_FOLDER_ID], "mimeType": mimetype}
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mimetype, resumable=False)
    file = drive.files().create(body=body, media_body=media, fields="id, webViewLink, webContentLink").execute()
    file_id = file.get("id")
    link = file.get("webViewLink") or file.get("webContentLink") or f"https://drive.google.com/file/d/{file_id}/view"
    return file_id, link

# ----------------------------- Manager UI ------------------------------------
def export_section(checkins: pd.DataFrame):
    st.subheader("Exports")
    st.dataframe(checkins, use_container_width=True, height=320)
    st.download_button(
        "Download Check-Ins CSV",
        data=checkins.to_csv(index=False).encode("utf-8"),
        file_name=f"checkins_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        type="primary"
    )
    team_col = "Team" if "Team" in checkins.columns else ("team" if "team" in checkins.columns else None)
    if not checkins.empty and team_col:
        teams = sorted([t for t in checkins[team_col].dropna().unique() if str(t).strip()])
        if teams:
            team = st.selectbox("Per-Team export", teams)
            team_df = checkins[checkins[team_col].astype(str).str.lower() == str(team).lower()]
            st.download_button(
                f"Download {team} Check-Ins",
                data=team_df.to_csv(index=False).encode("utf-8"),
                file_name=f"checkins_{slugify(team)}.csv"
            )

def settings_section():
    st.subheader("Event / Organization Settings")
    if DEMO_MODE:
        st.warning("DEMO_MODE is ON - the app will not write to Google Sheets or Drive. Turn it off in Secrets to go live.")

    org_default = gs_get_setting("ORG_NAME", "")
    org_name = st.text_input("Organization / League Name (shown on kiosk)", value=org_default)
    if st.button("Save Settings"):
        gs_set_setting("ORG_NAME", org_name)
        st.success("Settings saved.")

    display_logo(width=220)

    # -------- Connection Test (only runs when DEMO_MODE is OFF) --------
    with st.expander("Connection Test", expanded=False):
        if DEMO_MODE:
            st.info("DEMO_MODE is on; skipping live tests. Turn it off in Secrets to run Google checks.")
        else:
            raw = st.secrets.get("GCP_SERVICE_ACCOUNT", None)
            fmt = (
                "mapping (TOML table)" if isinstance(raw, Mapping)
                else ("string (JSON)" if isinstance(raw, str) else str(type(raw)))
            )
            st.text("Detected GCP_SERVICE_ACCOUNT: " + fmt)
            if isinstance(raw, str):
                s = raw.strip()
                st.caption(f"Length: {len(s)} · startswith: {s[:1]!r}")
            st.text("GSHEET_ID present: " + str(bool(GSHEET_ID)))
            st.text("DRIVE_FOLDER_ID present: " + str(bool(DRIVE_FOLDER_ID)))
            if st.button("Run connection test"):
                try:
                    now = datetime.utcnow().isoformat()
                    gs_set_setting("HEALTHCHECK", now)
                    ping = gs_get_setting("HEALTHCHECK", "")
                    dummy_bytes = b"healthcheck"
                    fid, link = drive_upload_photo("healthcheck_" + now + ".txt", dummy_bytes, mimetype="text/plain")
                    st.success("Sheets OK (HEALTHCHECK=" + str(ping) + ") · Drive OK (file id " + str(fid) + ")")
                except Exception as e:
                    st.error("Connection test failed. Verify Secrets, sharing on Sheet & Folder, and enabled APIs.")
                    st.exception(e)

def page_manager():
    st.markdown(BRAND_CSS, unsafe_allow_html=True)
    st.title(f"📸 {BRAND_NAME} — Manager")
    st.markdown(f"<div class='brand-hero'><strong>Delivery CC:</strong> {BRAND_EMAILS} <span class='badge'>BRAND</span></div>", unsafe_allow_html=True)

    # PIN gate
    if "auth" not in st.session_state:
        st.session_state.auth = False
    if not st.session_state.auth:
        pin = st.text_input("Enter manager PIN", type="password")
        if st.button("Unlock"):
            if pin == MANAGER_PIN:
                st.session_state.auth = True
                st.rerun()
            else:
                st.error("Incorrect PIN")
        st.stop()

    with st.expander("Settings", expanded=True):
        settings_section()

    st.subheader("Share & QR")
    st.caption("Paste your deployed app URL below and we'll generate the kiosk link + QR.")
    base_url = st.text_input("Your app URL", placeholder="https://your-app.streamlit.app")
    if base_url:
        base_url = base_url.strip()
        if "?" in base_url:
            base_url = base_url.split("?")[0]
        kiosk_link = base_url.rstrip("/") + "/?mode=kiosk"
        st.write("**Kiosk link:**")
        st.code(kiosk_link)
        img = make_qr_image(kiosk_link, box_size=8)
        st.image(img, caption="Scan to open kiosk", width=240)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        st.download_button("Download QR (PNG)", data=buf.getvalue(), file_name="kiosk_qr.png", type="primary")

    checkins = sb_load_checkins()
    with st.expander("Exports", expanded=True):
        export_section(checkins)

    st.info("This build has **no roster**. All data comes from the kiosk form with required photo upload.")

# ----------------------------- Kiosk UI --------------------------------------
def page_kiosk():
    st.markdown(BRAND_CSS, unsafe_allow_html=True)

    # show logo from LOGO_URL or fall back to assets/logo.png
    display_logo(width=220)

    org_name = gs_get_setting("ORG_NAME", "")
    title_suffix = f" — {org_name}" if org_name else ""
    st.title(f"{BRAND_NAME} — Photo Day Check-In{title_suffix}")
    st.caption("Please complete all fields and upload a photo. A staff member can assist if needed.")


    with st.form("kiosk_form", clear_on_submit=True):
        colA, colB = st.columns(2)
        with colA:
            first = st.text_input("Player First Name", max_chars=50)
            last = st.text_input("Player Last Name", max_chars=50)
            team = st.text_input("Team / Division", max_chars=80)
            jersey = st.text_input("Jersey # (optional)", max_chars=10)
            try:
                paid = st.toggle("Paid (prepay or on-site)", value=False)
            except Exception:
                paid = st.checkbox("Paid (prepay or on-site)", value=False)
        with colB:
            parent_email = st.text_input("Parent Email (for final photo delivery)")
            parent_phone = st.text_input("Parent Phone")
            pkg = st.selectbox("Photo Package (optional)", ["Not selected", "Basic", "Deluxe", "Team+Individual"])
            notes = st.text_area("Notes (pose requests, etc.)")
            release = st.checkbox("I agree to the photo release/policy")

        st.markdown("**Photo (required)** — choose one:")
        cam = st.camera_input("Take photo with camera (preferred)")
        up = st.file_uploader("Or upload an image file", type=["jpg","jpeg","png","heic","webp"])

        submitted = st.form_submit_button("Complete Check-In", type="primary")

    if submitted:
        # Validate
        if not (first and last and team and parent_email and parent_phone and release):
            st.error("Please complete all required fields and agree to the release.")
            return
        if not (cam or up):
            st.error("Photo is required. Please use the camera or upload a file.")
            return

        # Prepare IDs
        pid = gen_player_id(first, last, team)
        scode = short_code(pid)

        # Choose photo bytes & mimetype
        if cam is not None:
            photo_bytes = cam.getvalue()
            mimetype = cam.type or "image/jpeg"
            ext = ".jpg" if "jpeg" in mimetype else ".png"
        else:
            photo_bytes = up.getvalue()
            mimetype = up.type or "image/jpeg"
            name = (up.name or "").lower()
            if name.endswith((".jpg",".jpeg")): ext = ".jpg"
            elif name.endswith(".png"): ext = ".png"
            else: ext = ".jpg"

        # Compose filename
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        base_name = f"{slugify(org_name)}_{slugify(team)}_{slugify(last)}_{slugify(first)}_{scode}_{ts}{ext}"

        try:
            fid, link = drive_upload_photo(base_name, photo_bytes, mimetype=mimetype)
        except Exception as e:
            st.error("Photo upload to Google Drive failed. Please alert a staff member.")
            st.exception(e)
            return

        new_row = {
            "ts": datetime.utcnow().isoformat(),
            "player_id": pid,
            "short_code": scode,
            "first_name": first,
            "last_name": last,
            "team": team,
            "parent_email": parent_email,
            "parent_phone": parent_phone,
            "confirmed_email": parent_email,
            "confirmed_phone": parent_phone,
            "jersey": str(jersey),
            "confirmed_jersey": str(jersey),
            "package": pkg,
            "notes": notes,
            "release_accepted": bool(release),
            "paid": "TRUE" if paid else "FALSE",
            "org_name": org_name,
            "brand": BRAND_NAME,
            "brand_emails": BRAND_EMAILS,
            "photo_filename": base_name,
            "photo_drive_id": fid,
            "photo_link": link,
        }
        sb_insert_checkin(new_row)
        st.success("Checked in and photo uploaded! Thank you.")
payment_footer()
# ----------------------------- Router ----------------------------------------
def main():
    mode = get_mode_param()
    if mode == "kiosk":
        page_kiosk()
        return

    tab1, tab2 = st.tabs(["Manager", "Kiosk (preview)"])
    with tab1:
        page_manager()
    with tab2:
        page_kiosk()

# ----------------------------- Optional smoke tests ---------------------------
def _run_smoke_tests():
    """Runs only when RUN_TESTS is set in Secrets."""
    # CSS f-string has doubled braces
    assert "{{" in BRAND_CSS and "}}" in BRAND_CSS
    # helper basics
    assert slugify("A B-C!") == "abc"
    pid = gen_player_id("A", "B", "Team"); assert len(pid) == 10
    sc = short_code(pid); assert len(sc) == 6

    # parse_service_account accepts a TOML-style mapping (dict)
    m = {
        "type": "service_account",
        "project_id": "p",
        "private_key_id": "k",
        # NOTE: keep this a short placeholder; do NOT add real newlines here
        "private_key": "KEY",
        "client_email": "a@p.iam.gserviceaccount.com",
        "client_id": "1",
        "token_uri": "https://oauth2.googleapis.com/token"
    }
    d = parse_service_account(m); assert d["project_id"] == "p"

    # parse_service_account accepts a JSON string as well
    j = "{\"type\":\"service_account\",\"project_id\":\"p\",\"private_key_id\":\"k\",\"private_key\":\"KEY\",\"client_email\":\"a@p.iam.gserviceaccount.com\",\"client_id\":\"1\",\"token_uri\":\"https://oauth2.googleapis.com/token\"}"
    d2 = parse_service_account(j); assert d2["client_email"].endswith("iam.gserviceaccount.com")

    # empty value should raise
    try:
        parse_service_account("")
        raise AssertionError("Expected ValueError for empty secret")
    except ValueError:
        pass

# Only run when explicitly enabled in Secrets
if str(st.secrets.get("RUN_TESTS", "")).strip().lower() in {"1", "true", "yes"}:
    _run_smoke_tests()

if __name__ == "__main__":
    main()
