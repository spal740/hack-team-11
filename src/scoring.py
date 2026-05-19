"""Apply rubric rules to a student's extracted assessment data using GPT-4o-mini."""

import json
from pathlib import Path
from src.client import get_openai_client, get_deployment_name

# Update this path if you used a different filename for the prompt
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "scoring_prompt.md"


def score_student(student_data: dict) -> dict:
    """Send student data + rubric rules to GPT-4o-mini, return scored JSON."""
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    client = get_openai_client()
    response = client.chat.completions.create(
        model=get_deployment_name(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(student_data, indent=2)},
        ],
        response_format={"type": "json_object"},
        
    )

    return json.loads(response.choices[0].message.content)


if __name__ == "__main__":
    mock_path = Path(__file__).parent.parent / "samples" / "mock_extraction.json"
    with open(mock_path, encoding="utf-8") as f:
        student = json.load(f)

    print("Input:")
    print(json.dumps(student, indent=2))
    print()

    result = score_student(student)

    print("Scored output:")
    print(json.dumps(result, indent=2))