# auth.py
import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ------------------- secrets/env helpers -------------------
def read_secret(key: str, default=None):
    if hasattr(st, "secrets") and key in st.secrets:
        return st.secrets[key]
    return os.getenv(key, default)

AUTH_MODE = (read_secret("AUTH_MODE", "dev") or "dev").lower()  # "dev" | "prod"
ALLOW_PLAIN_FALLBACK = (AUTH_MODE != "prod")

# Admin creds
ADMIN_USER = read_secret("ADMIN_USER", "admin")
ADMIN_PASS_HASH = read_secret("ADMIN_PASS_HASH")
ADMIN_PASS = read_secret("ADMIN_PASS")

# Aziende demo/configurabili
ENI_USER_EMAIL = read_secret("ENI_USER_EMAIL", "hr@eni.com")
ENI_PASS_HASH  = read_secret("ENI_PASS_HASH")
ENI_PASS       = read_secret("ENI_PASS")

LEO_USER_EMAIL = read_secret("LEO_USER_EMAIL", "leonardo.pasquato@gmail.com")
LEO_PASS_HASH  = read_secret("LEO_PASS_HASH")
LEO_PASS       = read_secret("LEO_PASS")

# ------------------- bcrypt -------------------
try:
    import bcrypt
    HAS_BCRYPT = True
except Exception:
    HAS_BCRYPT = False
    if AUTH_MODE == "prod":
        # In produzione richiediamo bcrypt
        raise RuntimeError("Install 'bcrypt' for prod.")

# ------------------- DB access -------------------
from sqlalchemy import text
from core import engine  # safe now (core no longer imports auth)

# ------------------- hashing & checks -------------------
def make_hash(plain: str) -> str:
    if not HAS_BCRYPT:
        return plain
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def check_password(plain: str, stored: str | None) -> bool:
    if not stored:
        return False
    # bcrypt hash
    if stored.startswith("$2") and HAS_BCRYPT:
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
        except Exception:
            return False
    # fallback in dev
    return ALLOW_PLAIN_FALLBACK and (plain == stored)

def admin_ok(email: str, pw: str) -> bool:
    if email != (ADMIN_USER or ""):
        return False
    if ADMIN_PASS_HASH:
        return check_password(pw, ADMIN_PASS_HASH)
    return check_password(pw, ADMIN_PASS)

# ------------------- seed & user lookup -------------------
def seed_demo_users():
    """Create/update ENI & Leonardo users from env/secrets (hash preferred over plain)."""
    def _resolve_hash(pref_hash: str | None, plain: str | None) -> str | None:
        if pref_hash:
            return pref_hash
        if plain:
            return make_hash(plain)
        return None

    eni_hash = _resolve_hash(ENI_PASS_HASH, ENI_PASS)
    leo_hash = _resolve_hash(LEO_PASS_HASH, LEO_PASS)

    with engine.begin() as conn:
        # ENI
        cid = conn.execute(text("SELECT id FROM company WHERE name='ENI'")).scalar()
        if cid and eni_hash:
            row = conn.execute(
                text("SELECT id, password FROM company_user WHERE LOWER(email)=LOWER(:e)"),
                {"e": ENI_USER_EMAIL}
            ).mappings().first()
            if row:
                if row["password"] != eni_hash:
                    conn.execute(
                        text("UPDATE company_user SET password=:p WHERE id=:id"),
                        {"p": eni_hash, "id": row["id"]}
                    )
            else:
                conn.execute(
                    text("INSERT INTO company_user (company_id, email, password) VALUES (:cid, :e, :p)"),
                    {"cid": cid, "e": ENI_USER_EMAIL, "p": eni_hash}
                )

        # Leonardo
        cid2 = conn.execute(text("SELECT id FROM company WHERE name='Leonardo'")).scalar()
        if cid2 and leo_hash:
            row = conn.execute(
                text("SELECT id, password FROM company_user WHERE LOWER(email)=LOWER(:e)"),
                {"e": LEO_USER_EMAIL}
            ).mappings().first()
            if row:
                if row["password"] != leo_hash:
                    conn.execute(
                        text("UPDATE company_user SET password=:p WHERE id=:id"),
                        {"p": leo_hash, "id": row["id"]}
                    )
            else:
                conn.execute(
                    text("INSERT INTO company_user (company_id, email, password) VALUES (:cid, :e, :p)"),
                    {"cid": cid2, "e": LEO_USER_EMAIL, "p": leo_hash}
                )

def find_company_user(conn, email, password):
    row = conn.execute(
        text("""SELECT cu.company_id, cu.email, c.name as company_name, cu.password
                FROM company_user cu 
                JOIN company c ON c.id=cu.company_id 
                WHERE LOWER(cu.email)=:e LIMIT 1"""),
        {"e": email.strip().lower()}
    ).mappings().first()
    if not row:
        return None
    if check_password(password, row["password"]):
        return {"company_id": row["company_id"], "email": row["email"], "company_name": row["company_name"]}
    return None

# ------------------- session utils -------------------
def reset_session():
    for k in ("role", "email", "company_id", "student_name"):
        if k in st.session_state:
            del st.session_state[k]
