import os
from urllib.parse import quote
from html import escape

import httpx
from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response


app = FastAPI(title="Reverse Proxy", version="1.0.0")


AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth_service:8000")
BACKEND_A_URL = os.getenv("BACKEND_A_URL", "http://backend_a:8001")
BACKEND_B_URL = os.getenv("BACKEND_B_URL", "http://backend_b:8002")


# Path prefix -> backend URL
BACKENDS = {
    "app": BACKEND_A_URL,
    "admin": BACKEND_B_URL,
}


# Path prefix -> allowed roles
# /app allows both normal users and admins.
# /admin allows only admins.
RBAC_POLICIES = {
    "app": {"user", "admin"},
    "admin": {"admin"},
}


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "cookie",
}


def login_page_html(next_url: str = "/", claims: dict | None = None) -> str:
    already_logged_in_notice = ""

    if claims:
        username = escape(str(claims.get("username", "unknown")))
        role = escape(str(claims.get("role", "unknown")))

        already_logged_in_notice = f"""
        <div style="
          max-width: 500px;
          padding: 1rem;
          margin-bottom: 1rem;
          border: 1px solid #ff9800;
          border-radius: 8px;
          background: #fff3e0;
        ">
          <strong>You are currently logged in as:</strong><br>
          User: <code>{username}</code><br>
          Role: <code>{role}</code>
          <p>
            Logging in as another account will log out the current session
            and replace it with the new account.
          </p>
        </div>
        """

    safe_next = escape(next_url, quote=True)

    return f"""
    <!doctype html>
    <html>
      <head>
        <title>Internal Login</title>
        <style>
          body {{
            font-family: Arial, sans-serif;
            margin: 3rem;
          }}
          form {{
            max-width: 350px;
            padding: 1.5rem;
            border: 1px solid #ccc;
            border-radius: 8px;
          }}
          input {{
            width: 100%;
            padding: 0.5rem;
            margin: 0.5rem 0;
          }}
          button {{
            padding: 0.5rem 1rem;
          }}
          code {{
            background: #eee;
            padding: 0.1rem 0.25rem;
            border-radius: 4px;
          }}
        </style>
      </head>
      <body>
        <h1>Internal Services Login</h1>

        {already_logged_in_notice}

        <form method="post" action="/login" autocomplete="off">
            <input type="hidden" name="next" value="{safe_next}" autocomplete="off" />

            <label for="login_user_input">Username</label>
            <input
                id="login_user_input"
                name="login_user_input"
                type="text"
                required
                autocomplete="off"
                autocapitalize="none"
                autocorrect="off"
                spellcheck="false"
            />

            <label for="login_pass_input">Password</label>
            <input
                id="login_pass_input"
                name="login_pass_input"
                type="password"
                required
                autocomplete="new-password"
                autocapitalize="none"
                autocorrect="off"
                spellcheck="false"
            />

            <button type="submit">Login</button>
        </form>

        <p>Seed users:</p>
        <ul>
          <li><code>alice / alice123</code> - role: user</li>
          <li><code>bob / bob123</code> - role: admin</li>
        </ul>

        <p><a href="/">Back to home</a></p>
      </body>
    </html>
    """


def set_auth_cookies(response: Response, token_response: dict) -> None:
    access_token = token_response["access_token"]
    refresh_token = token_response["refresh_token"]

    access_max_age = int(token_response.get("expires_in", 1800))
    refresh_max_age = int(token_response.get("refresh_expires_in", 604800))

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=False,  # local HTTP demo only; use True with HTTPS
        max_age=access_max_age,
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=False,  # local HTTP demo only; use True with HTTPS
        max_age=refresh_max_age,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")


async def verify_access_token(client: httpx.AsyncClient, access_token: str) -> dict | None:
    verify_response = await client.get(
        f"{AUTH_SERVICE_URL}/verify",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    if verify_response.status_code == 200:
        return verify_response.json()

    return None


async def refresh_tokens(client: httpx.AsyncClient, refresh_token: str) -> dict | None:
    refresh_response = await client.post(
        f"{AUTH_SERVICE_URL}/refresh",
        json={"refresh_token": refresh_token},
    )

    if refresh_response.status_code == 200:
        return refresh_response.json()

    return None


async def authenticate_request(request: Request) -> tuple[dict | None, dict | None]:
    """
    Returns:
      claims, new_token_response

    claims:
      Identity claims from auth_service /verify.

    new_token_response:
      Only set if access token was expired and refresh succeeded.
      Caller should set updated cookies on the final response.
    """

    access_token = request.cookies.get("access_token")
    refresh_token = request.cookies.get("refresh_token")

    # Also allow curl/API clients to use Authorization: Bearer directly.
    auth_header = request.headers.get("authorization")
    if not access_token and auth_header and auth_header.lower().startswith("bearer "):
        access_token = auth_header.split(" ", 1)[1]

    if not access_token:
        return None, None

    async with httpx.AsyncClient(timeout=10.0) as client:
        claims = await verify_access_token(client, access_token)

        if claims:
            return claims, None

        # If access token failed and browser has refresh token, try refresh.
        if refresh_token:
            new_tokens = await refresh_tokens(client, refresh_token)

            if new_tokens:
                new_claims = await verify_access_token(client, new_tokens["access_token"])

                if new_claims:
                    return new_claims, new_tokens

    return None, None


def redirect_to_login(request: Request) -> RedirectResponse:
    next_url = request.url.path

    if request.url.query:
        next_url += f"?{request.url.query}"

    encoded_next = quote(next_url, safe="")
    return RedirectResponse(url=f"/login?next={encoded_next}", status_code=status.HTTP_303_SEE_OTHER)


def check_rbac(service_name: str, claims: dict) -> None:
    allowed_roles = RBAC_POLICIES.get(service_name)

    if not allowed_roles:
        raise HTTPException(status_code=404, detail="Unknown service")

    user_role = claims.get("role")

    if user_role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user_role}' is not allowed to access /{service_name}",
        )


async def forward_request(
    request: Request,
    backend_base_url: str,
    backend_path: str,
    claims: dict,
) -> Response:
    if backend_path:
        target_url = f"{backend_base_url}/{backend_path}"
    else:
        target_url = f"{backend_base_url}/"

    if request.url.query:
        target_url += f"?{request.url.query}"

    incoming_headers = dict(request.headers)

    forwarded_headers = {
        key: value
        for key, value in incoming_headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }

    # Identity propagation to backend.
    forwarded_headers["X-Forwarded-User"] = claims.get("username", "")
    forwarded_headers["X-Forwarded-User-Id"] = str(claims.get("user_id", ""))
    forwarded_headers["X-Forwarded-Role"] = claims.get("role", "")
    forwarded_headers["X-Forwarded-Session-Id"] = claims.get("session_id", "")

    body = await request.body()

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        backend_response = await client.request(
            method=request.method,
            url=target_url,
            headers=forwarded_headers,
            content=body,
        )

    response_headers = {
        key: value
        for key, value in backend_response.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }

    return Response(
        content=backend_response.content,
        status_code=backend_response.status_code,
        headers=response_headers,
        media_type=backend_response.headers.get("content-type"),
    )

def render_login_status(claims: dict | None) -> str:
    if not claims:
        return """
        <div style="padding: 1rem; border: 1px solid #ccc; border-radius: 8px; background: #f8f8f8;">
          <strong>Status:</strong> Not logged in
        </div>
        """

    username = escape(str(claims.get("username", "unknown")))
    role = escape(str(claims.get("role", "unknown")))
    session_id = escape(str(claims.get("session_id", "")))

    return f"""
    <div style="padding: 1rem; border: 1px solid #4caf50; border-radius: 8px; background: #eefbea;">
      <strong>Status:</strong> Logged in<br>
      <strong>User:</strong> {username}<br>
      <strong>Role:</strong> {role}<br>
      <strong>Session:</strong> <code>{session_id}</code>
    </div>
    """

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    claims, new_tokens = await authenticate_request(request)

    login_status_html = render_login_status(claims)

    if claims:
        username = escape(str(claims.get("username", "unknown")))
        role = escape(str(claims.get("role", "unknown")))

        auth_links = f"""
        <p>
          Logged in as <strong>{username}</strong> with role <strong>{role}</strong>.
        </p>
        <p>
          <a href="/logout">Logout</a> |
          <a href="/login">Switch account</a>
        </p>
        """
    else:
        auth_links = """
        <p>
          <a href="/login">Login</a>
        </p>
        """

    html = f"""
    <!doctype html>
    <html>
      <head>
        <title>Proxy Demo</title>
        <style>
          body {{
            font-family: Arial, sans-serif;
            margin: 3rem;
          }}
          code {{
            background: #eee;
            padding: 0.1rem 0.25rem;
            border-radius: 4px;
          }}
          .card {{
            max-width: 700px;
            padding: 1rem;
            margin: 1rem 0;
            border: 1px solid #ccc;
            border-radius: 8px;
          }}
        </style>
      </head>
      <body>
        <h1>Centralized Auth + RBAC Reverse Proxy</h1>

        {login_status_html}

        <div class="card">
          <h2>Available Routes</h2>
          <ul>
            <li>
              <a href="/app/data">/app/data</a>
              - any authenticated user
            </li>
            <li>
              <a href="/admin/admin-data">/admin/admin-data</a>
              - admin only
            </li>
          </ul>
        </div>

        <div class="card">
          <h2>Authentication</h2>
          {auth_links}
        </div>

        <div class="card">
          <h2>Test Users</h2>
          <ul>
            <li><code>alice / alice123</code> - role: <code>user</code></li>
            <li><code>bob / bob123</code> - role: <code>admin</code></li>
          </ul>
        </div>

        <div class="card">
            <h2>Internal Service Isolation</h2>
            <p>
                These services should <strong>not</strong> be directly accessible from the host.
                They should only be reachable through the reverse proxy at
                <code>http://localhost:8080</code>.
            </p>

            
            <small>Expected: connection refused / unable to connect</small>
            <ul>
                <li>
                Auth Service:
                <a href="http://localhost:8000/health">http://localhost:8000/health</a>
                </li>

                <li>
                Backend Service A:
                <a href="http://localhost:8001/data">http://localhost:8001/data</a>
                </li>

                <li>
                Backend Service B:
                <a href="http://localhost:8002/admin-data">http://localhost:8002/admin-data</a>
                </li>
            </ul>
        </div>
      </body>
    </html>
    """

    response = HTMLResponse(content=html)

    if new_tokens:
        set_auth_cookies(response, new_tokens)

    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "reverse-proxy"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    claims, new_tokens = await authenticate_request(request)

    html = login_page_html(next_url=next, claims=claims)
    response = HTMLResponse(content=html)

    if new_tokens:
        set_auth_cookies(response, new_tokens)

    return response


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(..., alias="login_user_input"),
    password: str = Form(..., alias="login_pass_input"),
    next: str = Form("/"),
):
    existing_access_token = request.cookies.get("access_token")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # If the browser is already logged in, revoke the previous session first.
        if existing_access_token:
            try:
                await client.post(
                    f"{AUTH_SERVICE_URL}/logout",
                    headers={"Authorization": f"Bearer {existing_access_token}"},
                )
            except httpx.HTTPError:
                # Do not block new login just because old logout failed.
                pass

        auth_response = await client.post(
            f"{AUTH_SERVICE_URL}/login",
            json={
                "username": username,
                "password": password,
            },
        )

    if auth_response.status_code != 200:
        response = HTMLResponse(
            content=f"""
            <h1>Login failed</h1>
            <p>Invalid username or password.</p>
            <p><a href="/login?next={quote(next, safe='')}">Try again</a></p>
            <p><a href="/">Back to home</a></p>
            """,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

        # Clear local cookies if login failed after trying to switch accounts.
        clear_auth_cookies(response)
        return response

    token_response = auth_response.json()

    response = RedirectResponse(url=next, status_code=status.HTTP_303_SEE_OTHER)
    set_auth_cookies(response, token_response)
    return response


@app.get("/logout")
async def logout(request: Request):
    access_token = request.cookies.get("access_token")

    if access_token:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{AUTH_SERVICE_URL}/logout",
                headers={"Authorization": f"Bearer {access_token}"},
            )

    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_auth_cookies(response)
    return response


@app.api_route("/{service_name}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/{service_name}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(service_name: str, request: Request, path: str = ""):
    if service_name not in BACKENDS:
        raise HTTPException(status_code=404, detail="Unknown route")

    claims, new_tokens = await authenticate_request(request)

    if not claims:
        return redirect_to_login(request)

    check_rbac(service_name, claims)

    backend_response = await forward_request(
        request=request,
        backend_base_url=BACKENDS[service_name],
        backend_path=path,
        claims=claims,
    )

    if new_tokens:
        set_auth_cookies(backend_response, new_tokens)

    return backend_response