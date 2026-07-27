#!/usr/bin/env python3
"""Offline smoke tests for the cadence engine."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cadence_engine as eng


def main() -> None:
    assert eng.ENGINE_API_VERSION == "tracker-v3-merge-csv-only"

    state = eng.normalise_state({})
    assert state == {"cadences": {}, "contacts": [], "log": []}

    cadence = eng.DEFAULT_CADENCE
    contact = {
        "name": "Brandon Ellis",
        "email": "brandon879@hotmail.co.uk",
        "company": "Brandon Email Test",
        "status": "active",
        "step": 0,
        "last_sent": None,
    }
    assert eng.contact_due(contact, cadence)

    contact["step"] = 1
    contact["last_sent"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert not eng.contact_due(contact, cadence)
    contact["last_sent"] = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    assert eng.contact_due(contact, cadence)

    contact["tailored_steps"] = [
        {"subject": "One", "body": "Brandon,\n\nTest one."},
        {"subject": "Two", "body": "Brandon,\n\nTest two."},
        {"subject": "Three", "body": "Brandon,\n\nTest three."},
    ]
    assert eng.has_tailored_sequence(contact, cadence)

    subject, body = eng.build_email(contact, contact["tailored_steps"][0])
    assert subject == "One"
    assert body.endswith("Best,")
    assert "Brandon Ellis" not in body
    assert "\nLumon" not in body
    assert "no thanks" in body

    # --- bulk reply flagging ---
    assert eng.extract_addresses("sarah@a.co.uk") == ["sarah@a.co.uk"]
    assert eng.extract_addresses("Tom Wright <T.Wright@B.com>;  x@c.io") == [
        "t.wright@b.com",
        "x@c.io",
    ]
    assert eng.extract_addresses("dupe@a.com\ndupe@a.com") == ["dupe@a.com"]
    assert eng.extract_addresses("nothing here") == []

    outlook_csv = 'Subject,"From: (Address)",Received\nRe: FX,SARAH@a.co.uk,01/01/2026\n'
    assert eng.extract_addresses_from_csv(outlook_csv) == ["sarah@a.co.uk"]

    headerless = "no,useful,headers\nrow,tom@b.com,thing\n"
    assert eng.extract_addresses_from_csv(headerless) == ["tom@b.com"]

    bom_csv = "\ufeffEmail\nkate@c.com\n"
    assert eng.extract_addresses_from_csv(bom_csv.encode("utf-8")) == ["kate@c.com"]

    bulk_state = {
        "cadences": {},
        "contacts": [
            {"name": "Sarah", "email": "sarah@a.co.uk", "company": "A", "status": "active", "step": 1},
            {"name": "Colleague", "email": "mike@a.co.uk", "company": "A", "status": "active", "step": 1},
            {"name": "Done", "email": "done@b.com", "company": "B", "status": "replied", "step": 2},
        ],
        "log": [],
    }
    report = eng.bulk_mark_replied(
        bulk_state, ["SARAH@a.co.uk", "done@b.com", "ghost@nowhere.com"]
    )
    assert report["flagged"] == ["sarah@a.co.uk"], report
    assert report["already"] == ["done@b.com"], report
    assert report["not_found"] == ["ghost@nowhere.com"], report

    by_email = {c["email"]: c for c in bulk_state["contacts"]}
    assert by_email["sarah@a.co.uk"]["status"] == "replied"
    # flagging one person must not stop their colleague
    assert by_email["mike@a.co.uk"]["status"] == "active"

    # a flagged contact is no longer due, so cannot reach a merge CSV
    assert not eng.contact_due(by_email["sarah@a.co.uk"], cadence)

    assert not hasattr(eng, "smtp_send"), "SMTP path should be gone"

    print("Smoke tests passed.")


if __name__ == "__main__":
    main()
