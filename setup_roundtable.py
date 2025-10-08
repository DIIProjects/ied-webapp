# setup_roundtables.py
from core import engine, text

# Round tables definition
roundtables = [
    (1, 'Round Table 1', 'A103'),
    (1, 'Round Table 2', 'A105'),
    (1, 'Round Table 3', 'A107'),
    (1, 'Round Table 4', 'A206'),
    (1, 'Round Table 5', 'A207'),
    (1, 'Round Table 6', 'A210'),
]

with engine.begin() as conn:
    # ⚠️ Non serve più droppare le tabelle (così non cancelli i booking già fatti!)
    # Ti basta inserire le roundtable se non esistono
    for event_id, name, room in roundtables:
        conn.execute(
            text("""
                INSERT INTO roundtable (event_id, name, room)
                VALUES (:event_id, :name, :room)
                ON CONFLICT(event_id, name) DO NOTHING
            """),
            {"event_id": event_id, "name": name, "room": room}
        )

print("✅ Round tables setup completed successfully!")
