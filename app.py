"""
Sports League Photo Check‑In (Streamlit) — Kiosk‑Only + Photo Upload (Google Sheets + Drive)
-------------------------------------------------------------------------------------------
This version removes roster uploads entirely. Families enter all info **directly on the kiosk**,
and a **photo is required** (camera or file upload). Each submission is stored in Google Sheets
and the photo is uploaded to a Google Drive folder you control.

Brand: **Photograph BY TR, LLC** · Studio emails: photorgraphbytr@gmail.com; trossiter@photographybytr.com

NEW (per your request)
- ✅ No roster uploads; kiosk collects First/Last/Team/contacts/jersey/etc.
- ✅ **Required photo** (uses device camera with `st.camera_input` or file uploader)
- ✅ Photo stored to **Google Drive**; file link & id saved to `Checkins` sheet
- ✅ Fields kept: Paid toggle, OrgName (from Settings)

----------
QUICK DEPLOY (Streamlit Community Cloud)
----------
1) Google Cloud service account with **Sheets API** + **Drive API** enabled.
2) In Streamlit **Advanced settings → Secrets**, set:

   [GCP_SERVICE_ACCOUNT]
   type = "service_account"
   project_id = "YOUR_PROJECT_ID"
   private_key_id = "xxxxxxxxxxxxxxxx"
   private_key = "-----BEGIN PRIVATE KEY-----
...
-----END PRIVATE KEY-----
"
   client_email = "your-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com"
   client_id = "1234567890"
   token_uri = "https://oauth2.googleapis.com/token"

   GSHEET_ID = "YOUR_SHEET_ID"             # spreadsheet with tabs: Checkins, Settings
   DRIVE_FOLDER_ID = "YOUR_DRIVE_FOLDER_ID" # Google Drive folder where photos will upload
   MANAGER_PIN = "9690"                     # change this
   LOGO_URL = "https://.../your-logo.png"   # optional

3) In Google Sheets, create tabs: **Checkins**, **Settings** (exact spelling).
4) In Google Drive, create a folder for photos; copy its **Folder ID** from the URL.
5) Share BOTH the Sheet and the Folder with the **service account email** as **Editor**.
6) Deploy app → Manager → Settings → **Connection Test** to verify Sheets + Drive.

----------
REQUIREMENTS (requirements.txt)
----------
streamlit
pandas
rapidfuzz
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

import pandas as pd
from rapidfuzz import process, fuzz  # (kept for future fuzzy search needs)
import streamlit as st
from PIL import Image
import qrcode

# Google
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from collections.abc import Mapping

# ----------------------------- App Config ------------------------------------
st.set_page_config(page_title="Sports Photo Check‑In", page_icon="📸", layout="wide")

# Secrets
GCP_SERVICE_ACCOUNT = st.secrets.get("GCP_SERVICE_ACCOUNT", None)
GSHEET_ID = st.secrets.get("GSHEET_ID", "")
DRIVE_FOLDER_ID = st.secrets.get("DRIVE_FOLDER_ID", "")
MANAGER_PIN = st.secrets.get("MANAGER_PIN", "9690")
LOGO_URL = st.secrets.get("LOGO_URL", "")
DEMO_MODE = str(st.secrets.get("DEMO_MODE", "")).strip().lower() in {"1","true","yes"}

BRAND_NAME = "Photograph BY TR, LLC"
BRAND_PRIMARY = "#111827"
BRAND_ACCENT = "#f59e0b"
BRAND_EMAILS = "trossiter@photographbytr.com; photographbytr@gmail.com; rosskid0911@gmail.com"

# ----------------------------- Branding --------------------------------------
# NOTE: because this is an f-string, ALL literal CSS braces must be doubled {{ }}.
BRAND_CSS = f"""
<style>
:root {{ --brand-primary:{BRAND_PRIMARY}; --brand-accent:{BRAND_ACCENT}; }}
/* Default (light mode): headings use brand color for identity */
h1,h2,h3,h4,h5,h6 {{ color: var(--brand-primary) !important; }}
/* High-contrast for dark mode so the title 'Photograph BY TR, LLC' stays readable */
@media (prefers-color-scheme: dark) {{
  /* The error was previously caused by an invalid '#' comment here */
  h1,h2,h3,h4,h5,h6 {{ color: #f9fafb !important; }} /* near-white */
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

def parse_service_account(raw) -> dict:
    """Robustly parse the service account from Streamlit secrets.
    Accepts:
      - a TOML table (mapping) under [GCP_SERVICE_ACCOUNT]
      - a JSON string (optionally inside ```json fences or quoted)
    Raises ValueError with actionable guidance instead of a JSONDecodeError.
    """
    if raw is None:
        raise ValueError("GCP_SERVICE_ACCOUNT is missing. In Secrets, add a [GCP_SERVICE_ACCOUNT] table or a triple-quoted JSON block.")
    if isinstance(raw, Mapping):
        # Already a TOML table -> dict
        return dict(raw)

    s = str(raw)
    if s is None:
        raise ValueError("GCP_SERVICE_ACCOUNT is not set.")
    s = s.strip()
    if not s:
        raise ValueError("GCP_SERVICE_ACCOUNT is empty. Paste the JSON or use the TOML table format.")

    # Strip accidental code fences: ```json ... ``` or ``` ... ```
    if s.startswith("```"):
        stripped = s.strip().strip("`")
        # handle both ```json and ```
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
        s = stripped

    # If someone pasted a quoted JSON string (e.g. "{...}") remove outer quotes
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        inner = s[1:-1].strip()
        if inner.startswith("{"):
            s = inner

    # If it still doesn't start with '{', it's not JSON
    if not s.startswith("{"):
        raise ValueError("GCP_SERVICE_ACCOUNT is not valid JSON. Use [GCP_SERVICE_ACCOUNT] TOML table or wrap the exact JSON in triple quotes.")

    try:
        return json.loads(s)
    except Exception as e:
        raise ValueError(f"Could not parse JSON in GCP_SERVICE_ACCOUNT: {e}")


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

# Query param compat
def get_mode_param() -> str:
    """Use the modern query params API only (avoid mixing with experimental)."""
    try:
        val = st.query_params.get("mode", "")
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
        # Minimal stubs
        return {"sh": None, "drive": None}

    if not GSHEET_ID:
        st.error("Missing **GSHEET_ID** secret.")
        st.stop()
    if not DRIVE_FOLDER_ID:
        st.error("Missing **DRIVE_FOLDER_ID** secret (Google Drive folder for photos).")
        st.stop()

    # Parse the service account with strong validation
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

    # Ensure worksheets
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
        # In demo mode, just return empty frames
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
        # No-op in demo mode
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

# Checkins

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

def drive_upload_photo(filename: str, data: bytes, mimetype: str = "image/jpeg") -> Tuple[str, str]:
    if DEMO_MODE:
        # Return fake IDs/links in demo mode
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
        "Download Check‑Ins CSV",
        data=checkins.to_csv(index=False).encode("utf-8"),
        file_name=f"checkins_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        type="primary"
    )
    team_col = "Team" if "Team" in checkins.columns else ("team" if "team" in checkins.columns else None)
    if not checkins.empty and team_col:
        teams = sorted([t for t in checkins[team_col].dropna().unique() if str(t).strip()])
        if teams:
            team = st.selectbox("Per‑Team export", teams)
            team_df = checkins[checkins[team_col].astype(str).str.lower() == str(team).lower()]
            st.download_button(
                f"Download {team} Check‑Ins",
                data=team_df.to_csv(index=False).encode("utf-8"),
                file_name=f"checkins_{slugify(team)}.csv"
            )

    st.info("This build has **no roster**. All data comes from the kiosk form with required photo upload.")


def settings_section():
    st.subheader("Event / Organization Settings")
    if DEMO_MODE:
        st.warning("DEMO_MODE is ON - the app will not write to Google Sheets or Drive. Turn it off in Secrets to go live.")
    org_default = gs_get_setting("ORG_NAME", "")
    org_name = st.text_input("Organization / League Name (shown on kiosk)", value=org_default)
    if st.button("Save Settings"):
        gs_set_setting("ORG_NAME", org_name)
        st.success("Settings saved.")
    if LOGO_URL:
        st.image(LOGO_URL, caption="Logo (from LOGO_URL secret)", width=220)
    else:
        st.caption("Add a logo by setting a LOGO_URL secret with a direct link to an image.")

    with st.expander("Connection Test", expanded=False):
        if DEMO_MODE:
            st.info("DEMO_MODE is on; skipping live tests.")
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
    if LOGO_URL:
        st.image(LOGO_URL, width=220)
    org_name = gs_get_setting("ORG_NAME", "")
    title_suffix = f" — {org_name}" if org_name else ""
    st.title(f"✅ {BRAND_NAME} — Photo Day Check‑In{title_suffix}")
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
            pkg = st.selectbox("Photo Package (optional)", ["Not selected","Basic","Deluxe","Team+Individual"]) 
            notes = st.text_area("Notes (pose requests, etc.)")
            release = st.checkbox("I agree to the photo release/policy")
            
        st.markdown("**Photo (required)** — choose one:")
        cam = st.camera_input("Take photo with camera (preferred)")
        up = st.file_uploader("Or upload an image file", type=["jpg","jpeg","png","heic","webp"])  # some browsers provide jpeg/png only

        submitted = st.form_submit_button("Complete Check‑In", type="primary")

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
            # infer ext from type/name
            if up.name.lower().endswith((".jpg",".jpeg")): ext = ".jpg"
            elif up.name.lower().endswith(".png"): ext = ".png"
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

# ----------------------------- Optional quick tests ---------------------------
# Enable by setting RUN_TESTS = "1" in Secrets. These never run in production by default.
def _run_smoke_tests():
    # f-string CSS should have doubled braces
    assert "{{" in BRAND_CSS and "}}" in BRAND_CSS

    # slugify + id helpers
    assert slugify("A B-C!") == "abc"
    pid = gen_player_id("A", "B", "Team")
    assert len(pid) == 10
    sc = short_code(pid)
    assert len(sc) == 6

    # 1) Mapping/table with JSON-style private_key (
escapes
m = {
        "type": "service_account",
        "project_id": "p",
        "private_key_id": "k",
        "private_key": "-----BEGIN PRIVATE KEY-----,-----END PRIVATE KEY-----",
        "client_email": "a@p.iam.gserviceaccount.com",
        "client_id": "1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
assert parse_service_account(m)["client_email"].endswith("iam.gserviceaccount.com")

    # 2) JSON string (double-escaped 
to be valid JSON inside a Python string)
    j = (
        "{\"type\":\"service_account\",\"project_id\":\"p\",\"private_key_id\":\"k\"," 
        "\"private_key\":\"-----BEGIN PRIVATE KEY-----\nX\n-----END PRIVATE KEY-----\n\"," 
        "\"client_email\":\"a@p.iam.gserviceaccount.com\",\"client_id\":\"1\","
        "\"token_uri\":\"https://oauth2.googleapis.com/token\"}"
    )
assert parse_service_account(j)["project_id"] == "p"

    # 3) Code-fenced JSON (as users often paste)
    jf = (
        "```json
"
        "{\"type\":\"service_account\",\"project_id\":\"p\",\"private_key_id\":\"k\"," 
        "\"private_key\":\"-----BEGIN PRIVATE KEY-----\nX\n-----END PRIVATE KEY-----\n\","
        "\"client_email\":\"a@p.iam.gserviceaccount.com\",\"client_id\":\"1\","
        "\"token_uri\":\"https://oauth2.googleapis.com/token\"}
"
        "```"
    )
    assert parse_service_account(jf)["client_id"] == "1"

    # 4) Empty / invalid should raise
    try:
        parse_service_account("")
        assert False, "Expected ValueError for empty secret"
    except ValueError:
        pass

if str(st.secrets.get("RUN_TESTS","")) in {"1","true","yes","True","YES"}:
    _run_smoke_tests()

if __name__ == "__main__":
    main()
