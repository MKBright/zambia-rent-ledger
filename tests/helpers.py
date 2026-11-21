import re


def csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    if match is None:
        raise AssertionError("No CSRF token on the page")
    return match.group(1)


def csrf(client) -> str:
    response = client.get("/login")
    html = response.get_data(as_text=True)
    if response.status_code != 200 or "csrf_token" not in html:
        response = client.get("/")
        html = response.get_data(as_text=True)
    return csrf_token(html)


def register(client, email="amina@example.com", password="password123", name="Amina Banda"):
    page = client.get("/register")
    token = csrf_token(page.get_data(as_text=True))
    response = client.post(
        "/register",
        data={
            "name": name,
            "email": email,
            "phone": "0971234567",
            "password": password,
            "confirm": password,
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    return response


def logout(client):
    token = csrf(client)
    return client.post("/logout", data={"csrf_token": token}, follow_redirects=True)
