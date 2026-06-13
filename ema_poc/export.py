"""Export query results to CSV and JSON for stakeholder review (FR-305).

Serializes Response models via model_dump(mode="json") so enums become their
string values and timestamps become ISO strings — safe for both CSV cells and
JSON."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable

from ema_poc.models import Response

_FIELDS = list(Response.model_fields.keys())


def export_csv(responses: Iterable[Response], path: str) -> int:
    rows = [r.model_dump(mode="json") for r in responses]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def export_json(responses: Iterable[Response], path: str) -> int:
    rows = [r.model_dump(mode="json") for r in responses]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)
    return len(rows)
