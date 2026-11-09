from fastapi.testclient import TestClient
from main import app, BASE
import json
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

def test_preview_header_only():
    response = client.post("/csv-preview", files={"file": ("h.csv", "name,address,phone\n", "text/csv")})
    assert response.status_code == 400
    assert response.json()["detail"] == "CSV has no data rows"

@respx.mock
def test_bulk_header_only_makes_no_api_calls():
    post_route = respx.post(BASE + "/hospitals/").mock(return_value=httpx.Response(200, json={"id": 1}))
    patch_route = respx.patch(url__regex=r".*/hospitals/batch/.+/activate").mock(
        return_value=httpx.Response(200, json={"activated_count": 0})
    )
    response = client.post("/hospitals/bulk", files={"file": ("h.csv", "name,address,phone\n", "text/csv")})
    assert response.status_code == 400
    assert post_route.called is False
    assert patch_route.called is False


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


@respx.mock
def test_bulk_partial_failure():
    # Requests run concurrently, so arrival order is not guaranteed.
    # Decide success or failure from the hospital named in the request body, not from call order.
    def create_or_fail(request):
        name = json.loads(request.content)["name"]
        if name == "B":
            return httpx.Response(500)
        return httpx.Response(200, json={"id": ord(name)})

    post_route = respx.post(BASE + "/hospitals/").mock(side_effect=create_or_fail)
    patch_route = respx.patch(url__regex=r".*/hospitals/batch/.+/activate").mock(
        return_value=httpx.Response(200, json={"activated_count": 2})
    )
    csv_text = "name,address,phone\nA,1 St,555\nB,2 St,556\nC,3 St,557\n"
    response = client.post("/hospitals/bulk", files={"file": ("h.csv", csv_text, "text/csv")})
    body = response.json()

    assert response.status_code == 200
    assert body["total_hospitals"] == 3
    assert body["processed_hospitals"] == 2
    assert body["failed_hospitals"] == 1
    assert body["batch_activated"] is False
    by_name = {h["name"]: h for h in body["hospitals"]}
    assert by_name["B"]["status"] == "failed"
    assert by_name["B"]["hospital_id"] is None
    assert by_name["B"]["error"] is not None
    # the successful rows stay "created" (not activated) because one row failed
    assert by_name["A"]["status"] == "created"
    assert by_name["C"]["status"] == "created"
    # rows keep their CSV order in the response
    assert [h["row"] for h in body["hospitals"]] == [1, 2, 3]
    assert post_route.call_count == 3
    assert patch_route.called is False


@respx.mock
def test_bulk_blank_name_or_address_fails_without_api_call():
    post_route = respx.post(BASE + "/hospitals/").mock(return_value=httpx.Response(200, json={"id": 1}))
    patch_route = respx.patch(url__regex=r".*/hospitals/batch/.+/activate").mock(
        return_value=httpx.Response(200, json={"activated_count": 1})
    )
    # row 1 is valid, row 2 has a blank address, row 3 has a name of only spaces
    csv_text = "name,address,phone\nA,1 St,555\nB,,556\n   ,3 St,557\n"
    response = client.post("/hospitals/bulk", files={"file": ("h.csv", csv_text, "text/csv")})
    body = response.json()

    assert response.status_code == 200
    assert body["failed_hospitals"] == 2
    assert body["processed_hospitals"] == 1
    assert body["batch_activated"] is False
    by_row = {h["row"]: h for h in body["hospitals"]}
    assert by_row[1]["status"] == "created"
    for row in (2, 3):
        assert by_row[row]["status"] == "failed"
        assert by_row[row]["error"] == "name and address are required"
    # only the valid row reached the Directory API, and the batch was not activated
    assert post_route.call_count == 1
    assert patch_route.called is False