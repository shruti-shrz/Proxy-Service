import os
import sqlite3
import hashlib
import hmac
import secrets
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
PBKDF2_ITERATIONS = int(os.getenv("PBKDF2_ITERATIONS", "100000"))

if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is required. Add it to .env before starting auth service.")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
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


def create_access_token(user_id: int, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def get_bearer_token(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return credentials.credentials


def get_current_claims(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)) -> dict:
    token = get_bearer_token(credentials)
    return decode_access_token(token)


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

    token = create_access_token(user["id"], user["username"], user["role"])
    return LoginResponse(
        access_token=token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
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
def verify(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)) -> dict:
    token = get_bearer_token(credentials)
    claims = decode_access_token(token)
    return {
        "valid": True,
        "user_id": claims["sub"],
        "username": claims["username"],
        "role": claims["role"],
        "exp": claims["exp"],
    }


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
def logout() -> dict:
    return {"message": "Client must discard token. Stateless JWT logout acknowledged."}
