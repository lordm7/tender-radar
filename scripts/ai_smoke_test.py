"""Manual check of the real AI provider's Arabic quality. It is never run in CI.

Usage (PowerShell):
    $env:TR_AI_PROVIDER="gemini"; $env:GEMINI_API_KEY="..."; $env:TR_GEMINI_MODEL="<model>"
    python scripts/ai_smoke_test.py

It scores 3 seed tenders against the demo profile and prints the JSON, so you
can judge whether the Arabic reasons read naturally before choosing a model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tender_radar.ai.provider import get_provider
from tender_radar.models import AIScore, load_profile, load_seed_tenders
from tender_radar.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    provider = get_provider(Settings())
    profile = load_profile(ROOT / "data/seed/profile_it_services.json")
    tenders = load_seed_tenders(ROOT / "data/seed/tenders.json")
    for tender in (tenders[0], tenders[3], tenders[15]):
        prompt = (
            "You score how well a government tender fits a company (0-100) and give 2-3 short reasons "
            "in English and in Saudi business Arabic.\n"
            f"Company: {profile.model_dump_json()}\nTender: {tender.model_dump_json()}"
        )
        result = provider.generate_json(prompt, AIScore)
        print(tender.reference, json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
