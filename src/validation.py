"""Verify mandatory fields are present in an extracted form (in-scope:
"Mandatory field verification").

Checks the CSR tickbox criteria, CAT score, Fitness to Practise, and
Student ID. A criterion is 'complete' if at least one of its options is
selected. Reports anything missing.
"""

import logging
from src.logging_config import setup_logging

logger = logging.getLogger(__name__)

# The 12 CSR criteria. Note: patient_assessment uses '_some_res' for the
# "some reservations" option; the other 11 use '_reservations'.
CSR_CRITERIA = [
    "patient_assessment", "clinical_decision", "communication",
    "professional_qualities", "engagement_team", "self_management",
    "clinical_knowledge", "critical_reflection", "commitment_equity",
    "cultural_safety", "disease_prevention", "health_promotion",
]

# The selection options each criterion can have (any one selected = complete).
CSR_OPTIONS = ["major", "some_res", "reservations", "good", "excellent", "not_obs"]


def _is_selected(form: dict, key: str) -> bool:
    """True if the given field exists and is selected."""
    field = form.get(key)
    if not field:
        return False
    value = field.get("value")
    return value == ":selected:"


def verify_mandatory_fields(form: dict) -> dict:
    """Check all mandatory fields are present in the extracted form.

    Args:
        form: extraction output -- {field_name: {"value", "confidence"}}

    Returns:
        {"complete": bool, "missing": [list of missing field descriptions]}
    """
    missing = []

    # --- Student ID ---
    sid = form.get("Student_ID")
    if not sid or not sid.get("value"):
        missing.append("Student_ID")

    # --- CAT score ---
    cat = form.get("cat_total_score")
    if not cat or not cat.get("value"):
        missing.append("cat_total_score")

    # --- Fitness to Practise: at least one of yes/no selected ---
    ftp_yes = _is_selected(form, "fitness_to_practise_yes")
    ftp_no = _is_selected(form, "fitness_to_practise_no")
    if not (ftp_yes or ftp_no):
        missing.append("fitness_to_practise (neither yes nor no selected)")

    # --- CSR: each of the 12 criteria must have one option selected ---
    for criterion in CSR_CRITERIA:
        selected = any(
            _is_selected(form, f"{criterion}_{opt}")
            for opt in CSR_OPTIONS
        )
        if not selected:
            missing.append(f"CSR criterion '{criterion}' (no option selected)")

    complete = len(missing) == 0
    if complete:
        logger.info("Mandatory field check: PASSED")
    else:
        logger.warning("Mandatory field check: %d missing", len(missing))
        for m in missing:
            logger.warning("  missing: %s", m)

    return {"complete": complete, "missing": missing}


if __name__ == "__main__":
    setup_logging()
    import os
    from src.blob_reader import download_blob, list_forms
    from src.custom_extract import extract_form

    forms = list_forms()
    if not forms:
        logger.error("No forms found.")
        raise SystemExit(1)

    container = os.getenv("AZURE_CONTAINER_FORMS", "raw-forms")
    form_bytes = download_blob(container, forms[0])
    fields = extract_form(form_bytes)

    result = verify_mandatory_fields(fields)
    print(f"\ncomplete: {result['complete']}")
    print(f"missing:  {result['missing']}")