# auth.py
import os
import streamlit as st
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text
from core import engine

load_dotenv()

# ------------------- STUDENT USER -------------------

def create_student_user(conn, givenName, sn, matricola, email, password):
    """
    Crea uno studente con password hashata.
    Restituisce lo student_id.
    """
    if not password:
        raise ValueError("Password cannot be empty!")

    hashed_pw = generate_password_hash(password)

    conn.execute(text("""
        INSERT INTO student (givenName, sn, matricola, email, password)
        VALUES (:givenName, :sn, :matricola, :email, :password)
    """), {
        "givenName": givenName.strip(),
        "sn": sn.strip(),
        "matricola": matricola.strip(),
        "email": email.lower().strip(),
        "password": hashed_pw
    })

    student_id = conn.execute(
        text("SELECT id FROM student WHERE email=:email"),
        {"email": email.lower().strip()}
    ).scalar()

    print(f"DEBUG: created student_id={student_id}, hashed_pw={hashed_pw}")
    return student_id

def find_student_user(email, password=None, conn=None):
    """
    Trova studente per email. Se password fornita, verifica l'hash.
    """
    close_conn = False
    if conn is None:
        from core import engine
        conn = engine.connect()
        close_conn = True

    q = "SELECT * FROM student WHERE email=:email"
    res = conn.execute(text(q), {"email": email.lower().strip()}).mappings().first()

    if close_conn:
        conn.close()

    if not res:
        return None

    if password:
        if not check_password_hash(res["password"], password):
            return None

    return res

def create_student_if_not_exists(email: str, givenName: str, sn: str, matricola: str, password: str = None, plenary_attendance: int = 0):
    """
    Inserisce lo studente nel DB solo se non esiste già.
    Controlla unicità su email e matricola.
    Password opzionale, viene salvata come hash se fornita.
    """
    email_clean = email.lower().strip()
    matricola_clean = matricola.strip()

    with engine.begin() as conn:
        # Controllo esistenza email
        exists_email = conn.execute(
            text("SELECT 1 FROM student WHERE email=:e"),
            {"e": email_clean}
        ).scalar()
        if exists_email:
            raise ValueError(f"Email '{email_clean}' già registrata")

        # Controllo unicità matricola
        exists_matricola = conn.execute(
            text("SELECT 1 FROM student WHERE matricola=:m"),
            {"m": matricola_clean}
        ).scalar()
        if exists_matricola:
            raise ValueError(f"Matricola '{matricola_clean}' già registrata")

        # Hash password se fornita
        pw_hash = generate_password_hash(password) if password else ''

        # Inserimento
        conn.execute(
            text("""
                INSERT INTO student (email, givenName, sn, matricola, plenary_attendance, password)
                VALUES (:email, :givenName, :sn, :matricola, :plenary, :pw)
            """),
            {
                "email": email_clean,
                "givenName": givenName.strip(),
                "sn": sn.strip(),
                "matricola": matricola_clean,
                "plenary": plenary_attendance,
                "pw": pw_hash
            }
        )

# ------------------- secrets/env helpers -------------------
def read_secret(key: str, default=None):
    if hasattr(st, "secrets") and key in st.secrets:
        return st.secrets[key]
    return os.getenv(key, default)

# Default di PRODUZIONE
AUTH_MODE = (read_secret("AUTH_MODE", "prod") or "prod").lower()  # "dev" | "prod"
ALLOW_PLAIN_FALLBACK = (AUTH_MODE != "prod")

# ====== SAML / Shibboleth config ======
# Default prod: SAML attivo; se Apache non passa attributi, non succede nulla (fallback UI invariata)
SAML_MODE = (read_secret("SAML_MODE", "sso") or "sso").lower()  # "off" | "sso"
SAML_ALLOWED_EMAIL_DOMAINS = [
    d.strip().lower()
    for d in (read_secret("SAML_ALLOWED_EMAIL_DOMAINS", "@unitn.it") or "").split(",")
    if d.strip()
]

# possibili nomi degli attributi da mod_shib / proxy
SAML_ATTR_CANDIDATES = {
    "email": ["mail", "eppn", "eduPersonPrincipalName", "email",
              "HTTP_MAIL", "HTTP_EPPN", "HTTP_EMAIL", "X-Auth-Email"],
    "givenName": ["givenName", "given_name", "gn", "HTTP_GIVENNAME", "X-Auth-GivenName"],
    "sn": ["sn", "surname", "familyName", "family_name", "HTTP_SN", "X-Auth-Surname"],
    "displayName": ["displayName", "cn", "commonName", "HTTP_DISPLAYNAME", "X-Auth-DisplayName"],
    "remote_user": ["REMOTE_USER", "HTTP_REMOTE_USER", "X-Remote-User"],
}

def _domain_ok(email: str) -> bool:
    if not SAML_ALLOWED_EMAIL_DOMAINS:
        return True
    e = (email or "").lower()
    return any(e.endswith(dom) for dom in SAML_ALLOWED_EMAIL_DOMAINS)

def _get_first_present(d: dict, keys: list[str]) -> str | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, list):
            if v:
                return v[0]
        elif v:
            return v
    return None

def _extract_from_query() -> dict:
    """Read SAML attributes from the URL query (?mail=...&givenName=...&sn=...)."""
    try:
        qp = st.query_params  # new stable API
        params = qp.to_dict() if hasattr(qp, "to_dict") else dict(qp)
    except Exception:
        params = {}
    # normalize to scalars
    return {k: (v[0] if isinstance(v, list) else v) for k, v in params.items()}


def _extract_from_env() -> dict:
    """Legge attributi da environment/headers passati da Apache."""
    env = dict(os.environ)
    add = {}
    for k, v in list(env.items()):
        if k.startswith("HTTP_"):
            add[k[5:]] = v
    env.update(add)
    return env

def _derive_name(given: str | None, sn: str | None, display: str | None, email: str) -> tuple[str, str]:
    if given or sn:
        return (given or "").strip() or (email.split("@")[0]), (sn or "").strip()
    if display:
        parts = display.strip().split()
        if len(parts) >= 2:
            return " ".join(parts[:-1]), parts[-1]
        return display.strip(), ""
    local = email.split("@")[0]
    return local, ""

def bootstrap_student_login() -> bool:
    """
    Se SAML_MODE è 'sso' e arrivano attributi SAML (query/env),
    imposta la sessione "student" e ritorna True (solo la prima volta).
    Se la sessione è già impostata o non arrivano attributi, ritorna False.
    """
    if SAML_MODE != "sso":
        return False

    # non fare nulla se già loggato (evita rerun loop)
    if st.session_state.get("role") == "student":
        return False

    q = _extract_from_query()
    env = _extract_from_env()

    catalog = {}
    catalog.update(env)
    catalog.update(q)

    email = _get_first_present(catalog, SAML_ATTR_CANDIDATES["email"])
    if not email:
        email = _get_first_present(catalog, SAML_ATTR_CANDIDATES["remote_user"])
    if not email:
        return False

    email = str(email).strip()
    if not _domain_ok(email):
        return False

    given = _get_first_present(catalog, SAML_ATTR_CANDIDATES["givenName"])
    sn = _get_first_present(catalog, SAML_ATTR_CANDIDATES["sn"])
    display = _get_first_present(catalog, SAML_ATTR_CANDIDATES["displayName"])
    first, last = _derive_name(given, sn, display, email)

    st.session_state["role"] = "student"
    st.session_state["email"] = email
    st.session_state["student_name"] = f"{first} {last}".strip() or email.split("@")[0]

    # Clean querystring so PII isn't left in the URL
    try:
        st.query_params.clear()
    except Exception:
        pass

    return True

# ------------------- Admin & Companies -------------------
ADMIN_USER = read_secret("ADMIN_USER", "admin")
ADMIN_PASS_HASH = read_secret("ADMIN_PASS_HASH")
ADMIN_PASS = read_secret("ADMIN_PASS")

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
        raise RuntimeError("Install 'bcrypt' for prod.")

# ------------------- DB access -------------------
from sqlalchemy import text
from core import engine  # core non importa auth => OK

# ------------------- hashing & checks -------------------
def make_hash(plain: str) -> str:
    if not HAS_BCRYPT:
        return plain
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def check_password(plain: str, stored: str | None) -> bool:
    if not stored:
        return False
    if stored.startswith("$2") and HAS_BCRYPT:
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
        except Exception:
            return False
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
