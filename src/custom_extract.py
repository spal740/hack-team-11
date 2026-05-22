"""Test custom extraction model on one form from Blob Storage."""

import os
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient

from src.blob_reader import download_blob, list_forms

load_dotenv()


def extract_form(form_bytes: bytes) -> dict:
    """Run custom extraction model on form bytes, return fields dict."""
    endpoint = os.environ["DOCUMENTINTELLIGENCE_ENDPOINT"]
    key = os.environ["DOCUMENTINTELLIGENCE_API_KEY"]
    model_id = os.environ["CUSTOM_MODEL_ID"]

    client = DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key),
    )

    poller = client.begin_analyze_document(model_id=model_id, body=form_bytes)
    result = poller.result()

    fields = {}
    if result.documents:
        for doc in result.documents:
            for name, field in doc.fields.items():
                fields[name] = {
                    "value": field.get("valueString") or field.content,
                    "confidence": field.confidence,
                }
    return fields


if __name__ == "__main__":
    # Grab the first form from blob
    forms = list_forms()
    if not forms:
        print("No forms found in blob storage.")
        exit(1)

    form_name = forms[0]
    container = os.getenv("AZURE_CONTAINER_FORMS", "raw-forms")
    print(f"Downloading: {form_name}")

    form_bytes = download_blob(container, form_name)
    print(f"Downloaded {len(form_bytes)} bytes\n")

    print("Running custom extraction model...")
    fields = extract_form(form_bytes)

    print(f"\n--- Extracted {len(fields)} fields ---")
    for name, info in fields.items():
        print(f"  {name}: {info['value']}  (conf: {info['confidence']:.2f})")