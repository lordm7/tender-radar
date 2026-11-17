"""Test helper: a fake AI scoring answer in the three-part shape (fit, ability, risk)."""


def ai_answer(fit: int = 80, ability: int = 70, risk: int = 30, reason: str = "reason", **extra) -> dict:
    """A valid AIScore dict; `reason` is used for every part (Arabic: "سبب")."""
    answer = {
        "fit": fit, "ability": ability, "risk": risk,
        "fit_en": f"{reason} fit", "fit_ar": "سبب الملاءمة",
        "ability_en": f"{reason} ability", "ability_ar": "سبب القدرة",
        "risk_en": f"{reason} risk", "risk_ar": "سبب المخاطر",
    }
    answer.update(extra)
    return answer


def answer_for_total(total: int) -> dict:
    """An answer whose computed score is exactly `total` (fit = ability = total, risk = 100 - total)."""
    return ai_answer(total, total, 100 - total, reason=f"reason {total}",
                     fit_ar=f"سبب {total}", ability_ar=f"سبب {total}", risk_ar=f"سبب {total}")
