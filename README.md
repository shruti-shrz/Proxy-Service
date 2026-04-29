# Proxy-Service

Centralized authentication and role-based access control (RBAC) proxy prototype using FastAPI.

## Purpose

This project demonstrates how to protect internal services by requiring authentication and applying role-aware authorization before forwarding requests to backend resources. A reverse proxy intercepts all traffic, validates tokens against a central auth service, and enforces RBAC policies — backend services themselves contain no auth logic.

## Architecture

```
Client
  │
  ▼
Reverse Proxy  ──── calls /verify ────▶  Auth Service (port 8000)
  │                                          │
  │  (if allowed)                            ├── SQLite DB (users, sessions, tokens)
  ▼                                          └── Issues JWT + refresh tokens
Backend Service A (port 8001)   ← any authenticated user
Backend Service B (port 8002)   ← admin role only
```

### High-Level Flow

1. Client authenticates with `auth_service` and receives a JWT access token and a refresh token.
2. Client sends subsequent requests with the JWT in the `Authorization: Bearer` header.
3. Reverse proxy calls `auth_service /verify` to validate the token and retrieve claims.
4. Reverse proxy applies RBAC policy based on the role claim.
5. Request is forwarded to the backend service only if the policy allows it.

## Project Structure

```text
Proxy-Service/
├── auth_service/
│   └── main.py              # Auth service: login, register, verify, refresh, sessions
├── backend_service_a/
│   └── main.py              # General backend (any authenticated user)
├── backend_service_b/
│   └── main.py              # Admin backend (admin role only)
├── .env.example             # Environment variable template
├── .env                     # Local config (not committed)
├── .gitignore
├── requirements.txt
└── README.md
```

## Tech Stack

| Component         | Technology                        |
|-------------------|-----------------------------------|
| Language          | Python 3.10+                      |
| Web framework     | FastAPI                           |
| ASGI server       | Uvicorn                           |
| Authentication    | JWT (PyJWT, HS256)                |
| Database          | SQLite (file-based, no setup needed) |
| Password hashing  | PBKDF2-HMAC-SHA256 (100 000 iters)|
| Config            | python-dotenv                     |

## Prerequisites

- Python 3.10+
- `pip`

## Setup

1. Create and activate a virtual environment:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in values:

```bash
cp .env.example .env
```

Minimum `.env`:

```env
JWT_SECRET=replace_with_a_256bit_random_hex_secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
AUTH_DB_PATH=auth.db
PBKDF2_ITERATIONS=100000
```

Generate a strong secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Run Services

Start each service in its own terminal from the project root.

```bash
# Auth service
uvicorn auth_service.main:app --host 0.0.0.0 --port 8000 --reload

# Backend service A
uvicorn backend_service_a.main:app --host 0.0.0.0 --port 8001 --reload

# Backend service B
uvicorn backend_service_b.main:app --host 0.0.0.0 --port 8002 --reload
```

## Seed Accounts

On first startup the auth service auto-creates:

| Username | Password   | Role  |
|----------|------------|-------|
| `alice`  | `alice123` | user  |
| `bob`    | `bob123`   | admin |

The default admin (`bob`) cannot be deactivated.

## Auth Service API

Base URL: `http://localhost:8000`

| Method  | Endpoint                          | Auth required | Description                        |
|---------|-----------------------------------|---------------|------------------------------------|
| GET     | `/health`                         | No            | Health check                       |
| POST    | `/register`                       | No            | Register a new user                |
| POST    | `/login`                          | Username + password (body) | Login; returns access + refresh tokens |
| GET     | `/verify`                         | Bearer token  | Validate JWT and return claims     |
| POST    | `/refresh`                        | Refresh token (body) | Rotate refresh token, issue new access and refresh tokens |
| GET     | `/me`                             | Bearer token  | Get current user profile           |
| POST    | `/change-password`                | Bearer token  | Change own password                |
| POST    | `/logout`                         | Bearer token  | Revoke current session             |
| GET     | `/users`                          | Admin only    | List all users                     |
| PATCH   | `/users/{username}/deactivate`    | Admin only    | Deactivate a user account          |

### Register

```bash
curl -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{"username":"charlie","password":"charlie123","role":"user"}'
```

### Login

```bash
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"alice123"}'
```

Response includes `access_token` (short-lived JWT) and `refresh_token`.

### Verify Token

```bash
curl http://localhost:8000/verify \
  -H "Authorization: Bearer <access_token>"
```

### Refresh Access Token

```bash
curl -X POST http://localhost:8000/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_token>"}'
```

Returns a new `access_token` and a rotated `refresh_token`. The old refresh token is immediately revoked.

### Logout

```bash
curl -X POST http://localhost:8000/logout \
  -H "Authorization: Bearer <access_token>"
```

Revokes the entire session; all tokens bound to that session become invalid.

### Admin: List Users

```bash
curl http://localhost:8000/users \
  -H "Authorization: Bearer <admin_access_token>"
```

### Admin: Deactivate User

```bash
curl -X PATCH http://localhost:8000/users/charlie/deactivate \
  -H "Authorization: Bearer <admin_access_token>"
```

## Backend APIs

**Service A** — `http://localhost:8001` (any authenticated user)

| Method | Endpoint  | Description      |
|--------|-----------|------------------|
| GET    | `/health` | Health check     |
| GET    | `/data`   | General resource |

**Service B** — `http://localhost:8002` (admin role only)

| Method | Endpoint      | Description            |
|--------|---------------|------------------------|
| GET    | `/health`     | Health check           |
| GET    | `/admin-data` | Sensitive admin resource |

## Quick Test (PowerShell)

```powershell
# Login as alice
$login = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/login `
  -ContentType "application/json" `
  -Body '{"username":"alice","password":"alice123"}'

# Verify token
Invoke-RestMethod -Uri http://127.0.0.1:8000/verify `
  -Headers @{ Authorization = "Bearer $($login.access_token)" }

# Refresh token
$refreshed = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/refresh `
  -ContentType "application/json" `
  -Body "{`"refresh_token`":`"$($login.refresh_token)`"}"

# Logout (revokes session)
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/logout `
  -Headers @{ Authorization = "Bearer $($login.access_token)" }
```

## Database Schema

SQLite file at `AUTH_DB_PATH` (default `auth.db`). Created automatically on first run.

**`users`** — `id`, `username` (unique), `password_hash` (salt$digest), `role` (user|admin), `is_active`

**`sessions`** — `id` (UUID), `user_id`, `is_revoked`, `created_at`, `revoked_at`

**`refresh_tokens`** — `id`, `token_hash` (SHA-256), `user_id`, `session_id`, `expires_at`, `created_at`, `is_revoked`, `revoked_at`, `replaced_by_hash`

## Security Notes

- **JWT_SECRET** must be set in `.env` and kept secret; never commit it.
- **Password hashing**: PBKDF2-HMAC-SHA256 with a per-user random salt and 100 000 iterations; constant-time comparison via `hmac.compare_digest` prevents timing attacks.
- **Refresh token rotation**: each `/refresh` call issues a new token and revokes the previous one. Reuse of an already-revoked refresh token triggers full session revocation.
- **Session revocation**: `/logout` invalidates the session server-side, rendering all tokens for that session unusable immediately.
- **Token types**: access tokens are JWTs with a `typ: "access"` claim — the server rejects any JWT where this claim is missing or wrong. Refresh tokens are opaque random strings (`secrets.token_urlsafe(48)`), not JWTs; they are stored server-side as SHA-256 hashes and are only valid at `/refresh`.
- **Admin protection**: the default admin account cannot be deactivated through the API.
- **Prototype scope**: backend services do not independently verify tokens — in production, a reverse proxy (nginx, Traefik, Envoy) would enforce this boundary. Do not expose backend ports directly in a real deployment.
