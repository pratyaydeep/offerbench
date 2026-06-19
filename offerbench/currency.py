from offerbench import config

_INR_ALIASES = {"INR", "RS", "RS.", "RUPEES", "₹", "LPA"}
_USD_ALIASES = {"USD", "$", "DOLLARS"}


def normalize_compensation(
    currency: str | None, total_ctc: float | None
) -> tuple[float | None, float | None]:
    """Deterministically converts an extracted (currency, total_ctc) pair —
    where total_ctc is expected to be an absolute amount in that currency's
    base unit, not a shorthand like lakhs — into (total_ctc_inr_lakhs,
    total_ctc_usd). Returns (None, None) if currency is missing/unrecognized
    rather than guessing."""
    if total_ctc is None:
        return None, None

    currency_norm = (currency or "INR").strip().upper()

    if currency_norm in _INR_ALIASES:
        return total_ctc / 100_000, total_ctc / config.USD_TO_INR
    if currency_norm in _USD_ALIASES:
        return (total_ctc * config.USD_TO_INR) / 100_000, total_ctc

    return None, None
