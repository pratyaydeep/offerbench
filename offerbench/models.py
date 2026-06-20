from typing import Literal

from pydantic import BaseModel, Field


class OfferEntry(BaseModel):
    """One distinct offer/company mentioned in a post. Most posts have
    exactly one; comparison posts (e.g. "Amazon vs Gojek") have several."""

    organization: str | None = None
    role_title: str | None = None
    level_grade: str | None = None

    currency: str | None = None
    total_ctc: float | None = None
    fixed_base: float | None = None
    variable_bonus: float | None = None
    stock_rsu: float | None = None
    signing_bonus: float | None = None
    retirement_benefits: float | None = None

    confidence: float = Field(ge=0, le=1, default=0.0)
    notes: str | None = None


class ExtractionResult(BaseModel):
    """Top-level fields describe the post/poster as a whole and are shared
    across all offers; `offers` holds one entry per distinct company/offer
    mentioned."""

    post_kind: (
        Literal["accepted_offer", "current_comp", "question", "comparison", "other"] | None
    ) = None
    years_experience: float | None = None
    location: str | None = None

    offers: list[OfferEntry] = Field(default_factory=list)
