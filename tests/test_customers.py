"""Customer sign-up: one account per email, and the ZIP code must be in the chosen delivery area."""
def sign_up(client, email="asha@example.com", destination="SJC", zip_code="95112"):
    return client.post("/customers", json={"email": email, "full_name": "Asha Rao",
                                           "destination": destination, "zip": zip_code})


def test_sign_up_and_fetch(client):
    r = sign_up(client)
    assert r.status_code == 201
    c = r.json()
    assert (c["destination"], c["zip"]) == ("SJC", "95112")
    assert client.get(f"/customers/{c['customer_id']}").json()["email"] == "asha@example.com"


def test_email_is_unique_regardless_of_case(client):
    sign_up(client, email="ravi@example.com", destination="DEN", zip_code="80202")
    assert sign_up(client, email="Ravi@Example.com", destination="DEN", zip_code="80202").status_code == 409


def test_zip_must_be_in_the_delivery_area(client):
    r = sign_up(client, email="kiran@example.com", destination="DEN", zip_code="95112")   # San Jose ZIP, Denver
    assert r.status_code == 422 and "outside the DEN delivery area" in r.json()["detail"]
    assert sign_up(client, email="kiran@example.com", destination="DEN", zip_code="80014").status_code == 201


def test_bad_input(client):
    assert sign_up(client, email="x@example.com", destination="NYC").status_code == 400
    assert sign_up(client, email="x@example.com", zip_code="9511").status_code == 422
    assert sign_up(client, email="not-an-email").status_code == 422
    assert client.get("/customers/9999").status_code == 404
