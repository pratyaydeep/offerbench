from typing import Literal

from pydantic import BaseModel, Field


class ExtractedOffer(BaseModel):
    organization: str | None = None
    role_title: str | None = None
    level_grade: str | None = None
    years_experience: float | None = None
    location: str | None = None
    post_kind: (
        Literal["accepted_offer", "current_comp", "question", "comparison", "other"] | None
    ) = None

    currency: str | None = None
    total_ctc: float | None = None
    fixed_base: float | None = None
    variable_bonus: float | None = None
    stock_rsu: float | None = None
    signing_bonus: float | None = None
    retirement_benefits: float | None = None

    confidence: float = Field(ge=0, le=1, default=0.0)
    notes: str | None = None
