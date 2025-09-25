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

        # Optional CV
        st.caption("Upload your CV (PDF, optional)")
        cv_file = st.file_uploader("Curriculum (PDF)", type=["pdf"], key="cv_upload")

        if st.button("Book slot"):
            try:
                cv_path = save_cv_file(cv_file, event["id"], comp_id, student, slot_choice)
                with engine.begin() as conn:
                    book_slot(conn, event["id"], comp_id, student, slot_choice, cv_path)
                if cv_path:
                    st.success(f"Booked {slot_choice} con {pick}. CV uploaded.")
                else:
                    st.success(f"Booked {slot_choice} con {pick}.")
                st.rerun()
            except Exception as ex:
                st.error(f"Errore: {ex}")

    with tab_roundtables:
        st.subheader("Book a Round Table")

        student = st.session_state.get("student_name") or st.session_state["email"]

        # Load all roundtables and student bookings once
        with engine.begin() as conn:
            roundtables = get_roundtables(conn, event["id"])
            my_rt_bookings = {b['roundtable_id'] for b in get_student_roundtable_bookings(conn, event["id"], student)}

        if not roundtables:
            st.info("No round tables available for this event.")
        else:
            # Filter out roundtables already booked by this student
            available_roundtables = [rt for rt in roundtables if rt['id'] not in my_rt_bookings]

            if not available_roundtables:
                st.info("You have already booked all available round tables.")
            else:
                # Selectbox with name + room
                options = [f"{rt['name']} – 📍 {rt['room']}" for rt in available_roundtables]
                rt_choice_str = st.selectbox("Select a round table", options)

                if rt_choice_str:
                    # Map back to the roundtable dict
                    rt_choice = next(rt for rt in available_roundtables if f"{rt['name']} – 📍 {rt['room']}" == rt_choice_str)

                    if st.button("Book this round table"):
                        try:
                            with engine.begin() as conn:
                                book_roundtable(conn, event["id"], rt_choice['id'], student)
                            st.success(f"You booked **{rt_choice['name']}** successfully!")
                            #st.experimental_rerun()
                        except Exception as ex:
                            st.error(f"Error while booking: {ex}")

                # Optional: show current bookings
                st.subheader("Your Round Table Bookings")
                if my_rt_bookings:
                    for rt in roundtables:
                        if rt['id'] in my_rt_bookings:
                            st.write(f"- {rt['name']} – 📍 {rt['room']}")
                else:
                    st.info("You have no round table bookings yet.")
                                        