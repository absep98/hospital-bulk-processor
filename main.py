from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Optional
import csv
import io
import httpx
import asyncio
import uuid
import time
import os


BASE = "https://hospital-directory.onrender.com"
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "10"))


class Hospital(BaseModel):
    name: str
    address: str
    phone: Optional[str] = None

app = FastAPI()  # the application object


@app.get("/")
def read_root():
    return {"message": "hello"}  # so it converts dict to the json auto

@app.post("/echo")
def echo_hospital(hospital: Hospital):
    return {"hospital_name": hospital.name, "hospital_address": hospital.address, "hospital_phone": hospital.phone}

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    content =  await file.read()
    text = content.decode("utf-8")
    return {"filename": file.filename, "size": len(content)}


async def parse_csv(file: UploadFile) -> list:
    try:
        content = await file.read()
        text = content.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        fieldNames = reader.fieldnames
        if not fieldNames:
            raise HTTPException(status_code = 400, detail="CSV file is empty")
        if 'name' not in fieldNames or 'address' not in fieldNames:
            raise HTTPException(status_code = 400, detail="failed to get all fields")
        if len(rows) > 20:
            raise HTTPException(status_code = 400, detail="got more than 20 rows")
        return rows
    except UnicodeDecodeError:
        raise HTTPException(status_code = 400, detail="File is not valid UTF-8 text")
    

@app.post("/csv-preview")
async def viewing_csv_data(file: UploadFile = File(...)):
    rows = await parse_csv(file)
    return {"total_rows": len(rows), "rows": rows}


async def create_one(client, row_number, row, batch_id):

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


@app.post("/hospitals/bulk")
async def bulk_create(file: UploadFile = File(...)):
    start =  time.perf_counter()
    rows = await parse_csv(file)
    batch_id = str(uuid.uuid4())


    sem = asyncio.Semaphore(MAX_CONCURRENT)
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # for number, row in enumerate(rows, start = 1):
        #     results.append(await create_one(client, number, row, batch_id))

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
            # PATCH BASE + f"/hospitals/batch/{batch_id}/activate"
            # if it returns 200, set batch_activated = True
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