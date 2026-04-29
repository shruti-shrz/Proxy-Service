# Proxy-Service

Centralized authentication and role-based access control (RBAC) reverse proxy prototype using FastAPI and Docker Compose.

## Purpose

This project demonstrates how to protect internal web services using a centralized reverse proxy. Users must authenticate before accessing backend services, and access is restricted based on role. The backend services themselves do not implement authentication or authorization logic; all enforcement happens at the proxy.

The prototype demonstrates:

- unauthenticated users are redirected to login
- authenticated users can access only routes permitted by their role
- backend services are reachable only through the reverse proxy
- sessions are maintained using secure browser cookies
- logout revokes the current auth session

---

## Architecture

```text
Browser
  │
  ▼
Reverse Proxy :8080
  │
  ├── calls /login, /verify, /refresh, /logout
  │
  ▼
Auth Service :8000
  │
  ├── SQLite DB
  ├── users
  ├── sessions
  └── refresh tokens

Reverse Proxy
  │
  ├── /app/*   ─────▶ Backend Service A :8001
  │                  any authenticated user
  │
  └── /admin/* ─────▶ Backend Service B :8002
                     admin only
```

Only the reverse proxy is exposed to the host machine:

```text
http://localhost:8080
```

The auth service and backend services are private Docker services and are not directly reachable from the host.

---

## High-Level Flow

1. User visits a protected route such as `/app/data`.
2. Reverse proxy checks for an access token cookie.
3. If no valid token exists, the user is redirected to `/login`.
4. User submits username/password to the proxy login page.
5. Proxy calls the auth service `/login` endpoint.
6. Auth service returns an access token and refresh token.
7. Proxy stores tokens in `HttpOnly` cookies.
8. On future requests, the proxy validates the access token using `/verify`.
9. Proxy applies RBAC policy.
10. If allowed, the request is forwarded to the correct backend service.

---

## Project Structure

```text
Proxy-Service/
├── auth_service/
│   └── main.py              # Auth service: login, register, verify, refresh, sessions
├── backend_service_a/
│   └── main.py              # General backend, available to authenticated users
├── backend_service_b/
│   └── main.py              # Admin backend, available to admins only
├── reverse_proxy/
│   └── main.py              # Login page, session cookies, RBAC, request forwarding
├── AUTH_API.md              # Auth service API documentation
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── .env                     # Local config, not committed
└── README.md
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.10+ / 3.11 |
| Web framework | FastAPI |
| ASGI server | Uvicorn |
| Reverse proxy logic | FastAPI + HTTPX |
| Authentication | JWT access tokens |
| Session continuation | Refresh tokens |
| Database | SQLite |
| Password hashing | PBKDF2-HMAC-SHA256 |
| Containerization | Docker Compose |

---

## Services

| Service | Internal Address | Host Access | Description |
|---|---|---:|---|
| Reverse Proxy | `reverse_proxy:8080` | `localhost:8080` | Main entry point |
| Auth Service | `auth_service:8000` | Not exposed | Issues/verifies tokens |
| Backend A | `backend_a:8001` | Not exposed | General user service |
| Backend B | `backend_b:8002` | Not exposed | Admin service |

---

## Route Policy

| External Route | Internal Destination | Required Role |
|---|---|---|
| `/app/data` | `backend_a:8001/data` | `user` or `admin` |
| `/admin/admin-data` | `backend_b:8002/admin-data` | `admin` only |

The reverse proxy removes the first path segment before forwarding.

Example:

```text
/app/data
```

forwards to:

```text
backend_a:8001/data
```

And:

```text
/admin/admin-data
```

forwards to:

```text
backend_b:8002/admin-data
```

---

## Prerequisites

- Docker Desktop
- Docker Compose
- Optional for non-Docker development:
  - Python 3.10+
  - `pip`

---

## Environment Setup

Copy the example environment file:

```bash
cp .env.example .env
```

Minimum `.env`:

```env
JWT_SECRET=replace-with-strong-random-secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
AUTH_DB_PATH=auth.db
PBKDF2_ITERATIONS=100000
```

Generate a strong JWT secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Replace `JWT_SECRET` in `.env` with the generated value.

---

## Running with Docker

Start all services:

```bash
docker compose up --build
```

After startup, open:

```text
http://localhost:8080
```

Stop all containers:

```bash
docker compose down
```

Stop containers and reset the auth database volume:

```bash
docker compose down -v
```

---

## Seed Accounts

On first startup, the auth service auto-creates:

| Username | Password | Role |
|---|---|---|
| `alice` | `alice123` | `user` |
| `bob` | `bob123` | `admin` |

The default admin account `bob` cannot be deactivated through the API.

---

## Demo / Test Workflow

### 1. Open the proxy homepage

```text
http://localhost:8080
```

The page shows:

- current login status
- current username and role, if logged in
- available protected routes
- test users

---

### 2. Unauthenticated user is redirected to login

In a browser or private window, visit:

```text
http://localhost:8080/app/data
```

Expected result:

```text
redirected to /login
```

---

### 3. Alice can access the general service

Login as:

```text
alice / alice123
```

Then visit:

```text
http://localhost:8080/app/data
```

Expected response:

```json
{
  "service": "service-a",
  "message": "General internal data. Intended for authenticated users."
}
```

---

### 4. Alice cannot access the admin service

While logged in as Alice, visit:

```text
http://localhost:8080/admin/admin-data
```

Expected result:

```text
403 Forbidden
```

Alice has role `user`, but `/admin/*` requires role `admin`.

---

### 5. Bob can access the admin service

Logout:

```text
http://localhost:8080/logout
```

Login as:

```text
bob / bob123
```

Then visit:

```text
http://localhost:8080/admin/admin-data
```

Expected response:

```json
{
  "service": "service-b",
  "message": "Sensitive admin data. Intended for admins only."
}
```

---

### 6. Backend services are not directly reachable

Try accessing backend services directly from the host:

```text
http://localhost:8001/data
http://localhost:8002/admin-data
```

Expected result:

```text
connection refused / unable to connect
```

This demonstrates that backend services are isolated and can only be reached through the reverse proxy.

---

## Login and Session Behavior

The reverse proxy hosts a small login page at:

```text
http://localhost:8080/login
```

After successful login, the proxy stores:

```text
access_token
refresh_token
```

as `HttpOnly` cookies.

Future browser requests automatically include these cookies. The proxy uses the access token to call:

```text
GET auth_service:8000/verify
```

If the access token expires, the proxy attempts to use the refresh token by calling:

```text
POST auth_service:8000/refresh
```

If refresh succeeds, new cookies are issued. If refresh fails, the user is redirected to login.

The login page also detects if the user is already logged in. Logging in as a different account will revoke the previous session and replace the cookies with the new account session.

---

## Logout

Visit:

```text
http://localhost:8080/logout
```

The reverse proxy calls the auth service `/logout` endpoint and clears local cookies.

After logout, protected routes require login again.

---

## Auth Service API

The auth service is internal to Docker during normal operation, but its API is documented in:

```text
AUTH_API.md
```

Main endpoints:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/register` | Register user |
| `POST` | `/login` | Login and receive tokens |
| `GET` | `/verify` | Validate access token |
| `POST` | `/refresh` | Rotate refresh token and issue new access token |
| `GET` | `/me` | Current user profile |
| `POST` | `/change-password` | Change own password |
| `POST` | `/logout` | Revoke current session |
| `GET` | `/users` | Admin: list users |
| `PATCH` | `/users/{username}/deactivate` | Admin: deactivate user |

---

## Backend APIs

Backend services are not exposed directly to the host in the Docker setup.

They are reachable only through the reverse proxy.

### Service A

External route:

```text
http://localhost:8080/app/data
```

Internal route:

```text
backend_a:8001/data
```

Required role:

```text
user or admin
```

---

### Service B

External route:

```text
http://localhost:8080/admin/admin-data
```

Internal route:

```text
backend_b:8002/admin-data
```

Required role:

```text
admin
```

---

## Identity Propagation

When the proxy forwards an allowed request, it includes identity headers for the backend:

```http
X-Forwarded-User: alice
X-Forwarded-User-Id: 1
X-Forwarded-Role: user
X-Forwarded-Session-Id: <session-id>
```

Backends may read these headers for display or logging, but authorization decisions are enforced by the reverse proxy.

These headers should only be trusted because the backend services are isolated and cannot be accessed directly by users.

---

## Running Without Docker

Docker Compose is the recommended setup because it demonstrates backend isolation.

For development only, you can run each service manually in separate terminals:

```bash
uvicorn auth_service.main:app --host 0.0.0.0 --port 8000 --reload
uvicorn backend_service_a.main:app --host 0.0.0.0 --port 8001 --reload
uvicorn backend_service_b.main:app --host 0.0.0.0 --port 8002 --reload
uvicorn reverse_proxy.main:app --host 0.0.0.0 --port 8080 --reload
```

When running locally this way, backend ports are exposed on your machine, so this mode does not demonstrate backend isolation.

---

## Security Notes

- This is a prototype for demonstrating centralized authentication and RBAC.
- Do not commit `.env` or real secrets.
- `JWT_SECRET` must be strong and private.
- Access tokens are short-lived JWTs.
- Refresh tokens are opaque random tokens stored server-side as hashes.
- Refresh token rotation is implemented.
- Reuse of an old refresh token revokes the session.
- Logout revokes the server-side session.
- Backend applications do not verify tokens themselves.
- Backend services must remain private and reachable only from the reverse proxy.
- Cookies use `HttpOnly` and `SameSite=Lax`.
- For a real deployment, use HTTPS and set cookie `Secure=True`.

---

## Troubleshooting

### Port already in use

Check what is using a port:

```bash
lsof -i :8080
```

Stop the process or change the exposed port in `docker-compose.yml`.

---

### Reset database

If users or sessions are in a bad state, reset the Docker volume:

```bash
docker compose down -v
docker compose up --build
```

---

### Rebuild after code changes

```bash
docker compose up --build
```

---

### Backend is reachable directly

If this works:

```text
http://localhost:8001/data
```

then the backend is being exposed incorrectly.

Check `docker-compose.yml` and make sure backend services use:

```yaml
expose:
  - "8001"
```

not:

```yaml
ports:
  - "8001:8001"
```

Only the reverse proxy should have a `ports:` mapping.