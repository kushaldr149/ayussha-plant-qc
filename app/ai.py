"""AI review of QC and production records through the Claude API.

Claude is asked to use only the records sent, and never to invent limits, standards or causes.
The review is advisory: decisions on lots stay with the QC team.
"""
from __future__ import annotations

import json

from . import config

PROMPT = """You are assisting the quality team of a dry mix concrete plant. The plant packs coated coarse \
aggregate, fine aggregate and cementitious material in separate bulk bags. Review the plant records below.

Rules:
- Use only the data given. Do not assume causes, standards, limits or values that are not in the data.
- Where the data is not enough to conclude something, say so plainly.
- Refer to records by test number or record number, date, material and lot number.
- Do not recommend accepting or rejecting a lot; list what needs a decision and why.
- Plain text. Short headings followed by short lines. No tables.

Sections (skip a section if its data is empty):
1. Summary: counts of material tests, out-of-limit tests, lots on hold, production records, records over tolerance, dispatches, strength samples, open NCRs.
2. Out-of-limit results, grouped by material and supplier, with the parameter, value and limit.
3. Repeated issues: the same material, supplier or parameter out of limit more than once.
4. Production records over tolerance, or using lots that were not accepted or had no QC record.
5. Open decisions: lots on hold.
6. Dispatch: deliveries still on the road, returned or cancelled trips, and bags dispatched from flagged production records.
7. Strength tests: results below the acceptance values entered for the grade, and samples with no acceptance values.
8. NCRs: open and overdue NCRs, and repeated sources.
9. Data gaps: tests with values not entered, production records without planned values or lot numbers.

Data (JSON):
"""


class AIUnavailable(Exception):
    pass


def enabled() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def review(data: dict) -> str:
    if not enabled():
        raise AIUnavailable("Set ANTHROPIC_API_KEY in the .env file and restart the app to enable AI review.")
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=180.0, max_retries=2)
    try:
        message = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": PROMPT + json.dumps(data, ensure_ascii=False, default=str)}],
        )
    except anthropic.AuthenticationError as e:
        raise AIUnavailable("The Claude API key was rejected. Check ANTHROPIC_API_KEY in the .env file.") from e
    except anthropic.RateLimitError as e:
        raise AIUnavailable("The Claude API rate limit was reached. Try again in a few minutes.") from e
    except anthropic.NotFoundError as e:
        raise AIUnavailable(f"The model '{config.CLAUDE_MODEL}' was not found. Check CLAUDE_MODEL in the .env file.") from e
    except anthropic.APIConnectionError as e:
        raise AIUnavailable("Could not reach the Claude API. Check the server's internet connection.") from e
    except anthropic.APIError as e:
        raise AIUnavailable(f"The Claude API returned an error: {getattr(e, 'message', str(e))}") from e
    text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text").strip()
    if not text:
        raise AIUnavailable("Claude returned no text. Try again.")
    if message.stop_reason == "max_tokens":
        text += "\n\n[The review was cut short. Choose a shorter period.]"
    return text
