# page_admin.py
import streamlit as st
import pandas as pd
from sqlalchemy import text
from core import (
    engine,
    get_active_event,
    get_companies,
    get_bookings_with_logs,
    get_roundtables,
    generate_slots,
)

ROUND_TABLE_CAPACITY = {1:140, 2:140, 3:73, 4:130, 5:113, 6:68}

def render_admin(event):
    st.title("Area Admin")
    tab_plenaria, tab_rosters, tab_roundtables = st.tabs([
        "Plenaria", "Aziende", "Tavole Rotonde"
    ])

    # -----------------------------
    # Plenary Attendance
    # -----------------------------
    with tab_plenaria:
        st.subheader("Presenza Plenaria (conferma effettiva lato Admin)")
        
        with engine.begin() as conn:
            # Recupera gli studenti con eventuale stato di conferma
            students = list(conn.execute(
                text("""
                    SELECT id, givenName, sn, email, matricola, plenary_confirmed
                    FROM student
                    ORDER BY sn COLLATE NOCASE, givenName COLLATE NOCASE
                """)
            ).mappings())

        if students:
            st.write("**Studente – Matricola – Presenza effettiva alla plenaria**")
            
            with st.form("plenary_form"):
                presence_dict = {}
                for s in students:
                    label = f"{s['givenName']} {s['sn']} ({s['matricola'] or '—'})"
                    
                    # Qui leggo dal DB, se nulla o 0 -> checkbox non selezionata
                    presence_dict[s["id"]] = st.checkbox(
                        label,
                        value=bool(s.get("plenary_confirmed", 0)),
                        key=f"plenary_{s['id']}"
                    )
                
                submitted = st.form_submit_button("💾 Salva presenze")
                
                if submitted:
                    with engine.begin() as conn:
                        for sid, present in presence_dict.items():
                            conn.execute(
                                text("UPDATE student SET plenary_confirmed=:p WHERE id=:id"),
                                {"p": int(present), "id": sid}
                            )
                    st.success("✅ Presenze aggiornate (solo studenti selezionati).")

            # Esportazione CSV delle presenze confermate
            df_csv = pd.DataFrame(students)
            df_csv["Plenary Attendance"] = df_csv.get("plenary_confirmed", 0)
            df_csv = df_csv[["givenName", "sn", "matricola", "email", "Plenary Attendance"]]
            st.download_button(
                "📥 Esporta presenze plenaria",
                data=df_csv.to_csv(index=False),
                file_name="presenze_plenary.csv",
                mime="text/csv"
            )

    # -----------------------------
    # Colloqui / Booking
    # -----------------------------
    with tab_rosters:
        st.subheader("📋 Company Bookings Management")

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

        with engine.begin() as conn:
            companies = all_companies if selected_company == "Tutte" else [
                c for c in all_companies if c["name"] == selected_company
            ]

            # Recupero tutte le informazioni degli studenti
            students_info = conn.execute(
                text("SELECT email, givenName, sn, matricola FROM student")
            ).mappings()
            students_map = {s["email"].lower(): s for s in students_info}

        df_show_all = []

        for c in companies:
            st.markdown(f"### 🏢 {c['name']}")
            with engine.begin() as conn:
                bookings = get_bookings_with_logs(conn, event["id"], c["id"])

            if search_student:
                bookings = [
                    b for b in bookings
                    if search_student in (b["student"] or "").lower()
                ]

            # Prepara lista ordinata per il DataFrame
            df_rows = []
            for b in bookings:
                # estrai email dal campo student, che può essere "Nome Cognome <email>"
                import re
                match = re.search(r"<(.+)>", b["student"] or "")
                email = match.group(1).lower() if match else (b["student"] or "").lower()
                student_data = students_map.get(email, {})
                df_rows.append({
                    "Azienda": c["name"],
                    "Nome": student_data.get("givenName", ""),
                    "Cognome": student_data.get("sn", ""),
                    "Matricola": student_data.get("matricola", ""),
                    "Email": email,
                    "Orario": b.get("slot", ""),
                    "CV / Link": b.get("cv", ""),
                    "Stato": b.get("status", ""),
                    "Inizio": b.get("start_time", ""),
                    "Fine": b.get("end_time", "")
                })

            if df_rows:
                st.markdown(f"#### Prenotazioni per {c['name']}")
                for b in sorted(df_rows, key=lambda x: x["Orario"]):
                    cols = st.columns([4, 3, 2, 1])
                    with cols[0]:
                        st.write(f"👤 {b['Nome']} {b['Cognome']} ({b['Matricola'] or '—'})")
                    with cols[1]:
                        st.write(f"📧 {b['Email']}")
                    with cols[2]:
                        st.write(f"🕒 {b['Orario']}")
                    with cols[3]:
                        if st.button("❌ Cancella", key=f"del_{c['id']}_{b['Email']}_{b['Orario']}"):
                            try:
                                with engine.begin() as conn:
                                    conn.execute(
                                        text("""
                                            DELETE FROM booking 
                                            WHERE event_id = :e 
                                            AND company_id = :c 
                                            AND slot = :slot
                                            AND LOWER(student) LIKE :email_pattern
                                        """),
                                        {
                                            "e": event["id"],
                                            "c": c["id"],
                                            "slot": b["Orario"],
                                            "email_pattern": f"%{b['Email'].lower()}%",
                                        },
                                    )
                                st.success(f"🗑️ Prenotazione rimossa per {b['Email']} alle {b['Orario']}")
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Errore durante la cancellazione: {ex}")

                # Per esportazione CSV
                df_show = pd.DataFrame(df_rows).sort_values("Orario")
                df_show_all.append(df_show)

            # --- Form per aggiungere prenotazioni manuali ---
            with st.expander(f"➕ Aggiungi prenotazione per {c['name']}"):
                with st.form(f"add_booking_{c['id']}"):
                    colA, colB = st.columns(2)
                    with colA:
                        student_name = st.text_input("Nome studente", key=f"name_{c['id']}")
                    with colB:
                        student_email = st.text_input("Email studente", key=f"email_{c['id']}")

                    # Genera lista slot disponibili
                    available_slots = generate_slots()
                    booked_slots = {r["slot"] for r in bookings}
                    free_slots = [s for s in available_slots if s not in booked_slots]

                    slot_choice = st.selectbox(
                        "Seleziona uno slot disponibile",
                        free_slots,
                        key=f"slot_{c['id']}"
                    )

                    cv_link = st.text_input("Link CV (opzionale)", key=f"cv_{c['id']}")

                    submitted = st.form_submit_button("Aggiungi prenotazione")
                    if submitted:
                        if not (student_name and student_email and slot_choice):
                            st.warning("⚠️ Compila tutti i campi obbligatori (nome, email, slot).")
                        else:
                            student_identifier = f"{student_name} <{student_email}>"
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
                                st.error(f"Errore durante l'inserimento: {ex}")

        # Download CSV Rosters
        if df_show_all:
            df_rosters_csv = pd.concat(df_show_all, ignore_index=True)
            st.download_button(
                label="📥 Esporta prenotazioni aziende",
                data=df_rosters_csv.to_csv(index=False),
                file_name="prenotazioni_aziende.csv",
                mime="text/csv"
            )

    # -----------------------------
    # Round Tables
    # -----------------------------
    with tab_roundtables:
        st.subheader("Tavole Rotonde")
        if "rt_update" not in st.session_state:
            st.session_state.rt_update = 0

        df_all = []
        with engine.begin() as conn:
            rts = get_roundtables(conn, event["id"])
            for rt in rts:
                bookings = list(conn.execute(
                    text("""
                        SELECT s.givenName, s.sn, s.matricola, s.email,
                               r.attended
                        FROM roundtable_booking r
                        JOIN student s ON s.email = r.student
                        WHERE r.roundtable_id=:rt_id
                        ORDER BY r.created_at
                    """), {"rt_id": rt["id"]}
                ).mappings())

                if bookings:
                    st.write(f"### {rt['name']} – {rt['room']}")
                    for b in bookings:
                        cols = st.columns([5, 2])
                        with cols[0]:
                            st.write(f"👤 {b['givenName']} {b['sn']} ({b['matricola'] or '—'})")
                        with cols[1]:
                            present = st.checkbox(
                                "Presente",
                                value=bool(b["attended"]),
                                key=f"attend_{rt['id']}_{b['email']}"
                            )
                            if present != bool(b["attended"]):
                                conn.execute(
                                    text("UPDATE roundtable_booking SET attended=:a WHERE student=:email AND roundtable_id=:rt_id"),
                                    {"a": int(present), "email": b["email"], "rt_id": rt["id"]}
                                )
                    for b in bookings:
                        row = dict(b)  # ✅ converte RowMapping in dict
                        row["RoundTable"] = rt["name"]
                        row["Room"] = rt["room"]
                        df_all.append(row)

        if df_all:
            df_csv = pd.DataFrame(df_all)
            df_csv = df_csv.rename(columns={"attended": "Round Table Attendance"})
            df_csv = df_csv[["RoundTable", "Room", "givenName", "sn", "matricola", "email", "Round Table Attendance"]]
            st.download_button(
                "📥 Esporta presenze Round Tables",
                data=df_csv.to_csv(index=False),
                file_name="presenze_roundtables.csv",
                mime="text/csv"
            )

