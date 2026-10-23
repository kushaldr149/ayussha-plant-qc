"""AI review of QC and production records through the Claude API.

Claude is asked to use only the records sent, and never to invent limits, standards or causes.
The review is advisory: decisions on lots stay with the QC team.
"""
from __future__ import annotations

import json

from . import config

PROMPT = """You are assisting the quality team of a dry mix concrete plant. Coarse aggregate is coated in coating \
batches; cement, GGBS, fly ash and microsilica are ground in grinding batches. Coated coarse aggregate and fine \
aggregate are packed in aggregate jumbo bags, cementitious materials in cementitious jumbo bags, fibres in fibre bags \
and admixtures in barrels. The bags go to site with a mixer on wheels, where site mixing records are kept. Review the \
plant records below.

Rules:
- Use only the data given. Do not assume causes, standards, limits or values that are not in the data.
- Where the data is not enough to conclude something, say so plainly.
- Refer to records by test number or record number, date, material and lot number.
- Do not recommend accepting or rejecting a lot; list what needs a decision and why.
- Plain text. Short headings followed by short lines. No tables.

Sections (skip a section if its data is empty):
1. Summary: counts of material tests, out-of-limit tests, lots on hold, coating batches, grinding batches, bags by kind \
and status, bags outside batching tolerance, production records, dispatches, site mixes, strength samples, open NCRs.
2. Out-of-limit results, grouped by material and supplier, with the parameter, value and limit.
3. Repeated issues: the same material, supplier or parameter out of limit more than once.
4. Coating and grinding batches: batches on hold or rejected, batches that used lots not accepted or with no QC record, \
batches with no QC test linked, and coating batches outside the coating dosage target or with no target \
(coating_check). Grinding fineness has no target in the data; report it as given.
5. Bags: bags outside the batching tolerance (with material, planned, actual and deviation), bags with no tolerance or \
planned quantities, bags packed from lots not accepted or from batches not accepted, and flagged bags that were \
dispatched or used at site.
6. Production records over tolerance, or using lots that were not accepted or had no QC record.
7. Open decisions: lots and batches on hold.
8. Dispatch: deliveries still on the road, returned or cancelled trips, and bags dispatched from flagged records.
9. Site mixing: per mix the water, water/binder ratio (state its basis as given in the data), mixing time, slump or \
flow, temperatures and admixture doses; mixes with flagged bags; mixes with no cube sample; values not entered. \
There are no limits for these in the data, so do not judge them against any limit.
10. Strength and durability tests: results below the acceptance values entered for the grade, samples with no \
acceptance values, and durability results that do not meet their target (with the target source) or have no target.
11. NCRs: open and overdue NCRs, and repeated sources.
12. Sensors: readings outside the limits set for each sensor, grouped by sensor, with the limit and its source.
13. Data gaps: tests with values not entered, production records or bags without planned values or lot numbers.

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
