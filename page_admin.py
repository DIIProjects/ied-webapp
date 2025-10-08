# page_admin.py
import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import datetime
import traceback

from core import (
    engine,
    get_active_event,
    get_companies,
    get_bookings_with_logs,
    append_attendance_csv,
    decode_qr_from_image_bytes,
    parse_name_from_qr_text,
    get_roundtables,
    generate_slots,
)

ROUND_TABLE_CAPACITY = {
    1: 140,
    2: 140,
    3: 73,
    4: 130,
    5: 113,
    6: 68
}

# cv2 availability flag lives in core; re-evaluate here
try:
    from core import HAS_CV2
except Exception:
    HAS_CV2 = False

def render_admin(event):
    """Render the Admin area (unchanged behavior)."""
    st.title("Area Admin")
    #st.write("DEBUG: render_admin called with event =", event)
    tab_plenaria, tab_rosters, tab_add_company, tab_roundtables = st.tabs(["Plenary",
        "Companies", "Add company", "Round Tables Bookings"
    ])

    with tab_plenaria:
        st.subheader("Plenary Attendance")

    # Rosters
    with tab_rosters:
        st.subheader("📋 Company Bookings Management")

        # --- FILTRI DI RICERCA ---
        with st.expander("🔎 Filtri di ricerca", expanded=True):
            with engine.begin() as conn:
                all_companies = get_companies(conn, event["id"])

            col1, col2 = st.columns([2, 2])
            with col1:
                selected_company = st.selectbox(
                    "Filtra per azienda",
                    ["Tutte"] + [c["name"] for c in all_companies],
                    key="filter_company"
                )

            with col2:
                search_student = st.text_input(
                    "Cerca per nome studente o email",
                    key="filter_student"
                ).strip().lower()

        # --- CICLO PRINCIPALE ---
        with engine.begin() as conn:
            companies = all_companies if selected_company == "Tutte" else [
                c for c in all_companies if c["name"] == selected_company
            ]

        for c in companies:
            st.markdown(f"### 🏢 {c['name']}")

            with engine.begin() as conn:
                rows = get_bookings_with_logs(conn, event["id"], c["id"])

            # --- Applica filtro studente ---
            if search_student:
                rows = [
                    r for r in rows
                    if search_student in (r["student"] or "").lower()
                ]

            df = pd.DataFrame(rows)

            # --- Mostra le prenotazioni ---
            if df.empty:
                st.info("Nessuna prenotazione trovata per i filtri selezionati.")
            else:
                df_show = df.sort_values("slot")[
                    ["slot", "student", "cv", "status", "start_time", "end_time"]
                ].rename(columns={
                    "slot": "Orario",
                    "student": "Studente",
                    "cv": "CV / Link",
                    "status": "Stato",
                    "start_time": "Inizio",
                    "end_time": "Fine",
                })
                st.dataframe(df_show, use_container_width=True, hide_index=True)

                # --- Pulsanti per cancellare prenotazioni ---
                for _, row in df.iterrows():
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.write(f"🕒 {row['slot']} — {row['student']}")
                    with col2:
                        if st.button("❌ Rimuovi", key=f"del_{c['id']}_{row['student']}_{row['slot']}"):
                            try:
                                with engine.begin() as conn:
                                    conn.execute(
                                        text("""
                                            DELETE FROM booking
                                            WHERE event_id = :e
                                            AND company_id = :c
                                            AND student = :s
                                            AND slot = :slot
                                        """),
                                        {
                                            "e": event["id"],
                                            "c": c["id"],
                                            "s": row["student"],
                                            "slot": row["slot"],
                                        }
                                    )
                                st.success(f"Prenotazione di {row['student']} alle {row['slot']} rimossa.")
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Errore nella cancellazione: {ex}")

            # --- Sezione per aggiungere prenotazione manuale ---
            with st.expander(f"➕ Aggiungi prenotazione per {c['name']}"):
                with st.form(f"add_form_{c['id']}"):
                    colA, colB, colC = st.columns(3)
                    with colA:
                        name = st.text_input("Nome", key=f"name_{c['id']}")
                    with colB:
                        surname = st.text_input("Cognome", key=f"surname_{c['id']}")
                    with colC:
                        email = st.text_input("Email", key=f"email_{c['id']}")

                    available_slots = generate_slots()
                    booked_slots = {r["slot"] for r in rows}
                    free_slots = [s for s in available_slots if s not in booked_slots]

                    slot_choice = st.selectbox(
                        "Seleziona uno slot disponibile",
                        free_slots,
                        key=f"slot_{c['id']}"
                    )

                    cv_link = st.text_input("Link CV (facoltativo)", key=f"cvlink_{c['id']}")

                    submitted = st.form_submit_button("Aggiungi prenotazione")

                    if submitted:
                        if not (name and surname and email):
                            st.warning("⚠️ Compila nome, cognome ed email.")
                        else:
                            student_identifier = f"{name} {surname} <{email}>"
                            try:
                                with engine.begin() as conn:
                                    conn.execute(
                                        text("""
                                            INSERT INTO booking (event_id, company_id, student, slot, cv, status)
                                            VALUES (:e, :c, :s, :slot, :cv, 'manual')
                                            ON CONFLICT(event_id, company_id, student, slot) DO NOTHING
                                        """),
                                        {
                                            "e": event["id"],
                                            "c": c["id"],
                                            "s": student_identifier,
                                            "slot": slot_choice,
                                            "cv": cv_link or None,
                                        }
                                    )
                                st.success(f"✅ Prenotazione aggiunta per {student_identifier} alle {slot_choice}")
                                st.rerun()
                            except Exception as ex:
                                #st.error(f"Errore durante l'inserimento: {ex}")
                                st.error("❌ Errore durante l'inserimento. Controlla i log sotto.")
                                st.code(traceback.format_exc())
                                print(traceback.format_exc())


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
                    
    """
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
    """
    # -----------------------------
    # Round Tables Bookings
    # -----------------------------
    with tab_roundtables:
        st.subheader("Round Tables")

        # Input per aggiungere studenti
        student_name_input = st.text_input("Nome studente da prenotare", key="rt_student_name")

        # Forza refresh
        if "rt_update" not in st.session_state:
            st.session_state.rt_update = 0

        with engine.begin() as conn:
            rts = get_roundtables(conn, event["id"])
            if not rts:
                st.info("Nessuna round table disponibile.")
            else:
                for rt in rts:
                    capacity = ROUND_TABLE_CAPACITY.get(rt["id"], None)

                    if capacity:
                        percentage = rt['booked'] / capacity if capacity else 0
                        bar_length = 20
                        filled_blocks = int(percentage * bar_length)
                        bar = "█" * filled_blocks + "░" * (bar_length - filled_blocks)
                        st.markdown(
                            f"### {rt['name']} – {rt['room']} ({rt['booked']} / {capacity} — {round(percentage*100, 1)}%)\n"
                            f"`{bar} {round(percentage*100)}%`"
                        )
                    else:
                        st.markdown(f"### {rt['name']} - {rt['room']} ({rt['booked']} prenotazioni)")

                    # Mostra le prenotazioni con la colonna 'attended'
                    q = text("""
                        SELECT id, student, created_at, COALESCE(attended, 0) AS attended
                        FROM roundtable_booking
                        WHERE roundtable_id = :rt_id
                        ORDER BY created_at
                    """)
                    bookings = list(conn.execute(q, {"rt_id": rt["id"]}).mappings())

                    if not bookings:
                        st.write("Nessuna prenotazione per questo tavolo.")
                    else:
                        st.write("**Partecipanti**")
                        for b in bookings:
                            cols = st.columns([4, 2, 2])
                            with cols[0]:
                                st.write(f"👤 {b['student']}")
                            with cols[1]:
                                present = st.checkbox(
                                    "Presente",
                                    value=bool(b["attended"]),
                                    key=f"attend_{rt['id']}_{b['id']}"
                                )
                                # Aggiorna DB al cambio della checkbox
                                if present != bool(b["attended"]):
                                    try:
                                        conn.execute(
                                            text("""
                                                UPDATE roundtable_booking
                                                SET attended = :a
                                                WHERE id = :id
                                            """),
                                            {"a": int(present), "id": b["id"]}
                                        )
                                        st.toast(f"Presenza di {b['student']} aggiornata ✅", icon="✅")
                                    except Exception as ex:
                                        st.error(f"Errore aggiornando presenza: {ex}")
                            with cols[2]:
                                if st.button("🗑️ Rimuovi", key=f"rm_{rt['id']}_{b['id']}"):
                                    try:
                                        conn.execute(
                                            text("DELETE FROM roundtable_booking WHERE id = :id"),
                                            {"id": b["id"]}
                                        )
                                        st.success(f"{b['student']} rimosso da {rt['name']}")
                                        st.session_state.rt_update += 1
                                        st.rerun()
                                    except Exception as ex:
                                        st.error(f"Errore: {ex}")

                    # Pulsante per aggiungere prenotazioni
                    if student_name_input:
                        if st.button(f"Aggiungi {student_name_input} a {rt['name']}", key=f"add_{rt['id']}"):
                            try:
                                conn.execute(
                                    text("""
                                        INSERT INTO roundtable_booking (event_id, roundtable_id, student, created_at, attended)
                                        VALUES (:e, :rt, :s, :t, 0)
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
                                st.session_state.rt_update += 1
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Errore: {ex}")
