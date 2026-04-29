# Proxy-Service 

FastAPI implementation for the Auth portion of the project:
- Centralized authentication service
- Two internal backend services to place behind a reverse proxy
- Token validation endpoint for proxy integration

## Architecture

- `auth_service`: user authentication and token verification
- `backend_service_a`: general service for authenticated users
- `backend_service_b`: sensitive service intended for admin-only access

In final deployment, clients should reach only the reverse proxy.
The proxy calls `auth_service` to verify tokens and enforces RBAC before forwarding to backend services.

## Project Structure

```text
Proxy-Service/
|-- auth_service/
|   |-- main.py
|-- backend_service_a/
|   |-- main.py
|-- backend_service_b/
|   |-- main.py
|-- .env.example
|-- .gitignore
|-- requirements.txt
`-- README.md
```

## Prerequisites

- Python 3.10+
- pip

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` from `.env.example` and set a strong `JWT_SECRET` (required).

## Run Services

Run each service in its own terminal from project root.

### 1) Auth Service

```bash
uvicorn auth_service.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2) Backend Service A

```bash
uvicorn backend_service_a.main:app --host 0.0.0.0 --port 8001 --reload
```

### 3) Backend Service B

```bash
uvicorn backend_service_b.main:app --host 0.0.0.0 --port 8002 --reload
```

## Seed Users

The auth service auto-creates demo users on first startup:

- `alice` / `alice123` -> role `user`
- `bob` / `bob123` -> role `admin`

## API Contracts

### Auth Service (`http://localhost:8000`)

- `GET /health` -> service health
- `POST /login` -> get JWT
- `GET /verify` -> validate JWT and return claims (for proxy use)
- `POST /logout` -> stateless logout acknowledgement

#### Example Login

```bash
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"alice\",\"password\":\"alice123\"}"
```

Response:

```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "expires_in": 1800,
  "role": "user"
}
```

#### Example Verify

```bash
curl http://localhost:8000/verify \
  -H "Authorization: Bearer <JWT>"
```

### Backend Service A (`http://localhost:8001`)

- `GET /health`
- `GET /data`

### Backend Service B (`http://localhost:8002`)

- `GET /health`
- `GET /admin-data`

## Proxy Integration Guidance (for Vance)

1. Proxy receives client request to protected route.
2. Proxy extracts bearer token.
3. Proxy calls `GET /verify` on auth service with same bearer token.
4. If `valid=true`, proxy reads `role` from response.
5. Proxy enforces route policy:
   - role `user`: allow service A only
   - role `admin`: allow service A and B
6. Proxy forwards request to target backend only when policy allows.

## Demo Test Checklist

- Unauthenticated request to protected backend route is denied by proxy.
- `alice` can access service A but is denied service B.
- `bob` can access both services.
- Direct access to backend services is blocked by network rules in final topology.

## Security Notes

- `JWT_SECRET` is required and loaded from `.env`.
- JWT logout is stateless in this prototype (token blacklisting not implemented).
- This repo provides service-side components; enforce backend isolation via network/firewall and reverse proxy policy.
# Proxy-Service (Shruti Scope)

FastAPI implementation for the Backend and Auth portion of the project:
- Centralized authentication service
- Two internal backend services to place behind a reverse proxy
- Token validation endpoint for proxy integration

## Architecture

- `auth_service`: user authentication and token verification
- `backend_service_a`: general service for authenticated users
- `backend_service_b`: sensitive service intended for admin-only access

In final deployment, clients should reach only the reverse proxy.  
The proxy calls `auth_service` to verify tokens and enforces RBAC before forwarding to backend services.

## Project Structure

```text
Proxy-Service/
|-- auth_service/
|   |-- main.py
|-- backend_service_a/
|   |-- main.py
|-- backend_service_b/
|   |-- main.py
|-- .env.example
|-- .gitignore
|-- requirements.txt
`-- README.md
```

## Prerequisites

- Python 3.10+
- pip

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` from `.env.example` and set a strong `JWT_SECRET` (required).

## Run Services

Run each service in its own terminal from project root.

### 1) Auth Service

```bash
uvicorn auth_service.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2) Backend Service A

```bash
uvicorn backend_service_a.main:app --host 0.0.0.0 --port 8001 --reload
```

### 3) Backend Service B

```bash
uvicorn backend_service_b.main:app --host 0.0.0.0 --port 8002 --reload
```

## Seed Users

The auth service auto-creates demo users on first startup:

- `alice` / `alice123` -> role `user`
- `bob` / `bob123` -> role `admin`

## API Contracts

### Auth Service (`http://localhost:8000`)

- `GET /health` -> service health
- `POST /login` -> get JWT
- `GET /verify` -> validate JWT and return claims (for proxy use)
- `POST /logout` -> stateless logout acknowledgement

#### Example Login

```bash
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"alice\",\"password\":\"alice123\"}"
```

Response:

```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "expires_in": 1800,
  "role": "user"
}
```

#### Example Verify

```bash
curl http://localhost:8000/verify \
  -H "Authorization: Bearer <JWT>"
```

### Backend Service A (`http://localhost:8001`)

- `GET /health`
- `GET /data`

### Backend Service B (`http://localhost:8002`)

- `GET /health`
- `GET /admin-data`

## Proxy Integration Guidance (for Vance)

1. Proxy receives client request to protected route.
2. Proxy extracts bearer token.
3. Proxy calls `GET /verify` on auth service with same bearer token.
4. If `valid=true`, proxy reads `role` from response.
5. Proxy enforces route policy:
   - role `user`: allow service A only
   - role `admin`: allow service A and B
6. Proxy forwards request to target backend only when policy allows.

## Demo Test Checklist

- Unauthenticated request to protected backend route is denied by proxy.
- `alice` can access service A but is denied service B.
- `bob` can access both services.
- Direct access to backend services is blocked by network rules in final topology.

## Security Notes

- `JWT_SECRET` is required and loaded from `.env`.
- JWT logout is stateless in this prototype (token blacklisting not implemented).
- This repo provides service-side components; enforce backend isolation via network/firewall and reverse proxy policy.
