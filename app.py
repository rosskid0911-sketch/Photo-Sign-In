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
                fid, link = drive_upload_photo(
                    "healthcheck_" + now + ".txt", dummy_bytes, mimetype="text/plain"
                )
                st.success(
                    "Sheets OK (HEALTHCHECK=" + str(ping) + ") · Drive OK (file id " + str(fid) + ")"
                )
            except Exception as e:
                st.error("Connection test failed. Verify Secrets, sharing on Sheet & Folder, and enabled APIs.")
                st.exception(e)
