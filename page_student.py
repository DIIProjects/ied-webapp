import streamlit as st
from datetime import datetime, timedelta
from sqlalchemy import text, Table, MetaData, update
from auth import find_student_user

from core import (
    engine,
    get_companies,
    generate_slots,
    get_bookings,
    get_student_bookings,
    save_cv_file,
    book_slot,
    get_unread_notifications,
    mark_notification_read,
    get_roundtables,
    get_student_roundtable_bookings,
    book_roundtable,
)
from auth import find_student_user

def student_first_access(email: str):
    """Flusso di primo accesso per lo studente."""
    
    email = email.lower().strip()
    
    # Recupera studente
    with engine.begin() as conn:
        student = find_student_user(email, conn=conn)

    if not student:
        st.error("Studente non trovato nel database. Contatta l'amministratore.")
        st.stop()

    st.title(f"Welcome, {student['givenName']} {student['sn']} 🎓")

    # --- Plenary session ---
    plenary_attend = st.checkbox(
        "☑️ I will attend the plenary session "
        "(attendance is mandatory for type F credit)",
        value=bool(student.get("plenary_attendance"))
    )

    # --- Privacy agreement ---
    st.markdown("""
    #### Privacy Notice
    Your personal data will be processed by the University of Trento in accordance with the Student Privacy Notice. 
    By continuing, you agree to the processing and sharing of your data with participating companies.
    """)
    agree_info = st.checkbox("☑️ I have read the Information on the processing of personal data.")
    agree_share = st.checkbox(
        "☑️ I agree to share my personal data with the participating companies."
    )

    if st.button("💾 Save and continue"):
        if not plenary_attend:
            st.error("⚠️ You must confirm attendance to the plenary session.")
        elif not agree_info or not agree_share:
            st.error("⚠️ You must accept both privacy statements to continue.")
        else:
            # --- Aggiorna database ---
            metadata = MetaData()
            student_table = Table('student', metadata, autoload_with=engine)
            
            stmt = (
                update(student_table)
                .where(student_table.c.email == email)
                .values(plenary_attendance=1)
            )
            
            with engine.begin() as conn:
                conn.execute(stmt)
            
            st.success("✅ Your attendance and privacy agreements have been saved!")
            st.session_state["plenary_done"] = True
            st.rerun()


def render_student(event):
    """Render the Student area."""
    email = st.session_state.get("email")
    if not email:
        st.error("Email non disponibile. Contatta l'amministratore.")
        st.stop()

        # --- Load student from DB first ---
    with engine.begin() as conn:
        student = find_student_user(email, conn=conn)
    if not student:
        st.error("Studente non trovato nel database. Contatta l'amministratore.")
        st.stop()

    # Primo accesso: mostra sempre fino a quando non è salvato in DB
    if not bool(student.get("plenary_attendance")):
        # evita che un vecchio flag di sessione nasconda la schermata
        st.session_state.pop("plenary_done", None)
        student_first_access(email)
        st.stop()


    # --- Mostra info studente ---
    with engine.begin() as conn:
        student = find_student_user(email, conn=conn)

    student_name = f"{student['givenName']} {student['sn']}"

    st.markdown(f"### 👤 {student_name}")
    st.info(f"✅ Matricola: `{student['matricola']}`")

    tab_companies, tab_roundtables = st.tabs(["Company Interview", "Round Tables"])

    # --- COMPANY INTERVIEWS ---
    with tab_companies:
        st.subheader("My Bookings & Notifications")

        with engine.begin() as conn:
            # Notifiche non lette
            notifs = get_unread_notifications(conn, event["id"], email)
            for n in notifs:
                colA, colB = st.columns([4, 1])
                with colA:
                    st.info(f"🔔 {n['message']}")
                with colB:
                    if st.button("Mark as read", key=f"read_{n['id']}"):
                        mark_notification_read(conn, n["id"])
                        st.rerun()

            # Prenotazioni studente
            myb = get_student_bookings(conn, event["id"], email)

        st.subheader("My Bookings")
        if myb:
            now = datetime.now()
            for b in myb:
                st.write(f"🕒 {b['slot']} — **{b['company']}**")
        else:
            st.info("No Bookings")

        # --- New Booking ---
        st.subheader("Book an interview")
        with engine.begin() as conn:
            comps = get_companies(conn, event["id"])

        pick = st.selectbox("Select the company", [c["name"] for c in comps])
        comp_id = next(c["id"] for c in comps if c["name"] == pick)

        with engine.begin() as conn:
            booked = {b["slot"] for b in get_bookings(conn, event["id"], comp_id)}
            myb = get_student_bookings(conn, event["id"], email)

        # --- Filter slots ---
        slots = generate_slots()
        my_booked_times = [datetime.strptime(b["slot"], "%H:%M") for b in myb]
        available = [s for s in slots if datetime.strptime(s, "%H:%M") not in my_booked_times and s not in booked]

        if not available:
            st.warning("No slots available for this company.")
            st.stop()

        slot_choice = st.selectbox("Available slots", available)
        cv_link = st.text_input("Optional link / CV", key="cv_link_input")

        if st.button("Book slot"):
            try:
                with engine.begin() as conn:
                    book_slot(conn, event["id"], comp_id, email, slot_choice, cv_link or None, student['matricola'])
                st.success(f"Booked {slot_choice} with {pick}.")
                st.rerun()
            except Exception as ex:
                st.error(f"Errore: {ex}")

    # --- ROUND TABLES ---
    with tab_roundtables:
        st.subheader("Book a Round Table  9 - 11 am")
        CAPACITY = {1: 140, 2: 140, 3: 73, 4: 130, 5: 113, 6: 68}

        with engine.begin() as conn:
            roundtables = get_roundtables(conn, event["id"])
            my_rt_bookings = {b['roundtable_id'] for b in get_student_roundtable_bookings(conn, event["id"], email)}
            current_counts = {rt['id']: conn.execute(text("SELECT COUNT(*) FROM roundtable_booking WHERE roundtable_id=:rt_id"), {"rt_id": rt["id"]}).scalar() for rt in roundtables}

        if my_rt_bookings:
            st.warning("⚠️ You have already booked a round table.")
        else:
            available_roundtables = [rt for rt in roundtables if current_counts[rt['id']] < CAPACITY[rt['id']] // 2]
            if available_roundtables:
                rt_choice_str = st.selectbox("Select a round table", [f"{rt['name']} – 📍 {rt['room']} ({current_counts[rt['id']]}/{CAPACITY[rt['id']]})" for rt in available_roundtables])
                rt_choice = next(rt for rt in available_roundtables if rt_choice_str.startswith(rt['name']))
                if st.button("Book this round table"):
                    with engine.begin() as conn:
                        book_roundtable(conn, event["id"], rt_choice['id'], email, student['matricola'])
                    st.success(f"You booked **{rt_choice['name']}** successfully!")
                    st.rerun()
            else:
                st.info("No round tables available for booking at this time.")

        # --- Mostra prenotazioni correnti ---
        st.subheader("Your Round Table Bookings")
        if my_rt_bookings:
            for rt in roundtables:
                if rt['id'] in my_rt_bookings:
                    st.write(f"- {rt['name']} – 📍 {rt['room']}")
        else:
            st.info("You have no round table bookings yet.")
