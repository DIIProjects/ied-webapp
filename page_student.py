# page_student.py
import streamlit as st
import pandas as pd
from sqlalchemy import text

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
    book_roundtable
)

def render_student(event):
    """Render the Student area (unchanged behavior)."""
    student = st.session_state.get("student_name") or st.session_state["email"]
    st.title("Student Area")

    tab_companies, tab_roundtables = st.tabs(["Company Interview", "Round Tables"])

    with tab_companies:
        # Notifications + my bookings
        with engine.begin() as conn:
            # Notifications
            notifs = get_unread_notifications(conn, event["id"], student)
            for n in notifs:
                colA, colB = st.columns([4, 1])
                with colA:
                    st.info(f"🔔 {n['message']}")
                with colB:
                    if st.button("Segna letta", key=f"read_{n['id']}"):
                        mark_notification_read(conn, n["id"])
                        st.rerun()

            # My bookings
            st.subheader("My Bookings")
            myb = get_student_bookings(conn, event["id"], student)

        if myb:
            for b in myb:
                st.write(f"- {b['slot']} con {b['company']}")
        else:
            st.info("No Bookings")

        # New booking
        st.subheader("Book an interview")

        with engine.begin() as conn:
            comps = get_companies(conn, event["id"])

        pick = st.selectbox("Select the company", [c["name"] for c in comps])
        comp_id = next(c["id"] for c in comps if c["name"] == pick)

        with engine.begin() as conn:
            booked = {b["slot"] for b in get_bookings(conn, event["id"], comp_id)}

        slots = generate_slots()
        available = [s for s in slots if s not in booked]

        if not available:
            st.warning("Any available slot for this company")
            return

        slot_choice = st.selectbox("Available slots", available)

        # Optional CV link
        st.caption("Add a link (optional)")
        cv_link = st.text_input(
            "Link for further information about your experience (e.g. GitHub, LinkedIn, Google Drive)",
            key="cv_link_input"
        )

        if st.button("Book slot"):
            try:
                cv_path = cv_link or None  # save link or None
                with engine.begin() as conn:
                    book_slot(conn, event["id"], comp_id, student, slot_choice, cv_path)

                if cv_link:
                    st.success(f"Booked {slot_choice} with {pick}. CV/link saved.")
                else:
                    st.success(f"Booked {slot_choice} with {pick}.")

                # try to rerun; if st.rerun() not available, fallback to session_state increment
                try:
                    st.rerun()
                except Exception:
                    st.session_state["book_update"] = st.session_state.get("book_update", 0) + 1

            except Exception as ex:
                st.error(f"Errore: {ex}")
   
    with tab_roundtables:
        st.subheader("Book a Round Table")

        student = st.session_state.get("student_name") or st.session_state["email"]

        # Capienza dei tavoli (ID → capienza)
        CAPACITY = {
            1: 140,
            2: 140,
            3: 73,
            4: 130,
            5: 113,
            6: 68,
        }

        with engine.begin() as conn:
            roundtables = get_roundtables(conn, event["id"])
            my_rt_bookings = {b['roundtable_id'] for b in get_student_roundtable_bookings(conn, event["id"], student)}

            # Conta prenotazioni per ogni tavolo
            current_counts = {}
            for rt in roundtables:
                q = text("SELECT COUNT(*) FROM roundtable_booking WHERE roundtable_id = :rt_id")
                current_counts[rt['id']] = conn.execute(q, {"rt_id": rt["id"]}).scalar()

        if not roundtables:
            st.info("No round tables available for this event.")
        else:
            # Controlla se tutte hanno raggiunto almeno il 50%
            phase2 = all(current_counts[rt['id']] >= CAPACITY[rt['id']] // 2 for rt in roundtables)

            # Determina roundtable prenotabili
            available_roundtables = []
            for rt in roundtables:
                limit = CAPACITY[rt['id']] if phase2 else CAPACITY[rt['id']] // 2
                if current_counts[rt['id']] < limit and rt['id'] not in my_rt_bookings:
                    available_roundtables.append(rt)

            if not available_roundtables:
                st.info("No round tables available for booking at this time.")
            else:
                # Mostra percentuale riempimento
                options = [
                    f"{rt['name']} – 📍 {rt['room']}"
                    for rt in available_roundtables
                ]
                rt_choice_str = st.selectbox("Select a round table", options)

                if rt_choice_str:
                    rt_choice = next(rt for rt in available_roundtables if rt_choice_str.startswith(rt['name']))

                    if st.button("Book this round table"):
                        try:
                            with engine.begin() as conn:
                                book_roundtable(conn, event["id"], rt_choice['id'], student)
                            st.success(f"You booked **{rt_choice['name']}** successfully!")
                        except Exception as ex:
                            st.error(f"Error while booking: {ex}")

            # Show student's current bookings
            st.subheader("Your Round Table Bookings")
            if my_rt_bookings:
                for rt in roundtables:
                    if rt['id'] in my_rt_bookings:
                        st.write(f"- {rt['name']} – 📍 {rt['room']}")
            else:
                st.info("You have no round table bookings yet.")

                                        