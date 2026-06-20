from offerbench import config

_INR_ALIASES = {"INR", "RS", "RS.", "RUPEES", "₹", "LPA"}
_USD_ALIASES = {"USD", "$", "DOLLARS"}


def normalize_compensation(
    currency: str | None, total_ctc: float | None
) -> tuple[float | None, float | None]:
    """Deterministically converts an extracted (currency, total_ctc) pair
    into (total_ctc_inr_lakhs, total_ctc_usd). The LLM reports `total_ctc`
    in lakhs already when currency is INR (e.g. 44.5 for "44.5 LPA") --
    matching the source posts' own notation reduces unit-conversion errors
    versus asking it to compute an absolute-rupee figure itself. For USD,
    `total_ctc` is a plain absolute dollar amount. Returns (None, None) if
    currency is missing/unrecognized rather than guessing."""
    if total_ctc is None:
        return None, None

    currency_norm = (currency or "INR").strip().upper()

    if currency_norm in _INR_ALIASES:
        return total_ctc, (total_ctc * 100_000) / config.USD_TO_INR
    if currency_norm in _USD_ALIASES:
        return (total_ctc * config.USD_TO_INR) / 100_000, total_ctc

    return None, None
