from offerbench.currency import normalize_compensation


def test_inr_converts_to_lakhs_and_usd():
    lakhs, usd = normalize_compensation("INR", 4_450_000)
    assert lakhs == 44.5
    assert round(usd, 2) == round(4_450_000 / 83.0, 2)


def test_usd_converts_to_lakhs_and_passthrough():
    lakhs, usd = normalize_compensation("USD", 100_000)
    assert usd == 100_000
    assert round(lakhs, 2) == round(100_000 * 83.0 / 100_000, 2)


def test_missing_currency_defaults_to_inr():
    lakhs, usd = normalize_compensation(None, 1_000_000)
    assert lakhs == 10.0


def test_unknown_currency_returns_none():
    lakhs, usd = normalize_compensation("EUR", 50_000)
    assert lakhs is None
    assert usd is None


def test_none_total_ctc_returns_none():
    lakhs, usd = normalize_compensation("INR", None)
    assert lakhs is None
    assert usd is None
