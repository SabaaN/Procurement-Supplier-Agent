"""Building blocks shared by every device type (camera, sensor, PLC)."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

T = TypeVar("T")


class Req(BaseModel, Generic[T]):
    """One requirement: the wanted value, and whether it is a must-have.

    required=True  -> hard filter (product is dropped if it fails or lacks the field)
    required=False -> nice-to-have (only affects ranking)
    """

    value: T
    required: bool = False


class SharedCriteria(BaseModel):
    """Fields every search has, whatever the device."""

    budget_min: float | None = Field(default=None, ge=0)
    budget_max: float | None = Field(default=None, ge=0)
    currency: str = "PKR"
    quantity: int = Field(default=1, ge=1)
    notes: str = ""  # free text; the only input an LLM has to interpret

    @model_validator(mode="after")
    def _check_budget_order(self):
        if (
            self.budget_min is not None
            and self.budget_max is not None
            and self.budget_min > self.budget_max
        ):
            raise ValueError("budget_min must not exceed budget_max")
        return self


class ProductBase(BaseModel):
    """Fields every extracted product has. Missing data stays None, never guessed."""

    title: str
    source_url: str
    supplier: str | None = None
    part_number: str | None = None
    fetched_at: datetime | None = None
    price: float | None = None
    currency: str | None = None
    moq: int | None = None
    shipping_cost: float | None = None
    rating: float | None = None
    review_count: int | None = None
    # filled in by the filter / score steps
    requirements_met: list[str] = []
    requirements_missed: list[str] = []
    flags: list[str] = []
    match_score: float | None = Field(default=None, ge=0, le=100)


class FieldDef(BaseModel):
    """One form input. The frontend renders the dynamic form from a list of these."""

    name: str
    label: str
    kind: Literal["number", "select", "multiselect", "toggle"]
    unit: str | None = None
    options: list[str] = []
    help: str | None = None
    has_required_toggle: bool = True  # shows the Required / Preferred switch


SHARED_FIELDS = [
    FieldDef(name="budget_min", label="Budget min", kind="number", has_required_toggle=False),
    FieldDef(name="budget_max", label="Budget max", kind="number", has_required_toggle=False),
    FieldDef(name="quantity", label="Quantity", kind="number", has_required_toggle=False),
]


@dataclass(frozen=True)
class DeviceDefinition:
    """Everything the agent needs to know about one device type."""

    key: str
    label: str
    criteria_model: type[SharedCriteria]
    spec_model: type[ProductBase]
    fields: list[FieldDef] = field(default_factory=list)
    # Temporary: builds a fake product so the graph can run before real extraction exists.
    stub_spec: Callable[[int, str], ProductBase] | None = None
