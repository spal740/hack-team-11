"""Aggregate component grades into a final assessment using a Foundry Agent.

This module creates/updates the aggregator agent in code (idempotent — safe to
re-run) and then invokes it on scored + student payload.
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from src.scoring import score_student

load_dotenv()

AGENT_NAME = "mbchb-aggregator"
INSTRUCTIONS_PATH = Path(__file__).parent.parent / "prompts" / "aggregation_prompt.md"


def _get_project_client() -> AIProjectClient:
    """Connect to Foundry project using Entra ID (az login)."""
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        raise RuntimeError("FOUNDRY_PROJECT_ENDPOINT not set in .env")
    return AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )


def ensure_agent_exists(project: AIProjectClient) -> str:
    """Create (or update) the aggregator agent. Returns the agent name.

    create_version is idempotent — calling it again with the same name
    creates a new version, which becomes the active one.
    """
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if not deployment:
        raise RuntimeError("AZURE_OPENAI_DEPLOYMENT not set in .env")

    instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")

    agent = project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=deployment,
            instructions=instructions,
        ),
    )
    return agent.name


def aggregate_assessment(scored: dict, student: dict) -> dict:
    """Invoke the aggregator agent on the scored + student payload."""
    project = _get_project_client()
    agent_name = ensure_agent_exists(project)
    openai_client = project.get_openai_client()

    payload = {"scored": scored, "student": student}
    payload_json = json.dumps(payload, indent=2)

    conversation = openai_client.conversations.create(
        items=[
            {
                "type": "message",
                "role": "user",
                "content": payload_json,
            }
        ]
    )

    response = openai_client.responses.create(
        conversation=conversation.id,
        input=(
            "Apply the rubric rules to the input above and return the final "
            "assessment JSON. Return ONLY the JSON object, no commentary."
        ),
        extra_body={
            "agent_reference": {
                "name": agent_name,
                "type": "agent_reference",
            }
        },
    )

    # Walk the response structure to extract the text
    text_parts = []
    for item in response.output:
        if item.type == "message":
            for block in item.content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)

    full_text = "".join(text_parts).strip()

    # Strip markdown code fence if present
    if full_text.startswith("```"):
        lines = full_text.split("\n")
        full_text = "\n".join(lines[1:-1]).strip()

    return json.loads(full_text)


if __name__ == "__main__":
    mock_path = Path(__file__).parent.parent / "samples" / "mock_extraction.json"
    with open(mock_path, encoding="utf-8") as f:
        student = json.load(f)

    print("=" * 60)
    print("STUDENT INPUT")
    print("=" * 60)
    print(json.dumps(student, indent=2))

    print("\n" + "=" * 60)
    print("RUNNING SCORING (direct gpt-5-mini call)...")
    print("=" * 60)
    scored = score_student(student)
    print(json.dumps(scored, indent=2))

    print("\n" + "=" * 60)
    print("RUNNING AGGREGATION (Foundry Agent call)...")
    print("=" * 60)
    final = aggregate_assessment(scored, student)
    print(json.dumps(final, indent=2))