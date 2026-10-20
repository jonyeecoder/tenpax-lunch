"""Smoke test of the whole lunch-run flow. Run with: python test_app.py"""
import os
import re
import tempfile

os.environ["TEAM_CODE"] = "test-code"
os.environ["DATABASE"] = os.path.join(tempfile.mkdtemp(), "test.db")

from app import MAX_USERS, app  # noqa: E402

app.config["TESTING"] = True


def signup(client, name):
    return client.post("/signup", data={"team_code": "test-code", "username": name, "password": "secret1"},
                       follow_redirects=True)


def main():
    alice, bob, eve = app.test_client(), app.test_client(), app.test_client()

    assert b"Wrong team code" in eve.post("/signup", data={"team_code": "nope", "username": "eve", "password": "secret1"}).data
    assert eve.get("/").status_code == 302, "logged-out users are redirected to login"

    assert b"Start a lunch run" in signup(alice, "alice").data
    signup(bob, "bob")

    page = alice.post("/runs", data={"place": "Chicken rice stall", "cutoff": "11:30"}, follow_redirects=True)
    run_url = re.search(rb'action="(/runs/\d+)/order"', page.data).group(1).decode()

    alice.post(run_url + "/order", data={"item": "Roast chicken rice", "price": "5.50"})
    bob.post(run_url + "/order", data={"item": "Steamed chicken rice", "price": "6"})
    bob.post(run_url + "/order", data={"item": "Steamed chicken rice, extra egg", "price": "6.80"})

    page = alice.get(run_url).data
    assert b"extra egg" in page and b"$12.30" in page, "edits replace the old order and total adds up"

    order_ids = re.findall(rb'action="/orders/(\d+)/paid"', page)
    assert len(order_ids) == 2, "organizer can mark each order paid"
    assert bob.post(f"/orders/{order_ids[0].decode()}/paid").status_code == 403, "only the organizer marks paid"
    alice.post(f"/orders/{order_ids[0].decode()}/paid")
    assert b"$6.80 owed" in alice.get(run_url).data or b"$5.50 owed" in alice.get(run_url).data

    alice.post(run_url + "/close")
    bob.post(run_url + "/order", data={"item": "Sneaky late order", "price": "1"})
    assert b"Sneaky" not in alice.get(run_url).data, "closed runs reject new orders"

    for i in range(MAX_USERS - 2):
        signup(app.test_client(), f"user{i}")
    assert b"team is full" in signup(eve, "eve").data, "sign-up stops at 10 people"

    print("All checks passed.")


if __name__ == "__main__":
    main()
