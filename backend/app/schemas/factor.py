from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class DomainEnum(str, Enum):
    sales = "sales"
    statistics = "statistics"
    policy = "policy"
    organization = "organization"


class Factor(BaseModel):
    factor_id: str = Field(..., description="Identifier like F1, F2, ...")
    description: str
    domain: DomainEnum
