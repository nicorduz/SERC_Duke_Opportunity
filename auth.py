"""
auth.py — minimal username/password gate for Streamlit, mirroring the pattern
from your other repo. Credentials live in st.secrets (never in git), stored as
SHA-256 hashes. Call require_login() at the very top of app.py, right after
st.set_page_config(); the app body only runs once a valid user is in session.

secrets.toml
------------
[auth]
# username = sha256(password)  — generate with the helper at the bottom
niko    = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"
gcernjul= "..."

[auth_meta]
title = "Nofar · SERC Deal Intelligence"
"""
from __future__ import annotations
import hashlib
import streamlit as st


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def _check(user: str, pw: str) -> bool:
    users = st.secrets.get("auth", {})
    stored = users.get(user)
    return bool(stored) and _hash(pw) == stored


def current_user() -> str | None:
    return st.session_state.get("_auth_user")


def logout():
    st.session_state.pop("_auth_user", None)
    st.rerun()


def require_login():
    """Blocks the app until a valid login. Returns the username when authenticated."""
    if st.session_state.get("_auth_user"):
        return st.session_state["_auth_user"]

    # Dev bypass: if no users are configured in secrets, don't block the app.
    if not st.secrets.get("auth", {}):
        st.session_state["_auth_user"] = "dev"
        return "dev"

    meta = st.secrets.get("auth_meta", {})
    st.markdown(f"### {meta.get('title', 'Sign in')}")
    with st.form("login_form", clear_on_submit=False):
        u = st.text_input("User")
        p = st.text_input("Password", type="password")
        ok = st.form_submit_button("Entrar")
    if ok:
        if _check(u.strip(), p):
            st.session_state["_auth_user"] = u.strip()
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")
    st.stop()   # halt the rest of app.py until logged in


if __name__ == "__main__":
    # helper: python auth.py mypassword  ->  prints the hash to paste in secrets.toml
    import sys
    if len(sys.argv) > 1:
        print(_hash(sys.argv[1]))
    else:
        print("usage: python auth.py <password>")
