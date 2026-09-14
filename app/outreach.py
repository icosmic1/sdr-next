"""Source-grounded Gemini outreach generation for the local SDR workspace."""
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .config import get_settings
from .models import Account, Prospect


class OutreachConfigurationError(RuntimeError):
    pass


class OutreachProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class OutreachDraft:
    subject: str
    opening_line: str
    email_body: str
    call_talk_track: str
    source_urls: list[str]
    provider: str = "Gemini"


def _evidence(account: Account, prospect: Prospect) -> list[dict[str, str]]:
    findings = list(account.signals)
    if prospect.research_state:
        findings.extend(prospect.research_state.signals)
    seen: set[str] = set()
    items: list[dict[str, str]] = []
    for finding in findings:
        if finding.source_url in seen:
            continue
        seen.add(finding.source_url)
        items.append({"summary": finding.summary[:240], "evidence": finding.evidence[:500], "url": finding.source_url})
        if len(items) == 5:
            break
    return items


def _prompt(account: Account, prospect: Prospect, evidence: list[dict[str, str]]) -> str:
    context = {"company": account.name, "company_domain": account.domain, "industry": account.industry or "not supplied", "prospect_name": prospect.name, "prospect_title": prospect.title, "verified_evidence": evidence}
    return f"""You write brief, professional B2B SDR outreach.

Use only the facts supplied in CONTEXT. Do not invent company news, metrics, initiatives, technology, funding, relationships, or personal details. Do not claim to have personally observed the prospect. If there is no useful evidence, write a low-pressure role-based draft that does not imply a signal exists. Do not include links or citations in the email itself.

Return a JSON object with exactly these strings:
- subject: maximum 8 words
- opening_line: one sentence, maximum 28 words
- email_body: 55-100 words, including a simple CTA
- call_talk_track: one sentence, maximum 35 words

CONTEXT:
{json.dumps(context, ensure_ascii=False)}"""


def _text_from_response(payload: dict[str, Any]) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
        return "".join(str(part.get("text", "")) for part in parts).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise OutreachProviderError("Gemini returned no usable content.") from exc


def _clean_draft(text: str, source_urls: list[str]) -> OutreachDraft:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OutreachProviderError("Gemini returned an unreadable outreach draft.") from exc
    fields = ("subject", "opening_line", "email_body", "call_talk_track")
    if not isinstance(value, dict) or any(not isinstance(value.get(field), str) or not value[field].strip() for field in fields):
        raise OutreachProviderError("Gemini returned an incomplete outreach draft.")
    return OutreachDraft(**{field: value[field].strip()[:1500] for field in fields}, source_urls=source_urls)


async def generate_outreach(account: Account, prospect: Prospect) -> OutreachDraft:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise OutreachConfigurationError("Gemini outreach is not configured. Set GEMINI_API_KEY in .env.")
    evidence = _evidence(account, prospect)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(settings.gemini_model, safe='-_.')}:generateContent"
    schema = {
        "type": "OBJECT",
        "properties": {
            "subject": {"type": "STRING"},
            "opening_line": {"type": "STRING"},
            "email_body": {"type": "STRING"},
            "call_talk_track": {"type": "STRING"},
        },
        "required": ["subject", "opening_line", "email_body", "call_talk_track"],
    }
    payload = {"contents": [{"role": "user", "parts": [{"text": _prompt(account, prospect, evidence)}]}], "generationConfig": {"temperature": 0.35, "maxOutputTokens": 1200, "thinkingConfig": {"thinkingLevel": "minimal"}, "responseMimeType": "application/json", "responseSchema": schema}}
    try:
        async with httpx.AsyncClient(timeout=settings.gemini_timeout_seconds) as client:
            response = await client.post(url, params={"key": settings.gemini_api_key}, json=payload)
        if response.status_code >= 400:
            raise OutreachProviderError(f"Gemini request failed ({response.status_code}).")
        data = response.json()
    except httpx.HTTPError as exc:
        raise OutreachProviderError("Gemini could not be reached.") from exc
    return _clean_draft(_text_from_response(data), [item["url"] for item in evidence])
