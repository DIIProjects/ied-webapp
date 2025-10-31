from core import engine, text

OLD = "Infeon Technologies Italia"
NEW = "Infineon Technologies Italia"

with engine.begin() as conn:
    # Controlla quale record esiste
    rows = list(conn.execute(text("SELECT id, name FROM company WHERE name LIKE '%Biko%'")).mappings())
    print("🔍 Aziende trovate:")
    for r in rows:
        print(f" - {r['id']}: {r['name']}")

    # Se esiste il nome sbagliato, rinominalo
    conn.execute(text("UPDATE company SET name = :new WHERE name = :old"), {"new": NEW, "old": OLD})
    print("✅ Azienda rinominata con successo (senza cambiare l'id)")
