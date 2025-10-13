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

try:
    from core import HAS_CV2
except Exception:
    HAS_CV2 = False

def render_admin(event):
    st.title("Area Admin")
    tab_plenaria, tab_rosters, tab_add_company, tab_roundtables = st.tabs([
        "Plenary", "Companies", "Add company", "Round Tables Bookings"
    ])

    # -----------------------------
    # Plenary Attendance + Download
    # -----------------------------
    with tab_plenaria:
        st.subheader("Plenary Attendance")
        with engine.begin() as conn:
            rows = list(conn.execute(
                text("SELECT id, name, matricola, plenary_attendance FROM student ORDER BY name COLLATE NOCASE")
            ).mappings())

        if not rows:
            st.info("Nessuno studente registrato.")
        else:
            st.write("**Studente – Matricola – Presenza**")

            # Form per aggiornare tutte le presenze
            with st.form("plenary_form"):
                presence_dict = {}
                for r in rows:
                    presence_dict[r["id"]] = st.checkbox(
                        r["name"],
                        value=bool(r["plenary_attendance"]),
                        key=f"plenary_{r['id']}"
                    )

                submitted = st.form_submit_button("Salva presenze")
                if submitted:
                    with engine.begin() as conn:
                        for student_id, present in presence_dict.items():
                            conn.execute(
                                text("UPDATE student SET plenary_attendance = :p WHERE id = :id"),
                                {"p": int(present), "id": student_id}
                            )
                    st.success("Presenze aggiornate ✅")

        # Download CSV
        df_plenary = pd.DataFrame(rows)
        st.download_button(
            label="📥 Esporta presenze plenary",
            data=df_plenary.to_csv(index=False),
            file_name="presenze_plenary.csv",
            mime="text/csv"
        )

    # -----------------------------
    # Rosters / Colloqui + Download
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

        df_show_all = []
        for c in companies:
            st.markdown(f"### 🏢 {c['name']}")
            with engine.begin() as conn:
                rows = get_bookings_with_logs(conn, event["id"], c["id"])

            if search_student:
                rows = [r for r in rows if search_student in (r["student"] or "").lower()]

            df = pd.DataFrame(rows)
            if not df.empty:
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
                df_show_all.append(df_show)

        # Download CSV Rosters
        if df_show_all:
            df_rosters_csv = pd.concat(df_show_all)
            st.download_button(
                label="📥 Esporta prenotazioni aziende",
                data=df_rosters_csv.to_csv(index=False),
                file_name="prenotazioni_aziende.csv",
                mime="text/csv"
            )

    # -----------------------------
    # Add Company
    # -----------------------------
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

    # -----------------------------
    # Round Tables + Download
    # -----------------------------
    with tab_roundtables:
        st.subheader("Round Tables")
        student_name_input = st.text_input("Nome studente da prenotare", key="rt_student_name")

        if "rt_update" not in st.session_state:
            st.session_state.rt_update = 0

        with engine.begin() as conn:
            rts = get_roundtables(conn, event["id"])
            all_bookings = []
            if rts:
                for rt in rts:
                    capacity = ROUND_TABLE_CAPACITY.get(rt["id"], None)
                    bookings = list(conn.execute(
                        text("""
                            SELECT id, student, created_at, COALESCE(attended, 0) AS attended
                            FROM roundtable_booking
                            WHERE roundtable_id = :rt_id
                            ORDER BY created_at
                        """), {"rt_id": rt["id"]}
                    ).mappings())
                    # Converti ogni RowMapping in dict per poter aggiungere campi
                    bookings = [dict(b, roundtable=rt["name"]) for b in bookings]
                    for b in bookings:
                        b["roundtable"] = rt["name"]
                    all_bookings.extend(bookings)

                    if bookings:
                        st.write(f"### {rt['name']} – {rt['room']}")
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
                                if present != bool(b["attended"]):
                                    conn.execute(
                                        text("UPDATE roundtable_booking SET attended = :a WHERE id = :id"),
                                        {"a": int(present), "id": b["id"]}
                                    )
                            with cols[2]:
                                if st.button("🗑️ Rimuovi", key=f"rm_{rt['id']}_{b['id']}"):
                                    conn.execute(
                                        text("DELETE FROM roundtable_booking WHERE id = :id"),
                                        {"id": b["id"]}
                                    )
                                    st.session_state.rt_update += 1
                                    st.rerun()

                # Download CSV Round Tables
                if all_bookings:
                    df_rts = pd.DataFrame(all_bookings)
                    st.download_button(
                        label="📥 Esporta prenotazioni Round Tables",
                        data=df_rts.to_csv(index=False),
                        file_name="prenotazioni_roundtables.csv",
                        mime="text/csv"
                    )
