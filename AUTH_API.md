# Auth Service API Documentation

Base URL: `http://localhost:8000`

All endpoints that require a token expect it in the `Authorization` header as:
```
Authorization: Bearer <access_token>
```

---

## Table of Contents

1. [Health Check](#1-health-check)
2. [Register](#2-register)
3. [Login](#3-login)
4. [Verify Token](#4-verify-token)
5. [Refresh Token](#5-refresh-token)
6. [Get Current User](#6-get-current-user)
7. [Change Password](#7-change-password)
8. [Logout](#8-logout)
9. [List All Users](#9-list-all-users) _(admin)_
10. [Deactivate User](#10-deactivate-user) _(admin)_

---

## 1. Health Check

Check if the auth service is running.

```
GET /health
```

**Auth required:** No

**Sample request**
```bash
curl http://localhost:8000/health
```

**Sample response** `200 OK`
```json
{
  "status": "ok",
  "service": "auth-service"
}
```

---

## 2. Register

Create a new user account.

```
POST /register
```

**Auth required:** No

**Request body**

| Field      | Type   | Required | Constraints            |
|------------|--------|----------|------------------------|
| `username` | string | Yes      | 3–50 characters        |
| `password` | string | Yes      | 8–128 characters       |
| `role`     | string | No       | `user` or `admin`, defaults to `user` |

**Sample request**
```bash
curl -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{"username": "charlie", "password": "charlie123", "role": "user"}'
```

**Sample response** `201 Created`
```json
{
  "id": 3,
  "username": "charlie",
  "role": "user",
  "is_active": true
}
```

**Error responses**

| Status | Reason |
|--------|--------|
| `400`  | Invalid role value |
| `409`  | Username already exists |

---

## 3. Login

Authenticate and receive an access token and a refresh token.

```
POST /login
```

**Auth required:** Username + password in request body

**Request body**

| Field      | Type   | Required |
|------------|--------|----------|
| `username` | string | Yes      |
| `password` | string | Yes      |

**Sample request**
```bash
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "alice123"}'
```

**Sample response** `200 OK`
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "dGhpcyBpcyBhIHNhbXBsZSByZWZyZXNoIHRva2Vu...",
  "token_type": "bearer",
  "expires_in": 1800,
  "refresh_expires_in": 604800,
  "role": "user"
}
```

> `expires_in` and `refresh_expires_in` are in **seconds**.
> `1800` = 30 minutes (access token), `604800` = 7 days (refresh token).

**Error responses**

| Status | Reason |
|--------|--------|
| `401`  | Invalid username or password |
| `403`  | Account is deactivated |

---

## 4. Verify Token

Validate an access token and return its claims. Used by a reverse proxy to authenticate requests before forwarding.

```
GET /verify
```

**Auth required:** `Authorization: Bearer <access_token>`

**Sample request**
```bash
curl http://localhost:8000/verify \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Sample response** `200 OK`
```json
{
  "valid": true,
  "user_id": "1",
  "username": "alice",
  "role": "user",
  "session_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "exp": 1714000000
}
```

> `user_id` is returned as a string. `exp` is a Unix timestamp.

**Error responses**

| Status | Reason |
|--------|--------|
| `401`  | Missing, expired, or invalid token |
| `401`  | Session has been revoked |

---

## 5. Refresh Token

Exchange a valid refresh token for a new access token and a new refresh token. The old refresh token is immediately revoked.

```
POST /refresh
```

**Auth required:** Refresh token in request body (not in the `Authorization` header)

**Request body**

| Field           | Type   | Required |
|-----------------|--------|----------|
| `refresh_token` | string | Yes      |

**Sample request**
```bash
curl -X POST http://localhost:8000/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "dGhpcyBpcyBhIHNhbXBsZSByZWZyZXNoIHRva2Vu..."}'
```

**Sample response** `200 OK`
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "bmV3IHJlZnJlc2ggdG9rZW4gZ2VuZXJhdGVk...",
  "token_type": "bearer",
  "expires_in": 1800,
  "refresh_expires_in": 604800,
  "role": "user"
}
```

> **Token rotation:** each call returns a brand new refresh token. Using an already-used refresh token triggers immediate revocation of the entire session.

**Error responses**

| Status | Reason |
|--------|--------|
| `401`  | Invalid or expired refresh token |
| `401`  | Refresh token reuse detected — session revoked |
| `401`  | Session has been revoked |
| `403`  | Account is deactivated |

---

## 6. Get Current User

Return the profile of the currently authenticated user.

```
GET /me
```

**Auth required:** `Authorization: Bearer <access_token>`

**Sample request**
```bash
curl http://localhost:8000/me \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Sample response** `200 OK`
```json
{
  "id": 1,
  "username": "alice",
  "role": "user",
  "is_active": true
}
```

**Error responses**

| Status | Reason |
|--------|--------|
| `401`  | Missing, expired, or invalid token |
| `404`  | User not found |

---

## 7. Change Password

Change the password of the currently authenticated user. Requires the current password to confirm identity.

```
POST /change-password
```

**Auth required:** `Authorization: Bearer <access_token>`

**Request body**

| Field              | Type   | Required | Constraints      |
|--------------------|--------|----------|------------------|
| `current_password` | string | Yes      | 8–128 characters |
| `new_password`     | string | Yes      | 8–128 characters |

**Sample request**
```bash
curl -X POST http://localhost:8000/change-password \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{"current_password": "alice123", "new_password": "newsecure99"}'
```

**Sample response** `200 OK`
```json
{
  "message": "Password updated successfully"
}
```

**Error responses**

| Status | Reason |
|--------|--------|
| `401`  | Missing or invalid access token |
| `401`  | Current password is incorrect |
| `404`  | User not found |

---

## 8. Logout

Revoke the current session. Both the access token and all refresh tokens tied to this session are immediately invalidated.

```
POST /logout
```

**Auth required:** `Authorization: Bearer <access_token>`

**Sample request**
```bash
curl -X POST http://localhost:8000/logout \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Sample response** `200 OK`
```json
{
  "message": "Session revoked successfully"
}
```

**Error responses**

| Status | Reason |
|--------|--------|
| `401`  | Missing, expired, or invalid token |

---

## 9. List All Users

Return a list of all registered users. Admin only.

```
GET /users
```

**Auth required:** `Authorization: Bearer <admin_access_token>`

**Sample request**
```bash
curl http://localhost:8000/users \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Sample response** `200 OK`
```json
[
  {
    "id": 1,
    "username": "alice",
    "role": "user",
    "is_active": true
  },
  {
    "id": 2,
    "username": "bob",
    "role": "admin",
    "is_active": true
  },
  {
    "id": 3,
    "username": "charlie",
    "role": "user",
    "is_active": false
  }
]
```

**Error responses**

| Status | Reason |
|--------|--------|
| `401`  | Missing, expired, or invalid token |
| `403`  | Authenticated user is not an admin |

---

## 10. Deactivate User

Deactivate a user account by username. Deactivated users cannot log in. Admin only. The default admin (`bob`) cannot be deactivated.

```
PATCH /users/{username}/deactivate
```

**Auth required:** `Authorization: Bearer <admin_access_token>`

**Path parameter**

| Parameter  | Type   | Description              |
|------------|--------|--------------------------|
| `username` | string | Username to deactivate   |

**Sample request**
```bash
curl -X PATCH http://localhost:8000/users/charlie/deactivate \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Sample response** `200 OK`
```json
{
  "message": "User 'charlie' deactivated"
}
```

**Error responses**

| Status | Reason |
|--------|--------|
| `400`  | Cannot deactivate the default admin (`bob`) |
| `401`  | Missing, expired, or invalid token |
| `403`  | Authenticated user is not an admin |
| `404`  | Username not found |

---

## Common Workflow

```
1. POST /login          → get access_token + refresh_token
2. GET  /verify         → validate access_token (done by proxy)
3. POST /refresh        → get new tokens when access_token expires
4. POST /logout         → revoke session when done
```
