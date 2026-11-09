from fastapi.testclient import TestClient
from main import app, BASE
import httpx, respx
client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"service": "hospital-bulk-processor", "status": "ok", "docs": "/docs"}

def test_preview_ok():
    csv_text = "name,address,phone\nA,1 St,555\n"
    response = client.post("/csv-preview", files={"file": ("h.csv", csv_text, "text/csv")})
    body = response.json()
    assert response.status_code == 200
    assert body["total_rows"] == 1
    assert body["rows"][0]["name"] == "A"

def test_preview_empty_file():
    response = client.post("/csv-preview", files={"file": ("e.csv", "", "text/csv")})
    assert response.status_code == 400
    assert response.json()["detail"] == "CSV file is empty"

def test_preview_bad_header():
    csv_text = "title,addr\nA,1 St\n"
    response = client.post("/csv-preview", files={"file": ("e.csv", csv_text, "text/csv")})
    body = response.json()
    assert response.status_code == 400
    assert body["detail"] == "failed to get all fields"

def test_preview_too_many_rows():
    rows = "\n".join(f"H{i},{i} St,555" for i in range(21))
    csv_text = "name,address,phone\n" + rows
    response = client.post("/csv-preview", files={"file": ("e.csv", csv_text, "text/csv")})
    assert response.status_code == 400
    assert response.json()["detail"] == "got more than 20 rows"

def test_preview_not_utf8():
    response = client.post("/csv-preview",  files={"file": ("b.csv", b"\xff\xfe\x00", "text/csv")})
    assert response.status_code == 400
    assert response.json()["detail"] == "File is not valid UTF-8 text"


@respx.mock
def test_bulk_happy_path():
    post_route = respx.post(BASE + "/hospitals/").mock(
        return_value=httpx.Response(200, json={'id': 1})
    )

    patch_route = respx.patch(url__regex=r".*/hospitals/batch/.+/activate").mock(
        return_value=httpx.Response(200, json={"activated_count": 3})
    )
    csv_text = "name,address,phone\nA,1 St,555\nB,2 St,556\nC,3 St,557\n"
    response = client.post("/hospitals/bulk", files={"file": ("h.csv", csv_text, "text/csv")})
    body = response.json()

    assert response.status_code == 200
    assert body["total_hospitals"] == 3
    assert body["processed_hospitals"] == 3
    assert body["failed_hospitals"] == 0
    assert body["batch_activated"] is True
    for h in body["hospitals"]:
        assert h["status"] == "created_and_activated"
    assert post_route.call_count == 3
    assert patch_route.call_count == 1


@respx.mock
def test_bulk_all_rows_fail():
    post_route = respx.post(BASE + "/hospitals/").mock(
        return_value=httpx.Response(500)
    )
    patch_route = respx.patch(url__regex=r".*/hospitals/batch/.+/activate").mock(
        return_value=httpx.Response(200, json={"activated_count": 0})
    )
    csv_text = "name,address,phone\nA,1 St,555\nB,2 St,556\nC,3 St,557\n"
    response = client.post("/hospitals/bulk", files={"file": ("h.csv", csv_text, "text/csv")})
    body = response.json()

    assert response.status_code == 200
    assert body["total_hospitals"] == 3
    assert body["processed_hospitals"] == 0
    assert body["failed_hospitals"] == 3
    assert body["batch_activated"] is False
    for h in body["hospitals"]:
        assert h["status"] == "failed"
        assert h["hospital_id"] is None
    assert post_route.call_count == 3
    # the design rule: a batch with failures must never be activated
    assert patch_route.called is False


@respx.mock
def test_bulk_activation_fails():
    respx.post(BASE + "/hospitals/").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    patch_route = respx.patch(url__regex=r".*/hospitals/batch/.+/activate").mock(
        return_value=httpx.Response(500)
    )
    csv_text = "name,address,phone\nA,1 St,555\nB,2 St,556\nC,3 St,557\n"
    response = client.post("/hospitals/bulk", files={"file": ("h.csv", csv_text, "text/csv")})
    body = response.json()

    assert response.status_code == 200
    assert body["failed_hospitals"] == 0
    assert body["batch_activated"] is False
    assert body["activation_error"] is not None
    # rows were created but never activated, so they keep the plain "created" status
    for h in body["hospitals"]:
        assert h["status"] == "created"
    assert patch_route.call_count == 1