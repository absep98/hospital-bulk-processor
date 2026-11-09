# Learning Log

A running record of mistakes, fixes and lessons while building the Paribus Hospital Bulk Processing assignment.
Format: what went wrong, why, how to fix, and how to spot it next time.

---

## Session 1: FastAPI basics, Pydantic, CSV upload

### 1. Wrong import for `Optional`
- **Code:** `from pydantic import BaseModel, typing`
- **Problem:** `Optional` comes from Python's standard `typing` module, not from `pydantic`. Importing `typing` from pydantic doesn't bring `Optional` into scope, so `Optional[str]` raises `NameError`.
- **Fix:** `from typing import Optional`
- **Lesson:** An IDE auto-import can pick the wrong module. When a name is "undefined", check where it really lives.

### 2. `Optional[str]` without a default makes the field required (Pydantic v2)
- **Code:** `phone: Optional[str]`
- **Problem:** In Pydantic v2, `Optional[str]` only means "may be None". The field is still required, so a request that omits `phone` gets a 422 error. The CSV rule says phone is optional.
- **Fix:** `phone: Optional[str] = None`
- **Lesson:** "Can be None" and "can be omitted" are different. The `= None` default is what makes a field omittable.

### 3. `HTTPException` used but never imported
- **Code:** `HTTPException(...)` with only `FastAPI, UploadFile, File` imported.
- **Fix:** `from fastapi import FastAPI, UploadFile, File, HTTPException`

### 4. `return HTTPException(...)` instead of `raise`
- **Problem:** `return` sends the exception object back as a normal 200 response. It does not trigger an error response.
- **Fix:** `raise HTTPException(status_code=400, detail="...")`
- **Lesson:** Errors are raised, results are returned.

### 5. Empty `if` body is a SyntaxError
- **Code:** `if len(fieldNames) == 3:` followed directly by `except:`
- **Problem:** Python needs at least one statement in a block (use `pass` as a placeholder). This stops the whole app from starting, so none of the routes work.
- **Lesson:** If the server won't start, read the traceback at the bottom first. It names the file and line.

### 6. Wrong validation logic: `len(fieldnames) == 3`
- **Problem:** `phone` is optional, so a valid CSV with only `name,address` has 2 headers and would be rejected. Header count also doesn't prove the names are correct.
- **Fix idea:** Check that the required names are present: `{"name", "address"}` is a subset of the header set.
- **Lesson:** Validate the thing you care about (required names), not a proxy for it (count).

### 7. `fieldnames` can be `None`
- **Problem:** For an empty file, `reader.fieldnames` is `None`, and `len(None)` raises `TypeError`.
- **Fix idea:** Check `if not reader.fieldnames` and raise a 400 with a clear message.

### 8. Bare `except:` hides real errors
- **Problem:** A bare `except:` catches everything, including typos and bugs, so you lose the real error message.
- **Fix idea:** Catch specific exceptions (like `UnicodeDecodeError`) around the line that can fail, and use explicit `if` checks for validation.

### 9. Naming: `fieldNames`
- Python convention is `snake_case` for variables: `field_names`.

---

## Session 2: validating `/csv-preview`, starting httpx

Fixed since session 1: `Optional` import, `phone = None` default, snake_case echo keys, `try/except UnicodeDecodeError` added, 20-row check added.

### 10. `HTTPException` is still not imported
- **Problem:** The import line has `FastAPI, UploadFile, File` only. Once the code reaches `HTTPException`, it raises `NameError`.
- **Fix:** add `HTTPException` to the `from fastapi import ...` line.

### 11. Still `return HTTPException(...)` (same as #4)
- **Problem:** Returns a 200 response with a weird body instead of a real 400 error. All four places need `raise`.
- **Lesson:** Repeated mistake. Rule: **errors are raised, results are returned.**

### 12. `len(fieldNames) is None` can never be true
- **Problem:** `len()` returns an int, and an int is never `None`. Also, if `fieldnames` is `None` (empty file), `len(None)` crashes before the comparison happens.
- **Fix:** test the thing itself: `if not field_names:`
- **Lesson:** Check for `None` before calling anything on the value.

### 13. `fieldNames.name` treats a list like an object
- **Problem:** `reader.fieldnames` is a plain list of strings, like `["name", "address", "phone"]`. Attribute access (`.name`) raises `AttributeError`.
- **Fix:** membership test: `"name" not in field_names` (or a set check: `{"name", "address"} <= set(field_names)`).
- **Lesson:** Print the value (`print(field_names)`) to see what type you really have.

### 14. Stray `asyncio def main():` at the bottom
- **Problem:** `asyncio def` is invalid syntax, so the whole file fails to import. The right form is `async def main():`. Also, scratch code for calling the external API belongs in a separate file (`try_api.py`), not in `main.py`.
- **Lesson:** The server can't start with a SyntaxError. Read the traceback bottom-up.

### 15. Conceptual: what `await` blocks
- **Misunderstanding:** "httpx is used for sequential requests and blocks until the response comes back."
- **Reality:** httpx does both sequential and concurrent. `await` pauses only your own function; the server keeps serving other requests. Sequential vs concurrent is decided by how you write the calls (`await` in a loop vs `asyncio.gather`).

### 16. `uvicorn.exe` blocked by Windows Application Control
- **Error:** `An Application Control policy has blocked this file`
- **Cause:** the `.exe` launcher in `venv\Scripts` is unsigned and blocked by policy. Python itself is allowed.
- **Fix:** `python -m uvicorn main:app --reload` (same for `pytest`, `pip`, etc.)

### 17. Typo `reader.fieldNames` (capital N) caused a 500
- **Problem:** Python is case-sensitive. The real attribute is `fieldnames`. Result: `AttributeError` and a bare 500 "Internal Server Error" in `/docs`.
- **Lesson:** A 500 hides details from the client. **The real traceback is in the uvicorn terminal.** Read it bottom-up.

### 18. Test results for `/csv-preview` (Nov 9)
| File | Result |
|---|---|
| hospitals.csv | 200, 5 rows (OK) |
| bad_header.csv | 400 "failed to get all fields" (OK) |
| empty.csv | 400 "failed to get all data" (OK) |
| too_many_rows.csv | 400 "got more than 20 rows" (OK) |

All 4 cases pass. `/csv-preview` is done.

- **Observation:** a missing phone comes back as `""` (empty string), not `None`. Decide how to treat this before sending to the hospital API.

### 19. 422 from the hospital API: wrong types in payload
- **Code:** `"phone": 1222233` and `"creation_batch_id": 1234`
- **Error:** `422`, `loc: ['body','phone']` "Input should be a valid string"; `loc: ['body','creation_batch_id']` "UUID input should be a string".
- **Fix:** phone must be a string (`"555-1234"`); batch ID must be the UUID variable (`batch_id`), not a made-up number.
- **How to read a 422:** `loc` = which field, `msg` = what is wrong, `input` = the value you sent.
- **Lesson:** APIs validate types strictly. Identifiers like phone numbers are strings.

### 20. Hospital API behaviour learned from try_api.py (Nov 9)
- `POST /hospitals/` returns **200** (not 201), body has `id`, `active: False`.
- `GET /hospitals/batch/{id}` returns a **list** of hospital dicts.
- `PATCH .../activate` returns `{'activated_count': N, 'message': ...}`. After it, GET shows `active: True`.
- `DELETE /hospitals/batch/{id}` returns `{'deleted_count': N, ...}`.
- GET on a deleted or unknown batch returns **404** `{'detail': 'No hospitals found with the specified batch ID'}`. The body is a dict, not a list, so check the status code before treating it as a list.
- Test data left on the shared server: batches `cf7ae14c-bb02-478d-ad70-b28fd0d9a552` (id 1331) and `28385106-efb4-41da-a1cd-0743c26b947e` (id 1332). Clean up with DELETE.

### 21. `await` missing on an async helper
- **Code:** `rows = parse_csv(file)` where `parse_csv` is `async def`.
- **Problem:** without `await` the function never runs; you get a coroutine object and `len(rows)` crashes.
- **Fixed:** `rows = await parse_csv(file)`.

### 22. `File(...)` belongs on routes, not helpers
- `File(...)` tells FastAPI where to find a parameter in the request. `...` (Ellipsis) means "required". A helper called by your own code gets a plain `file: UploadFile`.

### 23. Leaving `...` placeholders in real code
- `...` is a real value (Ellipsis), not "fill in later". It cannot be sent as JSON.

### 24. `row["phone"]` instead of `row.get("phone") or None`
- `row["phone"]` raises `KeyError` if the column is missing, and sends `""` for a blank phone. Use `.get` plus `or None`.

### 25. Wrong exception type for the wrong layer
- Raising `HTTPException` inside `create_one` is not caught by `except httpx.HTTPError`, so it would abort the whole bulk request instead of failing one row. Validate once up front (`parse_csv`), not per row.

### 26. Exception objects are not JSON
- `"error": exec` can't be serialised; use `str(exc)`. Also don't name a variable `exec` (a Python built-in); use `exc`.

### 27. Empty `except` body (repeat of #5)
- A block needs at least one statement. Use `pass` as a placeholder, or better, write the real handling.

### 28. `await` inside a list comprehension is still sequential
- **Code:** `[await asyncio.gather(create_one(...)) for ...]`
- **Problem:** each `await` finishes before the next row starts, so no speedup. Each `gather` also returns a one-item list, so `r["status"]` fails.
- **Rule:** build all coroutines first (no `await`), then `await gather(...)` **once**.

### 29. `gather(tasks)` vs `gather(*tasks)`
- **Error:** `TypeError: cannot use 'list' as a dict key (unhashable type: 'list')`
- **Cause:** passing the list as one argument. `*tasks` unpacks it into separate arguments.
- **Debug skill:** in a traceback, find the line that points at your own file, then read the last line.

### 30. Performance result (Nov 9)
- Sequential, 5 rows: **27.48 s**. Concurrent (`gather`), 5 rows: **7.18 s** (about 3.8x faster).
- `gather` keeps results in input order even though the server assigned hospital ids out of order (1340, 1344, 1342, 1341, 1343).

### 31. Semaphore experiment, 20 rows (Nov 9)
| MAX_CONCURRENT | Time | Failed |
|---|---|---|
| 5 | 22.14 s | 0 |
| 20 | 6.47 s | 0 |
| 1 | not run (predicted about 110 s) | |

- Each call takes about 5.5 s on the hospital server. Time is roughly (number of waves) x 5.5 s: 20 rows / 5 slots = 4 waves = 22 s; 20 rows / 20 slots = 1 wave = 5.5 s (measured 6.47 s).
- Sequential 5 rows: 27.48 s. Concurrent 5 rows: 7.18 s / 6.28 s.
- At 20 concurrent the server handled the load with 0 failures (single sample, free tier).

---

## Open items (not yet done)
- [ ] Row limit check: more than 20 rows returns 400
- [ ] Handle non-UTF-8 / non-text uploads (`UnicodeDecodeError`)
- [ ] Validate per-row: missing `name` or `address`
- [ ] Learn `httpx` and async calls to the hospital API
