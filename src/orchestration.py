"""Pipeline orchestrator.

Drives the per-student pipeline:

    setup aggregator (once)
    list forms
      -> for each form:
           download -> extract -> build_payload -> score -> aggregate
      -> collect -> write results.json
"""

import json
import logging
from pathlib import Path

from src.logging_config import setup_logging
from src.blob_reader import list_forms, download_blob
from src.excel_reader import read_students
from src.custom_extract import extract_form
from src.payload_builder import build_payload, PayloadError
from src.scoring import score_student
from src.aggregation import setup_aggregator, aggregate_assessment

logger = logging.getLogger(__name__)

RESULTS_PATH = Path(__file__).parent.parent / "output" / "results.json"
FORMS_CONTAINER = "raw-forms"


def _agent_student_block(payload: dict) -> dict:
    """Build the 'student' block passed to the aggregator agent.

    The agent uses these for the rubric (fitness_concern -> escalation) and
    echoes the form-derived values into the structured output for
    transparency (so a reader who never sees the form can see what came in).
    Free-text *comments* are NOT sent (that's Content Safety's job).
    """
    return {
        "student_id": payload["student_id"],
        "csr": payload["csr"],
        "csr_ratings_per_domain": payload["csr_ratings_per_domain"],
        "cat_score": payload["cat_score"],
        "pogs_score": payload["pogs_score"],
        "fitness_concern": payload["fitness_concern"],
        "fitness_concern_reason": payload["fitness_concern_reason"],
    }


def _process_form(form_name: str, students: list[dict],
                  project, agent_name: str) -> dict:
    logger.info("Processing form: %s", form_name)

    form_bytes = download_blob(FORMS_CONTAINER, form_name)
    logger.info("Downloaded %s (%d bytes)", form_name, len(form_bytes))

    extracted = extract_form(form_bytes)
    logger.info("Extracted %d fields from %s", len(extracted), form_name)

    payload = build_payload(extracted, students)
    student_id = payload["student_id"]

    scored = score_student(payload)
    logger.info("Scored student %s", student_id)

    student_block = _agent_student_block(payload)
    final = aggregate_assessment(project, agent_name, scored, student_block)
    logger.info("Aggregated student %s", student_id)

    return {
        "student_id": student_id,
        "source_form": form_name,
        "scored": scored,
        "final": final,
    }


def run_pipeline() -> list[dict]:
    logger.info("=== Pipeline run starting ===")

    try:
        students = read_students()
    except Exception:
        logger.exception("Could not load students from Excel; aborting run")
        raise
    if not students:
        logger.error("No students loaded from Excel; nothing to process")
        return []
    logger.info("Loaded %d students from Excel", len(students))

    try:
        project, agent_name = setup_aggregator()
    except Exception:
        logger.exception("Could not set up aggregator; aborting run")
        raise

    try:
        forms = list_forms()
    except Exception:
        logger.exception("Could not list forms from blob storage; aborting run")
        raise
    if not forms:
        logger.error("No forms found in blob storage; nothing to process")
        return []
    logger.info("Found %d forms to process", len(forms))

    results: list[dict] = []
    failed: list[str] = []

    for form_name in forms:
        try:
            record = _process_form(form_name, students, project, agent_name)
            results.append(record)
        except PayloadError as e:
            logger.error("Skipping form '%s': %s", form_name, e)
            failed.append(form_name)
        except Exception:
            logger.exception("Skipping form '%s': unexpected error", form_name)
            failed.append(form_name)

    logger.info("=== Pipeline run finished: %d succeeded, %d failed ===",
                len(results), len(failed))
    if failed:
        logger.warning("Failed forms: %s", ", ".join(failed))

    _write_results(results)
    return results


def _write_results(results: list[dict]) -> None:
    try:
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(
            json.dumps(results, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Wrote %d results to %s", len(results), RESULTS_PATH)
    except Exception:
        logger.exception("Failed to write results to %s", RESULTS_PATH)


if __name__ == "__main__":
    setup_logging()
    pipeline_results = run_pipeline()
    print(f"\n=== {len(pipeline_results)} students processed ===")
    print(json.dumps(pipeline_results, indent=2, ensure_ascii=False))