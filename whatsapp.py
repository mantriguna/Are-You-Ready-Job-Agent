import os
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class IncomingTextMessage:
    whatsapp_number: str
    message_id: str
    text: str


def extract_text_messages(payload: dict) -> list[IncomingTextMessage]:
    incoming_messages: list[IncomingTextMessage] = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                if message.get("type") != "text":
                    continue

                whatsapp_number = message.get("from")
                message_id = message.get("id")
                body = message.get("text", {}).get("body")
                if whatsapp_number and message_id and body:
                    incoming_messages.append(
                        IncomingTextMessage(
                            whatsapp_number=whatsapp_number,
                            message_id=message_id,
                            text=body,
                        )
                    )

    return incoming_messages


async def send_text_message(whatsapp_number: str, body: str) -> dict:
    access_token = os.getenv("META_ACCESS_TOKEN")
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    api_version = os.getenv("META_GRAPH_API_VERSION", "v25.0")

    if not access_token or not phone_number_id:
        raise RuntimeError("Missing META_ACCESS_TOKEN or META_PHONE_NUMBER_ID.")

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": whatsapp_number,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


async def send_template_message(
    *,
    whatsapp_number: str,
    template_name: str,
    language_code: str,
    body_parameters: list[str],
) -> dict:
    access_token = os.getenv("META_ACCESS_TOKEN")
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    api_version = os.getenv("META_GRAPH_API_VERSION", "v25.0")

    if not access_token or not phone_number_id:
        raise RuntimeError("Missing META_ACCESS_TOKEN or META_PHONE_NUMBER_ID.")

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": whatsapp_number,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(parameter)[:1024]}
                        for parameter in body_parameters
                    ],
                }
            ],
        },
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


async def send_document_message(
    *,
    whatsapp_number: str,
    document_url: str,
    filename: str,
    caption: str,
) -> dict:
    access_token = os.getenv("META_ACCESS_TOKEN")
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    api_version = os.getenv("META_GRAPH_API_VERSION", "v25.0")

    if not access_token or not phone_number_id:
        raise RuntimeError("Missing META_ACCESS_TOKEN or META_PHONE_NUMBER_ID.")

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": whatsapp_number,
        "type": "document",
        "document": {
            "link": document_url,
            "filename": filename,
            "caption": caption,
        },
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
