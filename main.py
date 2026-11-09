from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import csv
import io
import httpx
import asyncio
import uuid
import time
import os


BASE = "https://hospital-directory.onrender.com"
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "10"))


app = FastAPI(title="Hospital Bulk Processor")


class PreviewResult(BaseModel):
    total_rows: int
    rows: List[dict]


class HospitalResult(BaseModel):
    row: int
    hospital_id: Optional[int] = None
    name: Optional[str] = None
    status: str  # "created", "created_and_activated" or "failed"
    error: Optional[str] = None


class BulkResult(BaseModel):
    batch_id: str
    total_hospitals: int
    processed_hospitals: int
    failed_hospitals: int
    processing_time_seconds: float
    batch_activated: bool
    hospitals: List[HospitalResult]
    activation_error: Optional[str] = None


@app.get("/")
def read_root():
    return {"service": "hospital-bulk-processor", "status": "ok", "docs": "/docs"}


async def parse_csv(file: UploadFile) -> list:
    """Read and validate an uploaded CSV; return its rows as dicts or raise a 400."""
    try:
        content = await file.read()
        text = content.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        field_names = reader.fieldnames
        if not field_names:
            raise HTTPException(status_code = 400, detail="CSV file is empty")
        if 'name' not in field_names or 'address' not in field_names:
            raise HTTPException(status_code = 400, detail="failed to get all fields")
        if not rows:
            raise HTTPException(status_code = 400, detail="CSV has no data rows")
        if len(rows) > 20:
            raise HTTPException(status_code = 400, detail="got more than 20 rows")
        return rows
    except UnicodeDecodeError:
        raise HTTPException(status_code = 400, detail="File is not valid UTF-8 text")


@app.post("/csv-preview", response_model=PreviewResult)
async def viewing_csv_data(file: UploadFile = File(...)):
    rows = await parse_csv(file)
    return {"total_rows": len(rows), "rows": rows}


async def create_one(client, row_number, row, batch_id):
    """Create one hospital in the batch; return a result dict, never raise on API failure."""
    if not (row.get("name") or "").strip() or not (row.get("address") or "").strip():
        return {"row": row_number, "hospital_id": None, "name": row.get("name") or "",
                "status": "failed", "error": "name and address are required"}

    payload = {
        "name": row["name"],
        "address": row["address"],
        "phone": row.get("phone") or None,
        "creation_batch_id": batch_id,
    }

    try:
        response = await client.post(BASE + "/hospitals/", json=payload)
        response.raise_for_status()
        data = response.json()
        return {"row": row_number, "hospital_id": data["id"], "name": row["name"], "status": "created"}
    except httpx.HTTPError as exc:
        return {"row": row_number, "hospital_id": None, "name": row["name"], "status": "failed", "error": str(exc)}


@app.post("/hospitals/bulk", response_model=BulkResult)
async def bulk_create(file: UploadFile = File(...)):
    """Create every CSV row as one batch, concurrently, and activate it only if all rows succeeded."""
    start =  time.perf_counter()
    rows = await parse_csv(file)
    batch_id = str(uuid.uuid4())
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async with httpx.AsyncClient(timeout=60.0) as client:

        async def limited(n, row):
            async with sem:
                return await create_one(client, n, row, batch_id)

        tasks = [limited(n, row) for n, row in enumerate(rows, start=1)]
        results = list(await asyncio.gather(*tasks))
        failed = [r for r in results if r["status"] == "failed"]
        failed_count = len(failed)
        batch_activated = False
        activation_error = None
        if failed_count == 0:

            try:
                response = await client.patch(BASE + f"/hospitals/batch/{batch_id}/activate")
                response.raise_for_status()
                batch_activated = True
            
            except httpx.HTTPError as exc:
                activation_error = str(exc)

        if batch_activated:
            for r in results:
                if r["status"] == "created":
                    r["status"] = "created_and_activated"
        elapsed = time.perf_counter() - start
        return {
            "batch_id": batch_id,
            "total_hospitals": len(rows),
            "processed_hospitals": len(rows) - failed_count,
            "failed_hospitals": failed_count,
            "processing_time_seconds": round(elapsed, 2),
            "batch_activated": batch_activated,
            "hospitals": results,
            "activation_error": activation_error,
        }