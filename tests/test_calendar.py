from test_entries import add_entry, as_user, setup  # noqa: F401  (setup is a fixture)

OCTOBER = "/entries/calendar-feed?start=2026-09-27T00:00:00%2B08:00&end=2026-11-08T00:00:00%2B08:00"


def ids(response):
    return [event["extendedProps"]["publicId"] for event in response.get_json()]


def test_calendar_page_renders(setup):
    page = setup.get("/").data
    assert b'id="calendar"' in page and b"fullcalendar" in page


def test_feed_returns_events_in_range(setup):
    add_entry(setup, date="2026-10-05", time="14:30", type="meeting")
    add_entry(setup, date="2026-10-20", time="", type="exam", subject_code="MATH1")
    add_entry(setup, date="2026-12-01")  # outside the range
    events = setup.get(OCTOBER).get_json()
    assert [e["extendedProps"]["publicId"] for e in events] == ["E-00001", "E-00002"]

    meeting, exam = events
    assert meeting["start"] == "2026-10-05T14:30" and meeting["allDay"] is False
    assert meeting["title"] == "CS101 · Cycle Meeting" and meeting["url"] == "/entries/1"
    assert meeting["color"] == "#0d6efd"
    assert exam["start"] == "2026-10-20" and exam["allDay"] is True


def test_feed_only_shows_enrolled_subjects_to_users(setup):
    add_entry(setup, date="2026-10-05", subject_code="CS101")
    add_entry(setup, date="2026-10-06", subject_code="MATH1")
    assert ids(setup.get(OCTOBER)) == ["E-00001", "E-00002"]  # admin sees all
    assert ids(as_user(setup, "juan").get(OCTOBER)) == ["E-00001"]


def test_feed_filters(setup):
    add_entry(setup, date="2026-10-05", type="meeting")
    add_entry(setup, date="2026-10-06", type="task", subject_code="MATH1")
    add_entry(setup, date="2026-10-07", type="exam")
    setup.post("/entries/3/delete", data={"reason": "cancelled"})

    assert ids(setup.get(OCTOBER + "&subject=MATH1")) == ["E-00002"]
    assert ids(setup.get(OCTOBER + "&types=meeting,exam")) == ["E-00001", "E-00003"]
    assert ids(setup.get(OCTOBER + "&types=")) == []
    assert ids(setup.get(OCTOBER + "&deleted=0")) == ["E-00001", "E-00002"]

    deleted = setup.get(OCTOBER).get_json()[2]
    assert deleted["classNames"] == ["entry-deleted"] and deleted["extendedProps"]["deleted"] is True


def test_feed_rejects_bad_dates(setup):
    assert setup.get("/entries/calendar-feed").status_code == 400
    assert setup.get("/entries/calendar-feed?start=nope&end=2026-11-01").status_code == 400


def test_feed_requires_login(client):
    assert client.get(OCTOBER).status_code == 302


def test_add_entry_prefills_clicked_date(setup):
    assert b'value="2026-10-15"' in setup.get("/entries/new?date=2026-10-15").data
