"""Building blocks shared by every device type (camera, sensor, PLC)."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

T = TypeVar("T")


class Req(BaseModel, Generic[T]):
    """One requirement: the wanted value, and how firm it is.

    required=True  -> must-have: the product is dropped if its page shows it fails
    flexible=True  -> close is fine: numbers up to FLEXIBLE_TOLERANCE short are kept as close
                      matches (ranked lower), other values that differ are kept as compromises,
                      and the spec is left out of the web searches so nearby values are found
    neither        -> nice-to-have: only affects ranking
    """

    value: T
    required: bool = False
    flexible: bool = False

    @model_validator(mode="after")
    def _one_level(self):
        if self.flexible:
            self.required = False  # flexible wins: it is the softer of the two
        return self


class SharedCriteria(BaseModel):
    """Fields every search has, whatever the device."""

    budget_min: float | None = Field(default=None, ge=0)
    budget_max: float | None = Field(default=None, ge=0)
    currency: str = "PKR"
    quantity: int = Field(default=1, ge=1)
    flexible_budget: bool = False  # keep products a little over budget_max (BUDGET_TOLERANCE), flagged
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
    # read from the page's HTML in Python (services/contacts.py), never by the model
    company_name: str | None = None
    email: str | None = None
    contact_no: str | None = None
    product_link: str | None = None
    datasheet_url: str | None = None  # a PDF the supplier links from the product page
    # filled in by the filter / score steps
    requirements_met: list[str] = []
    requirements_missed: list[str] = []
    flags: list[str] = []
    match_score: float | None = Field(default=None, ge=0, le=100)
    price_buyer: float | None = None  # unit price in the buyer's currency
    fx_rate: float | None = None  # exchange rate used, when the price was converted
    total_cost: float | None = None  # price_buyer x quantity (excludes shipping and duties)
    score_breakdown: dict[str, float | None] = {}  # preferences / price / confidence, each 0 to 1


class FieldDef(BaseModel):
    """One form input. The frontend renders the dynamic form from a list of these."""

    name: str
    label: str
    kind: Literal["number", "select", "multiselect", "toggle"]
    unit: str | None = None
    options: list[str] = []
    help: str | None = None
    has_required_toggle: bool = True  # shows the Required / Preferred switch
    # Word put after a chosen option in template search queries ("global" + "shutter"). None: the
    # label; "": nothing, for options that read on their own ("through-beam", "M18").
    search_word: str | None = None


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
    # What the LLM fills in from a page (loose strings), and how Python turns that into spec_model fields.
    extraction_model: type[BaseModel] | None = None
    extraction_hint: str = ""
    # What to search for, and what the searches must avoid (e.g. CCTV when the buyer wants machine vision).
    search_term: str = ""
    search_hint: str = ""
    # Words that show a page is about this device. A page with none of them and no price is skipped
    # without a model call (see services/triage.py). Lower case; leave empty to never skip this way.
    page_words: tuple[str, ...] = ()
    normalize: Callable[[dict], tuple[dict, list[str]]] | None = None
    # Requirement checks: criteria field -> (spec field or tuple of fields, comparison, label), see compare.py.
    checks: dict = field(default_factory=dict)
    units: dict = field(default_factory=dict)  # criteria field -> unit shown in close-match notes
    # Used only by tests, to fake products without calling Groq.
    stub_spec: Callable[[int, str], ProductBase] | None = None
