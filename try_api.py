import asyncio, uuid
import httpx

BASE = "https://hospital-directory.onrender.com"

async def main():
    batch_id = "79a298e7-6893-49ea-8eeb-33bcabc36872"
    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = {
            "name": "aks host",                 # your test hospital name, a string
            "address": "new jersey",
            "phone": "555-1234",
            "creation_batch_id": batch_id,    # which variable holds the batch ID?
        }

        # response = await client.post(
        #     BASE + "/hospitals/",
        #     json=payload,
        # )
        # print(response.status_code)
        # print(response.json())

        # response = await client.get(BASE + f"/hospitals/batch/{batch_id}")
        # print(response.status_code)
        # print(response.json())

        # response = await client.patch(BASE + f"/hospitals/batch/{batch_id}/activate")
        # print(response.status_code)
        # print(response.json())

        # response = await client.get(BASE + f"/hospitals/batch/{batch_id}")
        # print(response.status_code)
        # print(response.json())

        response = await client.delete(BASE + f"/hospitals/batch/{batch_id}")
        print(response.status_code)
        print(response.json())

        response = await client.get(BASE + f"/hospitals/batch/{batch_id}")
        print(response.status_code)
        print(response.json())

asyncio.run(main())
