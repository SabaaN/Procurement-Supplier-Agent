"""Photoelectric sensor (industrial) criteria, product spec and form definition."""
import re
from typing import Literal, get_args

from pydantic import BaseModel, PositiveFloat, PositiveInt

from .base import SHARED_FIELDS, DeviceDefinition, FieldDef, ProductBase, Req, SharedCriteria
from .compare import any_overlap, at_least, at_most, contains, equals, within_range
from .parse import ip_rating, length_mm, pick, pick_all, time_ms, voltage_range

SensingMethod = Literal[
    "through-beam", "retro-reflective", "polarized retro-reflective", "diffuse", "background suppression",
    "fiber optic",
]
Output = Literal["NPN", "PNP", "Relay", "Push-pull", "Analog", "IO-Link"]
SwitchingMode = Literal["light-on", "dark-on"]
LightSource = Literal["red", "infrared", "laser", "blue"]
Housing = Literal["M8", "M12", "M18", "M30", "rectangular"]
Connection = Literal["cable", "M8 connector", "M12 connector"]


class PhotoelectricCriteria(SharedCriteria):
    """What the buyer asks for. Every spec is optional and carries its own level."""

    sensing_method: Req[SensingMethod] | None = None
    min_sensing_range: Req[PositiveFloat] | None = None  # mm
    output: Req[list[Output]] | None = None  # any of these
    switching_mode: Req[SwitchingMode] | None = None
    light_source: Req[LightSource] | None = None
    housing: Req[Housing] | None = None
    connection: Req[Connection] | None = None
    supply_voltage: Req[PositiveFloat] | None = None  # V: the buyer's supply, must be in the sensor's range
    max_response_time: Req[PositiveFloat] | None = None  # ms
    min_ip: Req[PositiveInt] | None = None  # 67 for IP67


class PhotoelectricSpec(ProductBase):
    """What was extracted from a product page. Every spec is nullable: not on page -> None."""

    sensing_method: SensingMethod | None = None
    sensing_range_mm: float | None = None  # the longest distance stated
    output: list[Output] = []
    switching_mode: list[SwitchingMode] = []  # both when selectable
    light_source: LightSource | None = None
    housing: Housing | None = None
    connection: Connection | None = None
    supply_min_v: float | None = None
    supply_max_v: float | None = None
    response_time_ms: float | None = None
    ip_rating: int | None = None
    extra_specs: dict[str, str] = {}


def _stub_spec(i: int, url: str) -> PhotoelectricSpec:
    """Fake product for pipeline tests (no Groq)."""
    return PhotoelectricSpec(
        title=f"Stub photoelectric sensor {i + 1}",
        supplier="stub-supplier",
        source_url=url,
        price=2500 + 1500 * i,
        currency="PKR",
        sensing_method=["diffuse", "retro-reflective", "through-beam"][i % 3],
        sensing_range_mm=[300.0, 4000.0, 20000.0][i % 3],
        output=[["NPN"], ["PNP"], ["NPN", "PNP"]][i % 3],
        switching_mode=[["light-on", "dark-on"], ["dark-on"], ["light-on"]][i % 3],
        light_source=["red", "red", "infrared"][i % 3],
        housing=["M18", "rectangular", "M18"][i % 3],
        connection=["cable", "M12 connector", "M8 connector"][i % 3],
        supply_min_v=[10.0, 12.0, 24.0][i % 3],
        supply_max_v=[30.0, 24.0, 240.0][i % 3],
        response_time_ms=[1.0, 0.5, 2.0][i % 3],
        ip_rating=[67, 65, 67][i % 3],
    )


class PhotoelectricExtraction(BaseModel):
    """What the LLM fills in from one page. Deliberately loose: Python normalises it."""

    is_product_page: bool
    is_listing_page: bool = False
    is_right_device_type: bool | None = None  # see PHOTOELECTRIC_HINT
    title: str | None = None
    supplier: str | None = None
    part_number: str | None = None
    price: float | None = None
    currency: str | None = None
    moq: int | None = None
    sensing_method: str | None = None
    sensing_range: str | None = None  # as written, with its unit: "0.1-2 m", "300 mm"
    output: list[str] = []
    switching_mode: str | None = None
    light_source: str | None = None
    housing: str | None = None
    connection: str | None = None
    supply_min_v: float | None = None
    supply_max_v: float | None = None
    response_time: str | None = None  # as written, with its unit: "1 ms", "500 us"
    ip_rating: str | None = None


PHOTOELECTRIC_HINT = (
    "Industrial photoelectric sensor. is_right_device_type: true for photoelectric sensors that detect objects "
    "with a light beam (through-beam pairs, retro-reflective, diffuse, background suppression and fiber-optic "
    "sensors, including laser photoelectric sensors; makers like Omron, SICK, Keyence, Autonics, Banner, "
    "Pepperl+Fuchs, Balluff, ifm, Leuze, Panasonic, Schneider, Datalogic, Wenglor, Baumer). "
    "false for inductive, capacitive and ultrasonic proximity sensors, light curtains and safety light curtains, "
    "PIR motion detectors, smoke detectors, hobby IR obstacle or LDR modules (e.g. for Arduino), reflectors or "
    "fiber cables sold on their own, and laser rangefinders. "
    "sensing_method: as written (e.g. through-beam, retro-reflective, polarized, diffuse, background suppression, "
    "fiber). sensing_range: the sensing distance exactly as written, with its unit (e.g. '0.1-2 m', '300 mm'). "
    "output: every output listed (e.g. NPN, PNP, NPN/PNP selectable, relay, push-pull, analog 4-20 mA, IO-Link). "
    "switching_mode: light-on, dark-on, or selectable, as written. light_source: e.g. red LED, infrared, laser. "
    "housing: e.g. M18 cylindrical, M12, rectangular. connection: cable, or the connector type (e.g. M12 4-pin). "
    "supply_min_v / supply_max_v: the supply voltage range (12-24 V DC -> 12 and 24). response_time: exactly as "
    "written, with its unit (e.g. '1 ms', '500 us'). ip_rating: as written, e.g. IP67. "
    "Report the price of a single unit."
)

# --- normalisation: loose LLM text -> the exact values our criteria use ---
# order matters: polarized before retro, retro before diffuse ("diffuse reflective" is not retro)
_METHOD = [
    (("polari",), "polarized retro-reflective"),
    (("retro", "reflector", "mirror"), "retro-reflective"),
    (("through", "thru", "opposed", "emitter", "transmitter"), "through-beam"),
    (("background", "bgs"), "background suppression"),
    (("fiber", "fibre"), "fiber optic"),
    (("diffuse", "proximity", "direct reflect"), "diffuse"),
]
_OUTPUT = [
    (r"\bnpn\b", "NPN"),
    (r"\bpnp\b", "PNP"),
    (r"relay|\bspdt\b", "Relay"),
    (r"push[- ]?pull", "Push-pull"),
    (r"analog(ue)?\b|4\s?(-|\.\.|to)\s?20\s?ma|0\s?(-|\.\.|to)\s?10\s?v\b", "Analog"),
    (r"io[- ]?link", "IO-Link"),
]
_SWITCHING = [
    (r"selectable|switchable|\bl\s?/\s?d\b|light\s?/\s?dark|light[- ]on\s*(/|or|and)\s*dark[- ]on", "both"),
    (r"light[- ]?on|\bl\.?\s?on\b|\blo\b", "light-on"),
    (r"dark[- ]?on|\bd\.?\s?on\b|\bdo\b", "dark-on"),
]
_LIGHT = [(("laser",), "laser"), (("infrared", "infra-red", " ir", "ir ", "880", "850", "940", "870"), "infrared"),
          (("blue",), "blue"), (("red",), "red")]
_CONNECTION = [(("m12",), "M12 connector"), (("m8",), "M8 connector"),
               (("cable", "lead", "pre-wired", "prewired", "wire"), "cable")]


def _switching(value) -> list[str]:
    found = pick_all(value or "", _SWITCHING)
    if "both" in found or {"light-on", "dark-on"} <= set(found):
        return ["light-on", "dark-on"]
    return found


def _housing(value) -> str | None:
    s = (value or "").lower()
    m = re.search(r"\bm\s?(8|12|18|30)\b", s)
    if m:
        return f"M{m.group(1)}"
    return "rectangular" if re.search(r"rectang|square|block|cubic|compact|miniature|box", s) else None


def normalize_photoelectric(raw: dict) -> tuple[dict, list[str]]:
    """Loose extraction -> PhotoelectricSpec fields, plus flags. Unknown values become None, never guessed."""
    output = pick_all(raw.get("output") or [], _OUTPUT)
    lo, hi = voltage_range(raw.get("supply_min_v"), raw.get("supply_max_v"))
    out = {
        "sensing_method": pick(raw.get("sensing_method"), _METHOD),
        "sensing_range_mm": length_mm(raw.get("sensing_range")),
        "output": output,
        "switching_mode": _switching(raw.get("switching_mode")),
        "light_source": pick(f" {raw.get('light_source') or ''} ", _LIGHT) if raw.get("light_source") else None,
        "housing": _housing(raw.get("housing")),
        "connection": pick(raw.get("connection"), _CONNECTION),
        "supply_min_v": lo,
        "supply_max_v": hi,
        "response_time_ms": time_ms(raw.get("response_time")),
        "ip_rating": ip_rating(raw.get("ip_rating")),
    }
    flags = []
    for name, field in [("sensing_method", "sensing_method"), ("sensing_range", "sensing_range_mm"),
                        ("light_source", "light_source"), ("housing", "housing"), ("connection", "connection"),
                        ("response_time", "response_time_ms"), ("ip_rating", "ip_rating")]:
        if raw.get(name) not in (None, "") and out[field] is None:
            flags.append(f"{name}: unrecognised value {raw[name]!r}")
    if raw.get("output") and not output:
        flags.append(f"output: unrecognised value {raw['output']!r}")
    return out, flags


# criteria field -> (product spec field, comparison, label)
PHOTOELECTRIC_CHECKS = {
    "sensing_method": ("sensing_method", equals, "Sensing method"),
    "min_sensing_range": ("sensing_range_mm", at_least, "Sensing distance"),
    "output": ("output", any_overlap, "Output"),
    "switching_mode": ("switching_mode", contains, "Light-on / dark-on"),
    "light_source": ("light_source", equals, "Light source"),
    "housing": ("housing", equals, "Housing"),
    "connection": ("connection", equals, "Connection"),
    "supply_voltage": (("supply_min_v", "supply_max_v"), within_range, "Supply voltage"),
    "max_response_time": ("response_time_ms", at_most, "Response time"),
    "min_ip": ("ip_rating", at_least, "IP rating"),
}
PHOTOELECTRIC_UNITS = {"min_sensing_range": "mm", "supply_voltage": "V", "max_response_time": "ms"}


PHOTOELECTRIC = DeviceDefinition(
    key="photoelectric",
    label="Photoelectric sensor",
    criteria_model=PhotoelectricCriteria,
    spec_model=PhotoelectricSpec,
    stub_spec=_stub_spec,
    extraction_model=PhotoelectricExtraction,
    extraction_hint=PHOTOELECTRIC_HINT,
    normalize=normalize_photoelectric,
    checks=PHOTOELECTRIC_CHECKS,
    units=PHOTOELECTRIC_UNITS,
    search_term="photoelectric sensor",
    search_hint=(
        "The buyer wants an industrial photoelectric sensor (through-beam, retro-reflective, diffuse or background "
        "suppression; makers such as Omron, SICK, Keyence, Autonics, Banner, Pepperl+Fuchs). Always say "
        "'photoelectric sensor' or 'photo sensor' in the query, or name a maker or series (e.g. Omron E3Z, "
        "Autonics BJ). Never write queries that would find proximity sensors, light curtains, PIR motion "
        "sensors or hobby IR modules."
    ),
    fields=[
        FieldDef(name="sensing_method", label="Sensing method", kind="select", search_word="",
                 options=list(get_args(SensingMethod))),
        FieldDef(name="min_sensing_range", label="Sensing distance", kind="number", unit="mm",
                 help="At least this far, e.g. 2000 for 2 m"),
        FieldDef(name="output", label="Output", kind="multiselect", options=list(get_args(Output)),
                 search_word="output"),
        FieldDef(name="switching_mode", label="Light-on / dark-on", kind="select", search_word="",
                 options=list(get_args(SwitchingMode)), help="Sensors with a selector count for either"),
        FieldDef(name="light_source", label="Light source", kind="select", search_word="", options=list(get_args(LightSource))),
        FieldDef(name="housing", label="Housing", kind="select", search_word="", options=list(get_args(Housing))),
        FieldDef(name="connection", label="Connection", kind="select", search_word="", options=list(get_args(Connection))),
        FieldDef(name="supply_voltage", label="Your supply voltage", kind="number", unit="V",
                 help="Kept when it falls inside the sensor's range"),
        FieldDef(name="max_response_time", label="Response time", kind="number", unit="ms",
                 help="At most, e.g. 1"),
        FieldDef(name="min_ip", label="IP rating", kind="number", help="e.g. 67 for IP67"),
        *SHARED_FIELDS,
    ],
)
