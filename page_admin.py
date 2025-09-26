# page_admin.py
import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import datetime

from core import (
    engine,
    get_active_event,
    get_companies,
    get_bookings_with_logs,
    append_attendance_csv,
    decode_qr_from_image_bytes,
    parse_name_from_qr_text,
    get_roundtables,
)

# cv2 availability flag lives in core; re-evaluate here
try:
    from core import HAS_CV2
except Exception:
    HAS_CV2 = False

def render_admin(event):
    """Render the Admin area (unchanged behavior)."""
    st.title("Area Admin")
    #st.write("DEBUG: render_admin called with event =", event)
    tab_rosters, tab_add_company, tab_qr, tab_roundtables = st.tabs([
        "Companies", "Add company", "QR Scanner", "Round Tables Bookings"
    ])

    # Rosters
    with tab_rosters:
        st.subheader("Company List")
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
        st.subheader("Add a new company")
        new_name = st.text_input("Company name", key="new_company_name")
        if st.button("Add"):
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
        st.subheader("Scanner QR (student attendance)")
        if not HAS_CV2:
            st.error("OpenCV non è installato. Aggiungi 'opencv-python' al requirements.txt e riprova.")
        else:
            st.caption("Scansiona il QR dall'app dell'università (o carica un'immagine).")
            cam_img = st.camera_input("Apri la fotocamera per scannerizzare il QR")
            up_img = st.file_uploader("Oppure carica un'immagine", type=["png", "jpg", "jpeg"])

            image_bytes = None
            if cam_img is not None:
                image_bytes = cam_img.getvalue()
            elif up_img is not None:
                image_bytes = up_img.read()

            if not image_bytes:
                st.info("Carica un’immagine o usa la fotocamera per registrare la presenza.")
            else:
                decoded_list = decode_qr_from_image_bytes(image_bytes)
                if not decoded_list:
                    st.warning("Nessun QR rilevato nell'immagine.")
                else:
                    for idx, payload in enumerate(decoded_list, start=1):
                        full_name, first_name, last_name = parse_name_from_qr_text(payload)
                        st.success(f"QR #{idx} letto ✅")
                        st.write(f"**Nome completo:** {full_name}")
                        st.write(f"**Nome:** {first_name} — **Cognome:** {last_name}")
                        if st.button(f"Registra presenza (QR #{idx})"):
                            append_attendance_csv(event["id"], full_name, first_name, last_name, payload)
                            st.success("Presenza registrata")

    # -----------------------------
    # Round Tables Bookings
    # -----------------------------
    with tab_roundtables:
        st.subheader("Round Tables")

        # Input per il nome dello studente
        student_name_input = st.text_input("Nome studente da prenotare", key="rt_student_name")

        # Chiave di sessione per forzare il refresh
        if "rt_update" not in st.session_state:
            st.session_state.rt_update = 0

        with engine.begin() as conn:
            rts = get_roundtables(conn, event["id"])
            if not rts:
                st.info("Nessuna round table disponibile.")
            else:
                for rt in rts:
                    st.markdown(f"### {rt['name']} - {rt['room']} ({rt['booked']} prenotazioni)")

                    # Mostra le prenotazioni attuali
                    q = text("""
                        SELECT student, created_at
                        FROM roundtable_booking
                        WHERE roundtable_id = :rt_id
                        ORDER BY created_at
                    """)
                    bookings = list(conn.execute(q, {"rt_id": rt["id"]}).mappings())

                    if not bookings:
                        st.write("Nessuna prenotazione per questo tavolo.")
                    else:
                        df = pd.DataFrame(bookings).rename(columns={
                            "student": "Studente",
                            "created_at": "Prenotato il"
                        })
                        st.dataframe(df, use_container_width=True)

                    # Pulsante per aggiungere prenotazione
                    if student_name_input:
                        if st.button(f"Aggiungi {student_name_input} a {rt['name']}", key=f"add_{rt['id']}"):
                            try:
                                conn.execute(
                                    text("""
                                        INSERT INTO roundtable_booking (event_id, roundtable_id, student, created_at)
                                        VALUES (:e, :rt, :s, :t)
                                        ON CONFLICT(event_id, roundtable_id, student) DO NOTHING
                                    """),
                                    {
                                        "e": event["id"],
                                        "rt": rt["id"],
                                        "s": student_name_input,
                                        "t": datetime.utcnow().isoformat()
                                    }
                                )
                                st.success(f"{student_name_input} aggiunto a {rt['name']}")
                                st.session_state.rt_update += 1  # forza refresh
                            except Exception as ex:
                                st.error(f"Errore: {ex}")

                    # Pulsante per rimuovere prenotazioni
                    if bookings:
                        for b in bookings:
                            if st.button(f"Rimuovi {b['student']}", key=f"rm_{rt['id']}_{b['student']}"):
                                try:
                                    conn.execute(
                                        text("DELETE FROM roundtable_booking WHERE roundtable_id=:rt AND student=:s"),
                                        {"rt": rt["id"], "s": b["student"]}
                                    )
                                    st.success(f"{b['student']} rimosso da {rt['name']}")
                                    st.session_state.rt_update += 1  # forza refresh
                                except Exception as ex:
                                    st.error(f"Errore: {ex}")
