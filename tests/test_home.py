from classtracker import create_app


def test_home_page_loads():
    client = create_app().test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert b"ClassTracker" in response.data
