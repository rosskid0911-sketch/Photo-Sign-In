"""
Sports League Photo Check‑In (Streamlit) — Google Sheets Cloud Version
---------------------------------------------------------------------
Host this so your kiosk can reach it from anywhere.
This version stores **Roster**, **Check‑Ins**, and simple **Settings** in **Google Sheets** so you can
review or share them easily. It includes brand styling for **Photograph BY TR, LLC**
and shows your studio emails for quick reference: photorgraphbytr@gmail.com, trossiter@photographybytr.com.

New fields added per your request:
- **SiblingLink** (free‑text, e.g., sibling short code(s) or names)
- **Paid** (toggle)
- **OrgName** (Organization name, saved in Settings and stamped on each check‑in)

Why this setup?
- 🔒 Manager tab protected by a PIN in `st.secrets`.
- 🌐 Kiosk mode via `?mode=kiosk` works on any device (tablet/phone/laptop).
- ☁️ Google Sheets backend (no local files) for simple sharing and edits.
- 🧠 Fuzzy search + 6‑char player codes to avoid handwriting misreads.
- 📦 CSV exports + optional QR code ZIP.
- 🖼️ Optional logo via `LOGO_URL` secret (PNG/SVG/JPG)

----------
QUICK DEPLOY (Streamlit Community Cloud)
----------
1) Create a Google Cloud service account with **Drive** and **Sheets API** enabled.
2) Download the service account JSON. In Streamlit **Advanced settings → Secrets**, add:

   GCP_SERVICE_ACCOUNT = "{"type":"service_account",...}"   # paste full JSON (one line)
   GSHEET_ID = "YOUR_SHEET_ID"   # the spreadsheet ID (create an empty Google Sheet)
   MANAGER_PIN = "9690"           # change this
   LOGO_URL = "https://.../your-logo.png"  # optional

3) In Google Sheets, name three tabs (worksheets): **Roster**, **Checkins**, **Settings** (exact spelling).
4) Share the spreadsheet with the service account email (find it in your JSON: ends with gserviceaccount.com) with **Editor** access.
5) Push this file to GitHub and deploy on Streamlit Community Cloud.
6) Open your app URL. For kiosk: `https://your-app.streamlit.app/?mode=kiosk`.

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

"""

from __future__ import annotations
import os
import io
import zipfile
import hashlib
import json
from datetime import datetime
from typing import Optional

import pandas as pd
from rapidfuzz import process, fuzz
import streamlit as st
from PIL import Image
import qrcode

# Google Sheets client
import gspread
from google.oauth2.service_account import Credentials

# ----------------------------- App Config ------------------------------------
st.set_page_config(page_title="Sports Photo Check‑In", page_icon="📸", layout="wide")

# Secrets (set in Streamlit Cloud)
GCP_SERVICE_ACCOUNT = st.secrets.get("GCP_SERVICE_ACCOUNT", None)
GSHEET_ID = st.secrets.get("GSHEET_ID", "")
MANAGER_PIN = st.secrets.get("MANAGER_PIN", "9690")  # change in secrets
LOGO_URL = st.secrets.get("LOGO_URL", "")

BRAND_NAME = "Photograph BY TR, LLC"
BRAND_PRIMARY = "#111827"   # near-black
BRAND_ACCENT = "#f59e0b"    # amber accent
BRAND_EMAILS = "photorgraphbytr@gmail.com; trossiter@photographybytr.com"

# ----------------------------- Utilities & Branding -------------------------

BRAND_CSS = f"""
<style>
:root {{
  --brand-primary: {BRAND_PRIMARY};
  --brand-accent: {BRAND_ACCENT};
}}
/* Headings */
h1,h2,h3,h4,h5,h6 {{ color: var(--brand-primary) !important; }}
.stButton>button {{ border-radius: 12px; }}
.block-container {{ padding-top: 0.4rem; }}
.brand-hero {{
  padding: 0.6rem 0.9rem; border-left: 6px solid var(--brand-accent);
  background: rgba(245,158,11,0.07); margin: 0.6rem 0 0.8rem 0;
}}
.badge {{ display:inline-block; padding:2px 8px; border-radius:999px; background:var(--brand-accent); color:white; font-size:0.8rem; margin-left:6px; }}
</style>
"""

# ----------------------------- Utilities ------------------------------------

def slugify(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isalnum()).lower()


def gen_player_id(row: pd.Series) -> str:
    base = f"{row.get('FirstName','')}-{row.get('LastName','')}-{row.get('Team','')}".strip()
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    return h


def short_code(player_id: str) -> str:
    return hashlib.sha1(player_id.encode("utf-8")).hexdigest()[:6].upper()


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "firstname": "FirstName","first_name": "FirstName","fname": "FirstName",
        "lastname": "LastName","last_name": "LastName","lname": "LastName",
        "teamname": "Team",
        "parent_email": "ParentEmail","email": "ParentEmail",
        "parent_phone": "ParentPhone","phone": "ParentPhone",
        "jersey#": "Jersey","jersey": "Jersey",
        "playerid": "PlayerID","id": "PlayerID",
    }
    cols = {c: rename_map.get(slugify(c), c) for c in df.columns}
    df = df.rename(columns=cols)
    for col in ["FirstName", "LastName", "Team", "ParentEmail", "ParentPhone", "Jersey"]:
        if col not in df.columns:
            df[col] = ""
    if "PlayerID" not in df.columns:
        df["PlayerID"] = df.apply(gen_player_id, axis=1)
    df["ShortCode"] = df["PlayerID"].apply(short_code)
    df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)
    return df


# ----------------------------- Google Sheets ---------------------------------
@st.cache_resource(show_spinner=False)
def get_gs():
    if not GCP_SERVICE_ACCOUNT or not GSHEET_ID:
        st.error("Missing GCP_SERVICE_ACCOUNT or GSHEET_ID in secrets.")
        st.stop()
    # Secrets may be dict already (Streamlit Cloud) or string; handle both safely
    creds_info = GCP_SERVICE_ACCOUNT if isinstance(GCP_SERVICE_ACCOUNT, dict) else json.loads(str(GCP_SERVICE_ACCOUNT))
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GSHEET_ID)
    # Ensure worksheets
    for ws_name, cols in [
        ("Roster", ["PlayerID","ShortCode","FirstName","LastName","Team","ParentEmail","ParentPhone","Jersey"]),
        ("Checkins", [
            "ts","player_id","short_code","first_name","last_name","team","parent_email","parent_phone",
            "confirmed_email","confirmed_phone","jersey","confirmed_jersey","package","notes","release_accepted",
            "checked_in_by","sibling_link","paid","org_name","brand","brand_emails"
        ]),
        ("Settings", ["key","value"]),
    ]:
        try:
            ws = sh.worksheet(ws_name)
            # If the sheet is empty, write headers once
            if ws.row_count == 0 or not ws.get_values('A1:A1'):
                ws.update([cols])
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=ws_name, rows=1000, cols=max(20, len(cols)))
            ws.update([cols])
    return sh

@st.cache_data(ttl=20, show_spinner=False)
def gs_read_df(sheet_name: str) -> pd.DataFrame:
    sh = get_gs()
    ws = sh.worksheet(sheet_name)
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame()
    header, rows = values[0], values[1:]
    df = pd.DataFrame(rows, columns=header)
    # Coerce blank to proper empty
    df = df.replace({"": pd.NA})
    return df

def gs_write_df(sheet_name: str, df: pd.DataFrame):
    sh = get_gs()
    ws = sh.worksheet(sheet_name)
    # Normalize NaNs to blanks for Sheets
    df2 = df.copy()
    df2 = df2.where(pd.notnull(df2), "")
    data = [list(df2.columns)] + df2.astype(str).values.tolist()
    ws.clear()
    ws.update(data)

# Settings as simple key/value
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


def sb_load_roster() -> pd.DataFrame:
    df = gs_read_df("Roster")
    if df.empty:
        return df
    df = normalize_columns(df)
    return df


def sb_upsert_roster(df: pd.DataFrame):
    # Replace entire sheet with current roster for simplicity
    df = normalize_columns(df)
    gs_write_df("Roster", df[["PlayerID","ShortCode","FirstName","LastName","Team","ParentEmail","ParentPhone","Jersey"]])


def sb_insert_checkin(row: dict):
    existing = gs_read_df("Checkins")
    if existing.empty:
        new_df = pd.DataFrame([row])
    else:
        # Align columns
        for col in [c for c in row.keys() if c not in existing.columns]:
            existing[col] = pd.NA
        new_df = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    gs_write_df("Checkins", new_df)


def sb_load_checkins() -> pd.DataFrame:
    df = gs_read_df("Checkins")
    if df.empty:
        return df
    # Ensure expected column display names
    rename = {
        "ts":"TS","player_id":"PlayerID","short_code":"ShortCode",
        "first_name":"FirstName","last_name":"LastName","team":"Team",
        "parent_email":"ParentEmail","parent_phone":"ParentPhone",
        "confirmed_email":"ConfirmedEmail","confirmed_phone":"ConfirmedPhone",
        "jersey":"Jersey","confirmed_jersey":"ConfirmedJersey",
        "package":"Package","notes":"Notes","release_accepted":"ReleaseAccepted",
        "checked_in_by":"CheckedInBy","sibling_link":"SiblingLink","paid":"Paid","org_name":"OrgName",
        "brand":"Brand","brand_emails":"BrandEmails"
    }
    for k,v in rename.items():
        if k in df.columns and v not in df.columns:
            df = df.rename(columns={k:v})
    return df

# ----------------------------- Fuzzy Search ----------------------------------

def search_candidates(df: pd.DataFrame, query: str, team_filter: str = "") -> pd.DataFrame:
    if df.empty:
        return df
    if not query and not team_filter:
        return df.head(50)
    pool = df
    if team_filter:
        pool = pool[pool["Team"].astype(str).str.contains(team_filter, case=False, na=False)]
    names = pool.apply(lambda r: f"{r['FirstName']} {r['LastName']} | {r['Team']} | {r['ShortCode']}", axis=1).tolist()
    results = process.extract(query, names, scorer=fuzz.WRatio, limit=20)
    idxs = [r[2] for r in results if r[1] >= 60]
    return pool.iloc[idxs] if len(idxs) else pool.head(20)


# ----------------------------- QR Codes --------------------------------------

def make_qr_image(payload: str, box_size: int = 10) -> Image.Image:
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=box_size, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img


def build_qr_zip(df: pd.DataFrame) -> bytes:
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for _, row in df.iterrows():
            pid = row["PlayerID"]
            code = row["ShortCode"]
            payload = f"PID:{pid}|SC:{code}|FN:{row['FirstName']}|LN:{row['LastName']}|TEAM:{row['Team']}"
            img = make_qr_image(payload)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            fname = f"{slugify(row['Team'])}_{slugify(row['LastName'])}_{slugify(row['FirstName'])}_{code}.png"
            zf.writestr(fname, buf.getvalue())
    mem.seek(0)
    return mem.read()


# ----------------------------- UI: Manager -----------------------------------

def roster_editor(df: pd.DataFrame):
    st.subheader("Roster")
    st.caption("Edit inline and click **Save to Google Sheets**. PlayerIDs/ShortCodes regenerate only for new rows.")
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        column_config={
            "PlayerID": st.column_config.TextColumn(disabled=True),
            "ShortCode": st.column_config.TextColumn(disabled=True),
        },
        use_container_width=True,
        height=420
    )
    if st.button("Save to Google Sheets", type="primary"):
        sb_upsert_roster(edited)
        st.success("Roster saved to Google Sheets.")

    st.download_button("Download current roster CSV", data=df.to_csv(index=False).encode("utf-8"), file_name="roster.csv")


def export_section(roster: pd.DataFrame, checkins: pd.DataFrame):
    st.subheader("Exports")
    st.write("**All Check‑Ins**")
    st.dataframe(checkins, use_container_width=True, height=300)
    st.download_button(
        "Download Check‑Ins CSV",
        data=checkins.to_csv(index=False).encode("utf-8"),
        file_name=f"checkins_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        type="primary"
    )

    teams = sorted([t for t in roster["Team"].dropna().unique() if str(t).strip()]) if not roster.empty else []
    if teams:
        st.write("**Per‑Team CSV**")
        team = st.selectbox("Choose team", teams)
        team_df = checkins[checkins["Team"].astype(str).str.lower() == str(team).lower()]
        st.dataframe(team_df, use_container_width=True, height=240)
        st.download_button(
            f"Download {team} Check‑Ins",
            data=team_df.to_csv(index=False).encode("utf-8"),
            file_name=f"checkins_{slugify(team)}.csv"
        )

    st.write("**QR Codes** (optional)")
    if st.button("Generate QR ZIP"):
        zbytes = build_qr_zip(roster)
        st.download_button("Download QR_CODE_IMAGES.zip", data=zbytes, file_name="QR_CODE_IMAGES.zip")


def settings_section():
    st.subheader("Event / Organization Settings")
    org_default = gs_get_setting("ORG_NAME", "")
    org_name = st.text_input("Organization / League Name (shown on kiosk)", value=org_default)
    if st.button("Save Settings"):
        gs_set_setting("ORG_NAME", org_name)
        st.success("Settings saved.")
    if LOGO_URL:
        st.image(LOGO_URL, caption="Logo (from LOGO_URL secret)", width=240)
    else:
        st.caption("Add a logo by setting a LOGO_URL secret with a direct link to a PNG/JPG/SVG.")


def page_manager():
    st.markdown(BRAND_CSS, unsafe_allow_html=True)
    st.title(f"📸 {BRAND_NAME} — Sports Photo Check‑In (Manager)")
    st.caption("Google Sheets‑backed. Upload or edit your roster, then open **Kiosk** on any device with the link.")
    st.markdown(f"<div class='brand-hero'><strong>Delivery CC:</strong> {BRAND_EMAILS} <span class='badge'>BRAND</span></div>", unsafe_allow_html=True)

    # Simple PIN gate
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

    # Settings
    with st.expander("Settings", expanded=True):
        settings_section()

    st.subheader("Upload Roster CSV")
    up = st.file_uploader("CSV with headers: FirstName, LastName, Team, ParentEmail, ParentPhone, Jersey (optional)", type=["csv"])
    if up is not None:
        try:
            df = pd.read_csv(up)
            df = normalize_columns(df)
            sb_upsert_roster(df)
            st.success(f"Uploaded {len(df)} players to Google Sheets.")
        except Exception as e:
            st.error(f"Failed to read CSV: {e}")

    roster = sb_load_roster()
    if roster is None or roster.empty:
        st.info("No roster found yet. Upload a CSV to begin. A tiny sample is shown below.")
        sample = pd.DataFrame([
            {"FirstName":"Alex","LastName":"Lopez","Team":"U10 Red","ParentEmail":"alex.parent@example.com","ParentPhone":"405-555-0101","Jersey":9},
            {"FirstName":"Bri","LastName":"Nguyen","Team":"U10 Red","ParentEmail":"bri.parent@example.com","ParentPhone":"405-555-0111","Jersey":12},
            {"FirstName":"Chris","LastName":"Patel","Team":"U8 Blue","ParentEmail":"c.parent@example.com","ParentPhone":"405-555-0123","Jersey":7},
        ])
        st.dataframe(sample, use_container_width=True)
        return

    with st.expander("Edit Roster", expanded=True):
        roster_editor(roster)

    with st.expander("Exports & QR Codes", expanded=False):
        export_section(roster, sb_load_checkins())

    st.info("Share the kiosk link: **?mode=kiosk**. Keep your manager PIN secret.")


# ----------------------------- UI: Kiosk -------------------------------------

def page_kiosk():
    st.markdown(BRAND_CSS, unsafe_allow_html=True)
    if LOGO_URL:
        st.image(LOGO_URL, width=220)
    org_name = gs_get_setting("ORG_NAME", "")
    title_suffix = f" — {org_name}" if org_name else ""
    st.title(f"✅ {BRAND_NAME} — Photo Day Check‑In{title_suffix}")
    st.caption("Please type your player's name to avoid handwriting errors. A volunteer will help if needed.")

    roster = sb_load_roster()
    if roster is None or roster.empty:
        st.error("No roster loaded yet. Please ask a volunteer to upload it on the Manager screen.")
        st.stop()

    with st.container(border=True):
        st.write("### Find Your Player")
        q = st.text_input("Type first or last name (typos OK)")
        team_filter = st.text_input("Team (optional)")
        matches = search_candidates(roster, q, team_filter)
        st.write(f"Showing {len(matches)} possible match(es)")
        st.dataframe(matches[["FirstName","LastName","Team","ShortCode","Jersey"]], use_container_width=True, height=200)

        if matches.empty:
            st.stop()
        idx = st.selectbox(
            "Select player",
            options=list(matches.index),
            format_func=lambda i: f"{matches.at[i,'FirstName']} {matches.at[i,'LastName']} — {matches.at[i,'Team']} (Code {matches.at[i,'ShortCode']})"
        )

    sel = matches.loc[idx]
    st.write("---")
    st.write(f"### Confirm Details for {sel['FirstName']} {sel['LastName']} — {sel['Team']}")

    col1, col2 = st.columns(2)
    with col1:
        st.write("**On File**")
        st.text(f"Parent Email: {sel['ParentEmail']}")
        st.text(f"Parent Phone: {sel['ParentPhone']}")
        st.text(f"Jersey #: {sel['Jersey']}")
        with st.popover("Show My QR (optional)"):
            payload = f"PID:{sel['PlayerID']}|SC:{sel['ShortCode']}|FN:{sel['FirstName']}|LN:{sel['LastName']}|TEAM:{sel['Team']}"
            img = make_qr_image(payload, box_size=6)
            st.image(img, caption=f"Code {sel['ShortCode']}")

    with col2:
        st.write("**Please Confirm / Update**")
        email = st.text_input("Parent Email (for final photo delivery)", value=str(sel["ParentEmail"]))
        phone = st.text_input("Parent Phone", value=str(sel["ParentPhone"]))
        jersey = st.text_input("Jersey #", value=str(sel["Jersey"]))
        pkg = st.selectbox("Photo Package (optional)", ["Not selected","Basic","Deluxe","Team+Individual"]) 
        notes = st.text_area("Notes (pose requests, siblings, etc.)")
        release = st.checkbox("I agree to the photo release/policy")
        staff = st.text_input("Checked in by (staff initials)")
        sibling = st.text_input("SiblingLink (enter sibling short code(s) or names)")
        paid = st.toggle("Paid (prepay or on‑site)", value=False)

        if st.button("Complete Check‑In", type="primary", use_container_width=True):
            new_row = {
                "ts": datetime.utcnow().isoformat(),
                "player_id": sel["PlayerID"],
                "short_code": sel["ShortCode"],
                "first_name": sel["FirstName"],
                "last_name": sel["LastName"],
                "team": sel["Team"],
                "parent_email": sel["ParentEmail"],
                "parent_phone": sel["ParentPhone"],
                "confirmed_email": email,
                "confirmed_phone": phone,
                "jersey": str(sel["Jersey"]),
                "confirmed_jersey": str(jersey),
                "package": pkg,
                "notes": notes,
                "release_accepted": bool(release),
                "checked_in_by": staff,
                "sibling_link": sibling,
                "paid": str(bool(paid)),
                "org_name": org_name,
                "brand": BRAND_NAME,
                "brand_emails": BRAND_EMAILS,
            }
            sb_insert_checkin(new_row)
            st.success("Checked in! Thank you.")

    st.write("---")
    st.info("Tip: If you have your 6‑char code, type it in the name box to jump straight to your record.")

    with st.expander("I have a 6‑character code"):
        code = st.text_input("Enter code (letters/numbers)").strip().upper()
        if code:
            hit = roster[roster["ShortCode"] == code]
            if hit.empty:
                st.warning("Code not found.")
            else:
                h = hit.iloc[0]
                st.success(f"Found: {h['FirstName']} {h['LastName']} — {h['Team']}")


# ----------------------------- Router ----------------------------------------

def main():
    params = st.query_params
    mode = params.get("mode", [""])
    mode = mode[0] if isinstance(mode, list) else mode

    if mode == "kiosk":
        page_kiosk()
        return

    tab1, tab2 = st.tabs(["Manager", "Kiosk (preview)"])
    with tab1:
        page_manager()
    with tab2:
        page_kiosk()


if __name__ == "__main__":
    main()
