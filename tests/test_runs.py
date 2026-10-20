from datetime import datetime

import pytest
from conftest import SGT, page, post


def order(client, run_url, item="Roast chicken rice", price="5.50"):
    return post(client, run_url + "/order", item=item, price=price)


def orders(db):
    return {row["item"]: dict(row) for row in db("SELECT * FROM orders")}


# --- Starting a run ---------------------------------------------------------


def test_start_a_run(alice, run_url):
    text = page(alice, run_url)
    assert "Chicken rice stall · Tenpax Lunch" in text
    assert "order by 11:30" in text
    assert "Chicken rice stall" in page(alice, "/")


@pytest.mark.parametrize(
    ("form", "message"),
    [
        ({"place": "  "}, "Where are we ordering from?"),
        ({"place": "x" * 101}, "Where are we ordering from?"),  # issue #13
        ({"place": "Stall", "cutoff": "banana"}, "HH:MM"),  # issue #3
    ],
)
def test_start_run_validation(alice, db, form, message):
    resp = post(alice, "/runs", **form)
    assert resp.headers["Location"] == "/"
    assert message in page(alice, "/")
    assert db("SELECT * FROM runs") == []


def test_cutoff_is_stored_as_hh_mm(alice, db):
    post(alice, "/runs", place="Stall", cutoff="11:30:00")
    assert db("SELECT cutoff FROM runs")[0]["cutoff"] == "11:30"


def test_cutoff_is_optional(alice, db):
    post(alice, "/runs", place="Stall", cutoff="")
    assert db("SELECT cutoff FROM runs")[0]["cutoff"] is None


def test_today_uses_the_team_timezone(alice, db, clock):
    # Issue #5: 07:00 in Singapore is still the previous day in UTC.
    clock.now = datetime(2026, 10, 21, 7, 0, tzinfo=SGT)
    post(alice, "/runs", place="Breakfast run")
    assert db("SELECT day FROM runs")[0]["day"] == "2026-10-21"
    text = page(alice, "/")
    assert "Wed 21 Oct" in text
    assert "Breakfast run" in text


def test_index_only_lists_todays_runs(alice, run_url, clock):
    clock.now = datetime(2026, 10, 21, 10, 0, tzinfo=SGT)
    assert "No lunch runs yet today." in page(alice, "/")


def test_unknown_run_is_404(alice):
    assert alice.get("/runs/999").status_code == 404


# --- Ordering ---------------------------------------------------------------


def test_add_and_change_an_order(bob, run_url, db):
    order(bob, run_url, "Rice", "5")
    order(bob, run_url, "Rice, extra egg", "5.80")
    assert list(orders(db)) == ["Rice, extra egg"]
    text = page(bob, run_url)
    assert "Change your order" in text
    assert 'value="5.80"' in text  # issue #19: the dollars filter
    assert "$5.80 owed" in text


@pytest.mark.parametrize(
    ("item", "price"),
    [
        ("", "5"),
        ("x" * 101, "5"),
        ("Rice", "abc"),
        ("Rice", "-1"),
        ("Rice", "inf"),
        ("Rice", "1e300"),
    ],
)
def test_bad_orders_are_rejected(bob, run_url, db, item, price):
    # Issues #2 and #13
    resp = order(bob, run_url, item, price)
    assert resp.status_code == 302
    assert "Enter what you want" in page(bob, run_url)
    assert orders(db) == {}


def test_remove_an_order(bob, run_url, db):
    order(bob, run_url)
    post(bob, run_url + "/order/delete")
    assert orders(db) == {}


def test_changing_the_price_resets_paid(alice, bob, run_url, db):
    # Issue #1
    order(bob, run_url, "Rice", "5")
    order_id = orders(db)["Rice"]["id"]
    post(alice, f"/orders/{order_id}/paid", paid="1")
    order(bob, run_url, "Rice + 3 extra dishes", "25")
    assert orders(db)["Rice + 3 extra dishes"]["paid"] == 0
    assert "$25.00 owed" in page(alice, run_url)


def test_changing_only_the_item_keeps_paid(alice, bob, run_url, db):
    order(bob, run_url, "Rice", "5")
    post(alice, f"/orders/{orders(db)['Rice']['id']}/paid", paid="1")
    order(bob, run_url, "Rice, no chilli", "5.00")
    assert orders(db)["Rice, no chilli"]["paid"] == 1


# --- When a run stops taking orders ----------------------------------------


def assert_locked(client, run_url, db, before):
    order(client, run_url, "Late order", "1")
    post(client, run_url + "/order/delete")
    assert orders(db) == before
    assert "Your order" not in page(client, run_url)


def test_closed_run_rejects_changes(alice, bob, run_url, db):
    order(bob, run_url)
    before = orders(db)
    post(alice, run_url + "/closed", closed="1")
    assert_locked(bob, run_url, db, before)
    assert ">closed<" in page(bob, run_url)


def test_cutoff_is_enforced(bob, run_url, db, clock):
    # Issue #3
    order(bob, run_url)
    before = orders(db)
    clock.now = datetime(2026, 10, 20, 11, 31, tzinfo=SGT)
    assert_locked(bob, run_url, db, before)
    assert "past cutoff" in page(bob, run_url)


def test_order_at_the_cutoff_minute_is_accepted(bob, run_url, db, clock):
    clock.now = datetime(2026, 10, 20, 11, 30, tzinfo=SGT)
    order(bob, run_url)
    assert len(orders(db)) == 1


def test_runs_from_earlier_days_reject_changes(bob, run_url, db, clock):
    # Issue #4
    order(bob, run_url)
    before = orders(db)
    clock.now = datetime(2026, 10, 21, 9, 0, tzinfo=SGT)
    assert_locked(bob, run_url, db, before)
    assert "ended" in page(bob, run_url)


def test_closing_twice_stays_closed(alice, run_url, db):
    # Issue #6: a double-submit used to reopen the run.
    post(alice, run_url + "/closed", closed="1")
    post(alice, run_url + "/closed", closed="1")
    assert db("SELECT closed FROM runs")[0]["closed"] == 1
    assert "Reopen orders" in page(alice, run_url)
    post(alice, run_url + "/closed", closed="0")
    assert db("SELECT closed FROM runs")[0]["closed"] == 0


def test_only_the_organizer_can_close(bob, run_url):
    assert post(bob, run_url + "/closed", closed="1").status_code == 403


# --- Paid tracking ----------------------------------------------------------


def test_marking_paid_twice_stays_paid(alice, bob, run_url, db):
    # Issue #6
    order(bob, run_url)
    order_id = orders(db)["Roast chicken rice"]["id"]
    post(alice, f"/orders/{order_id}/paid", paid="1")
    post(alice, f"/orders/{order_id}/paid", paid="1")
    assert orders(db)["Roast chicken rice"]["paid"] == 1
    assert "$0.00 owed" in page(alice, run_url)
    post(alice, f"/orders/{order_id}/paid", paid="0")
    assert orders(db)["Roast chicken rice"]["paid"] == 0


def test_only_the_organizer_can_mark_paid(bob, run_url, db):
    order(bob, run_url)
    order_id = orders(db)["Roast chicken rice"]["id"]
    assert post(bob, f"/orders/{order_id}/paid", paid="1").status_code == 403
    assert "<button" not in page(bob, run_url).split("<tbody>")[1].split("</tbody>")[0]


def test_unknown_order_is_404(alice):
    assert post(alice, "/orders/999/paid", paid="1").status_code == 404


# --- The whole flow ---------------------------------------------------------


def test_lunch_run_end_to_end(alice, bob, user, run_url, db):
    carol = user("carol")
    order(alice, run_url, "Roast chicken rice", "5.50")
    order(bob, run_url, "Steamed chicken rice", "5")
    order(carol, run_url, "Char siew rice", "6.80")
    assert "$17.30" in page(alice, run_url)

    post(alice, f"/orders/{orders(db)['Char siew rice']['id']}/paid", paid="1")
    post(alice, run_url + "/closed", closed="1")

    text = page(bob, run_url)
    assert "$17.30" in text
    assert "$10.50 owed" in text
    assert "1 order" not in page(alice, "/")
    assert "3 orders" in page(alice, "/")
