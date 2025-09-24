# page_admin.py
import streamlit as st
import pandas as pd
from sqlalchemy import text

from core import (
    engine,
    get_active_event,
    get_companies,
    get_bookings_with_logs,
    append_attendance_csv,
    decode_qr_from_image_bytes,
    parse_name_from_qr_text,
)

# cv2 availability flag lives in core; re-evaluate here
try:
    from core import HAS_CV2
except Exception:
    HAS_CV2 = False

def render_admin(event):
    """Render the Admin area (unchanged behavior)."""
    st.title("Area Admin")

    tab_rosters, tab_add_company, tab_qr = st.tabs(["Rosters", "Aggiungi azienda", "Scanner QR (presenze)"])

    # Rosters
    with tab_rosters:
        st.subheader("Rosters (tutte le aziende)")
        with engine.begin() as conn:
            companies = get_companies(conn, event["id"])
            for c in companies:
                st.markdown(f"### {c['name']}")
                rows = get_bookings_with_logs(conn, event["id"], c["id"])
                df = pd.DataFrame(rows)
                if df.empty:
                    st.info("Nessuna prenotazione")
                else:
                    df_show = df.sort_values("slot")[
                        ["slot", "student", "cv", "status", "start_time", "end_time"]
                    ].rename(columns={
                        "slot": "Orario",
                        "student": "Studente",
                        "cv": "CV",
                        "status": "Stato",
                        "start_time": "Inizio",
                        "end_time": "Fine",
                    })
                    st.dataframe(df_show, use_container_width=True)

    # Add company
    with tab_add_company:
        st.subheader("Aggiungi nuova azienda")
        new_name = st.text_input("Nome azienda", key="new_company_name")
        if st.button("Aggiungi"):
            name = (new_name or "").strip()
            if not name:
                st.error("Nome azienda vuoto")
            else:
                try:
                    with engine.begin() as conn:
                        conn.execute(text("INSERT INTO company (name) VALUES (:n)"), {"n": name})
                        ev = event or get_active_event(conn)
                        if ev:
                            conn.execute(
                                text("""INSERT OR IGNORE INTO event_company (event_id, company_id)
                                        SELECT :e, id FROM company WHERE name=:n"""),
                                {"e": ev["id"], "n": name}
                            )
                    st.success("Azienda aggiunta")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Errore: {ex}")

    # QR scanner
    with tab_qr:
        st.subheader("Scanner QR (presenze studenti)")
        if not HAS_CV2:
            st.error("OpenCV non è installato. Aggiungi 'opencv-python' al requirements.txt e riprova.")
            return

        st.caption("Scansiona il QR dall'app dell'università (o carica un'immagine).")
        cam_img = st.camera_input("Apri la fotocamera per scannerizzare il QR")
        up_img = st.file_uploader("Oppure carica un'immagine", type=["png", "jpg", "jpeg"])

        image_bytes = None
        if cam_img is not None:
            image_bytes = cam_img.getvalue()
        elif up_img is not None:
            image_bytes = up_img.read()

        if not image_bytes:
            return

        decoded_list = decode_qr_from_image_bytes(image_bytes)
        if not decoded_list:
            st.warning("Nessun QR rilevato nell'immagine.")
            return

        for idx, payload in enumerate(decoded_list, start=1):
            full_name, first_name, last_name = parse_name_from_qr_text(payload)
            st.success(f"QR #{idx} letto ✅")
            st.write(f"**Nome completo:** {full_name}")
            st.write(f"**Nome:** {first_name} — **Cognome:** {last_name}")
            if st.button(f"Registra presenza (QR #{idx})"):
                append_attendance_csv(event["id"], full_name, first_name, last_name, payload)
                st.success("Presenza registrata")
