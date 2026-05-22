"""Load POGS scores and the ground-truth overall grade from the Excel
in blob storage.

The Excel serves two purposes:
  - POGS score: a pipeline input (POGS is not on the scanned form)
  - Final Overall Grade: the Access-generated outcome, used to validate
    the agent's generated overall grade.
"""

import io
import os
import pandas as pd
from dotenv import load_dotenv
from src.blob_reader import _get_blob_service

load_dotenv()


def _read_excel_bytes_from_blob() -> bytes:
    """Download the first .xlsx file in the data container."""
    container = os.getenv("AZURE_CONTAINER_DATA", "data")
    service = _get_blob_service()
    blobs = list(service.get_container_client(container).list_blobs())
    xlsx_blobs = [b for b in blobs if b.name.lower().endswith(".xlsx")]
    if not xlsx_blobs:
        raise RuntimeError(f"No .xlsx file in container '{container}'")
    blob_name = xlsx_blobs[0].name
    return service.get_blob_client(
        container=container, blob=blob_name
    ).download_blob().readall()


def read_students(limit: int | None = None) -> list[dict]:
    """Return a list of student dicts: POGS input + ground-truth overall grade.

    Each dict:
      student_id   - join key to match against extracted forms
      pogs_score   - pipeline input
      _truth       - {Final_Overall_Grade} from Access (for validation)
    """
    excel_bytes = _read_excel_bytes_from_blob()
    df = pd.read_excel(io.BytesIO(excel_bytes))

    if limit:
        df = df.head(limit)

    def safe_int(val, default=0):
        try:
            return int(val) if pd.notna(val) else default
        except (ValueError, TypeError):
            return default

    def safe_str(val):
        return str(val).strip() if pd.notna(val) else ""

    students = []
    for _, row in df.iterrows():
        student = {
            "student_id": safe_str(row.get("student id", row.get("ID", ""))),
            "pogs_score": safe_int(row.get("POGS_No")),
            "_truth": {
                "Final_Overall_Grade": safe_str(
                    row.get("Final Overall Grade for Run")
                ),
            },
        }
        students.append(student)

    return students


if __name__ == "__main__":
    import json
    students = read_students(limit=5)
    print(f"Loaded {len(students)} students.\n")
    for s in students:
        print(json.dumps(s, indent=2))
        print()