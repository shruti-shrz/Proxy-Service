import os
import sqlite3
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field


app = FastAPI(title="Auth Service", version="1.0.0")

bearer_scheme = HTTPBearer(auto_error=False)

load_dotenv()

DB_PATH = os.getenv("AUTH_DB_PATH", "auth.db")
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
PBKDF2_ITERATIONS = int(os.getenv("PBKDF2_ITERATIONS", "100000"))

if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is required. Add it to .env before starting auth service.")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int
    role: str


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="user")


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32)


ALLOWED_ROLES = {"user", "admin"}


def hash_password(password: str, salt: Optional[str] = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, digest = stored_hash.split("$", 1)
    except ValueError:
        return False
    candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, f"{salt}${digest}")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            is_revoked INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            revoked_at INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            is_revoked INTEGER NOT NULL DEFAULT 0,
            revoked_at INTEGER,
            replaced_by_hash TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(session_id) REFERENCES sessions(id)
        )
        """
    )
    conn.commit()

    cur.execute("SELECT COUNT(*) AS count FROM users")
    count = cur.fetchone()["count"]
    if count == 0:
        seed_users = [
            ("alice", hash_password("alice123"), "user", 1),
            ("bob", hash_password("bob123"), "admin", 1),
        ]
        cur.executemany(
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
            seed_users,
        )
        conn.commit()
    conn.close()


def create_access_token(user_id: int, username: str, role: str, session_id: str) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "sid": session_id,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    if claims.get("typ") != "access" or "sid" not in claims:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
    return claims


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_refresh_token(conn: sqlite3.Connection, user_id: int, session_id: str) -> tuple[str, int, str]:
    raw_token = secrets.token_urlsafe(48)
    token_hash = hash_refresh_token(raw_token)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    expires_at = int((datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)).timestamp())
    conn.execute(
        """
        INSERT INTO refresh_tokens (token_hash, user_id, session_id, expires_at, created_at, is_revoked)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (token_hash, user_id, session_id, expires_at, now_ts),
    )
    return raw_token, expires_at, token_hash


def revoke_session(conn: sqlite3.Connection, session_id: str) -> None:
    now_ts = int(datetime.now(timezone.utc).timestamp())
    conn.execute(
        "UPDATE sessions SET is_revoked = 1, revoked_at = ? WHERE id = ?",
        (now_ts, session_id),
    )
    conn.execute(
        """
        UPDATE refresh_tokens
        SET is_revoked = 1, revoked_at = ?
        WHERE session_id = ? AND is_revoked = 0
        """,
        (now_ts, session_id),
    )


def get_bearer_token(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return credentials.credentials


def get_current_claims(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)) -> dict:
    token = get_bearer_token(credentials)
    claims = decode_access_token(token)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT is_revoked FROM sessions WHERE id = ?", (claims["sid"],))
    session = cur.fetchone()
    conn.close()
    if not session or session["is_revoked"] == 1:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked")
    return claims


def require_admin(claims: dict = Depends(get_current_claims)) -> dict:
    if claims.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return claims


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "auth-service"}


@app.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (payload.username,))
    user = cur.fetchone()
    conn.close()

    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if user["is_active"] != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    conn = get_connection()
    session_id = str(uuid.uuid4())
    now_ts = int(datetime.now(timezone.utc).timestamp())
    conn.execute(
        "INSERT INTO sessions (id, user_id, is_revoked, created_at) VALUES (?, ?, 0, ?)",
        (session_id, user["id"], now_ts),
    )
    refresh_token, refresh_expires_at, _ = issue_refresh_token(conn, user["id"], session_id)
    conn.commit()
    conn.close()

    token = create_access_token(user["id"], user["username"], user["role"], session_id)
    return LoginResponse(
        access_token=token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_expires_in=max(0, refresh_expires_at - now_ts),
        role=user["role"],
    )


@app.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest) -> UserResponse:
    role = payload.role.lower()
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", (payload.username,))
    existing_user = cur.fetchone()
    if existing_user:
        conn.close()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    password_hash = hash_password(payload.password)
    cur.execute(
        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
        (payload.username, password_hash, role, 1),
    )
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return UserResponse(id=user_id, username=payload.username, role=role, is_active=True)


@app.get("/verify")
def verify(claims: dict = Depends(get_current_claims)) -> dict:
    return {
        "valid": True,
        "user_id": claims["sub"],
        "username": claims["username"],
        "role": claims["role"],
        "session_id": claims["sid"],
        "exp": claims["exp"],
    }


@app.post("/refresh", response_model=LoginResponse)
def refresh(payload: RefreshRequest) -> LoginResponse:
    token_hash = hash_refresh_token(payload.refresh_token)
    now_ts = int(datetime.now(timezone.utc).timestamp())

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT rt.*, u.username, u.role, u.is_active, s.is_revoked AS session_revoked
        FROM refresh_tokens rt
        JOIN users u ON u.id = rt.user_id
        JOIN sessions s ON s.id = rt.session_id
        WHERE rt.token_hash = ?
        """,
        (token_hash,),
    )
    token_row = cur.fetchone()

    if not token_row:
        conn.close()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if token_row["is_revoked"] == 1:
        revoke_session(conn, token_row["session_id"])
        conn.commit()
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token reuse detected. Session revoked.",
        )

    if token_row["expires_at"] <= now_ts:
        conn.close()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    if token_row["session_revoked"] == 1:
        conn.close()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked")

    if token_row["is_active"] != 1:
        revoke_session(conn, token_row["session_id"])
        conn.commit()
        conn.close()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    new_refresh_token, refresh_expires_at, new_hash = issue_refresh_token(
        conn, token_row["user_id"], token_row["session_id"]
    )
    cur.execute(
        """
        UPDATE refresh_tokens
        SET is_revoked = 1, revoked_at = ?, replaced_by_hash = ?
        WHERE token_hash = ?
        """,
        (now_ts, new_hash, token_hash),
    )
    conn.commit()
    conn.close()

    access_token = create_access_token(
        token_row["user_id"], token_row["username"], token_row["role"], token_row["session_id"]
    )
    return LoginResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_expires_in=max(0, refresh_expires_at - now_ts),
        role=token_row["role"],
    )


@app.get("/me", response_model=UserResponse)
def me(claims: dict = Depends(get_current_claims)) -> UserResponse:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, is_active FROM users WHERE id = ?", (claims["sub"],))
    user = cur.fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse(
        id=user["id"],
        username=user["username"],
        role=user["role"],
        is_active=bool(user["is_active"]),
    )


@app.post("/change-password")
def change_password(payload: ChangePasswordRequest, claims: dict = Depends(get_current_claims)) -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE id = ?", (claims["sub"],))
    user = cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not verify_password(payload.current_password, user["password_hash"]):
        conn.close()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    new_hash = hash_password(payload.new_password)
    cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, claims["sub"]))
    conn.commit()
    conn.close()
    return {"message": "Password updated successfully"}


@app.get("/users", response_model=list[UserResponse])
def list_users(_: dict = Depends(require_admin)) -> list[UserResponse]:
    conn = get_connection()
    cur = conn.cursor()
    users = cur.execute("SELECT id, username, role, is_active FROM users ORDER BY id").fetchall()
    conn.close()
    return [
        UserResponse(
            id=user["id"],
            username=user["username"],
            role=user["role"],
            is_active=bool(user["is_active"]),
        )
        for user in users
    ]


@app.patch("/users/{username}/deactivate")
def deactivate_user(username: str, _: dict = Depends(require_admin)) -> dict:
    if username == "bob":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate default admin")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_active = 0 WHERE username = ?", (username,))
    if cur.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    conn.commit()
    conn.close()
    return {"message": f"User '{username}' deactivated"}


@app.post("/logout")
def logout(claims: dict = Depends(get_current_claims)) -> dict:
    conn = get_connection()
    revoke_session(conn, claims["sid"])
    conn.commit()
    conn.close()
    return {"message": "Session revoked successfully"}
