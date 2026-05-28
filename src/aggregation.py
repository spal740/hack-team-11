"""Aggregate component grades into a final assessment using a Foundry Agent.

Split into:
  - setup_aggregator()  -> creates project client + agent ONCE. Call once.
  - aggregate_assessment(project, agent_name, scored, student) -> dict.
    Per-student invoke. Call inside the loop.
"""

import json
import os
import logging
from pathlib import Path

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition

load_dotenv()
logger = logging.getLogger(__name__)

AGENT_NAME = "mbchb-aggregator"
INSTRUCTIONS_PATH = Path(__file__).parent.parent / "prompts" / "aggregation_prompt.md"


def _get_project_client() -> AIProjectClient:
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        raise RuntimeError("FOUNDRY_PROJECT_ENDPOINT not set in .env")
    return AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )


def _ensure_agent_exists(project: AIProjectClient) -> str:
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if not deployment:
        raise RuntimeError("AZURE_OPENAI_DEPLOYMENT not set in .env")

    try:
        instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error("Aggregation prompt not found at %s", INSTRUCTIONS_PATH)
        raise

    logger.info("Ensuring aggregator agent '%s' exists (deployment: %s)",
                AGENT_NAME, deployment)
    try:
        agent = project.agents.create_version(
            agent_name=AGENT_NAME,
            definition=PromptAgentDefinition(
                model=deployment,
                instructions=instructions,
            ),
        )
    except Exception:
        logger.exception("Failed to create/update agent '%s'", AGENT_NAME)
        raise

    logger.info("Aggregator agent ready: %s", agent.name)
    return agent.name


def setup_aggregator() -> tuple[AIProjectClient, str]:
    """Create project client and ensure aggregator agent exists. Call ONCE."""
    logger.info("Setting up aggregator (once)")
    project = _get_project_client()
    agent_name = _ensure_agent_exists(project)
    return project, agent_name


def aggregate_assessment(
    project: AIProjectClient,
    agent_name: str,
    scored: dict,
    student: dict,
) -> dict:
    """Per-student aggregation. Returns the agent's structured output dict."""
    student_id = scored.get("student_id") or student.get("student_id")
    logger.info("Aggregating student %s", student_id)

    openai_client = project.get_openai_client()

    payload = {"scored": scored, "student": student}
    payload_json = json.dumps(payload, indent=2)

    try:
        conversation = openai_client.conversations.create(
            items=[{"type": "message", "role": "user", "content": payload_json}]
        )
        response = openai_client.responses.create(
            conversation=conversation.id,
            input=(
                "Apply the rubric rules to the input above and return the "
                "final assessment JSON. Return ONLY the JSON object, no commentary."
            ),
            extra_body={
                "agent_reference": {
                    "name": agent_name,
                    "type": "agent_reference",
                }
            },
        )
    except Exception:
        logger.exception("Aggregator call failed for student %s", student_id)
        raise

    text_parts = []
    for item in response.output:
        if item.type == "message":
            for block in item.content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
    full_text = "".join(text_parts).strip()

    if full_text.startswith("```"):
        lines = full_text.split("\n")
        full_text = "\n".join(lines[1:-1]).strip()

    try:
        result = json.loads(full_text)
    except json.JSONDecodeError:
        logger.exception(
            "Aggregator returned non-JSON for student %s; raw text: %r",
            student_id, full_text,
        )
        raise

    logger.info(
        "Aggregated student %s -> Final=%s, escalation=%s",
        student_id, result.get("Final_Overall_Grade"), result.get("escalation"),
    )
    return result


if __name__ == "__main__":
    from src.logging_config import setup_logging
    setup_logging()

    project, agent_name = setup_aggregator()

    fake_scored = {
        "student_id": "100099",
        "CSR_Grade": "Pass",
        "CSR_reasoning": "key_excellents=6, some_reservations=0, major_deficiencies=0 -> Pass.",
        "CAT_Grade": "Pass",
        "CAT_reasoning": "cat_score=18 -> 14-18 range -> Pass.",
        "POGS_Grade": "Distinction",
        "POGS_reasoning": "pogs_score=10 -> Distinction.",
    }
    fake_student = {
        "student_id": "100099",
        "csr": {"key_excellents_count": 6, "some_reservations_count": 0, "major_deficiencies_count": 0},
        "csr_ratings_per_domain": {
            "clinical_knowledge": "Excellent",
            "patient_assessment": "Excellent",
            "clinical_decision": "Excellent",
            "communication": "Excellent",
            "engagement_team": "Excellent",
            "professional_qualities": "Excellent",
        },
        "cat_score": 18,
        "pogs_score": 10,
        "fitness_concern": False,
        "fitness_concern_reason": "",
    }
    result = aggregate_assessment(project, agent_name, fake_scored, fake_student)
    print(json.dumps(result, indent=2, ensure_ascii=False))