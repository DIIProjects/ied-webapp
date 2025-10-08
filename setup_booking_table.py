# setup_booking_constraints.py
from core import engine, text

with engine.begin() as conn:
    print("🔍 Verifica struttura tabella 'booking'...")

    # --- 1️⃣ Recupera le colonne esistenti ---
    cols = [r["name"] for r in conn.execute(text("PRAGMA table_info(booking)")).mappings()]
    print(f"Colonne trovate: {cols}")

    # --- 2️⃣ Aggiunge colonne mancanti (cv e status) ---
    if "cv" not in cols:
        conn.execute(text("ALTER TABLE booking ADD COLUMN cv TEXT"))
        print("✅ Colonna 'cv' aggiunta a booking")

    if "status" not in cols:
        conn.execute(text("ALTER TABLE booking ADD COLUMN status TEXT DEFAULT 'active'"))
        print("✅ Colonna 'status' aggiunta a booking")

    # --- 3️⃣ Controlla gli indici esistenti ---
    idx = list(conn.execute(text("PRAGMA index_list(booking)")).mappings())
    idx_names = [i["name"] for i in idx]
    print(f"Indici trovati: {idx_names}")

    # --- 4️⃣ Crea vincolo UNIQUE se non esiste ---
    if not any("unique_booking" in i for i in idx_names):
        conn.execute(text("""
            CREATE UNIQUE INDEX unique_booking
            ON booking (event_id, company_id, student, slot)
        """))
        print("✅ Vincolo UNIQUE creato su (event_id, company_id, student, slot)")
    else:
        print("ℹ️ Vincolo UNIQUE già presente su booking")

print("\n🎯 Setup completato con successo!")
