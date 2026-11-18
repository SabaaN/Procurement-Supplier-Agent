"""Rotary encoder (industrial, incremental or absolute) criteria, product spec and form definition."""
import math
import re
from typing import Literal, get_args

from pydantic import BaseModel, PositiveFloat, PositiveInt

from .base import SHARED_FIELDS, DeviceDefinition, FieldDef, ProductBase, Req, SharedCriteria
from .compare import any_overlap, at_least, at_most, equals, same_number, within_range

EncoderType = Literal["incremental", "absolute"]
ShaftType = Literal["solid", "hollow", "blind hollow"]
Output = Literal[
    "TTL (RS-422)", "HTL (push-pull)", "NPN open collector", "PNP", "Sin/Cos 1 Vpp",
    "SSI", "BiSS", "CANopen", "PROFINET", "EtherCAT", "EtherNet/IP", "Analog",
]


class EncoderCriteria(SharedCriteria):
    """What the buyer asks for. Every spec is optional and carries its own level."""

    encoder_type: Req[EncoderType] | None = None
    min_ppr: Req[PositiveInt] | None = None  # incremental: pulses per revolution
    min_resolution_bits: Req[PositiveInt] | None = None  # absolute: single-turn resolution
    multiturn: Req[bool] | None = None  # absolute: counts whole turns too
    output: Req[list[Output]] | None = None  # any of these
    shaft_type: Req[ShaftType] | None = None
    shaft_diameter: Req[PositiveFloat] | None = None  # mm; the bore for hollow shafts
    max_housing_diameter: Req[PositiveFloat] | None = None  # mm: must fit the space
    supply_voltage: Req[PositiveFloat] | None = None  # V: the buyer's supply, must be in the encoder's range
    min_rpm: Req[PositiveInt] | None = None  # maximum speed the encoder must handle
    min_ip: Req[PositiveInt] | None = None  # 65 for IP65


class EncoderSpec(ProductBase):
    """What was extracted from a product page. Every spec is nullable: not on page -> None."""

    encoder_type: EncoderType | None = None
    ppr: int | None = None
    resolution_bits: int | None = None
    multiturn: bool | None = None
    output: list[Output] = []
    shaft_type: ShaftType | None = None
    shaft_diameter_mm: float | None = None
    housing_diameter_mm: float | None = None
    supply_min_v: float | None = None
    supply_max_v: float | None = None
    max_rpm: int | None = None
    ip_rating: int | None = None
    extra_specs: dict[str, str] = {}


def _stub_spec(i: int, url: str) -> EncoderSpec:
    """Fake product for pipeline tests (no Groq)."""
    return EncoderSpec(
        title=f"Stub encoder {i + 1}",
        supplier="stub-supplier",
        source_url=url,
        price=12000 + 4000 * i,
        currency="PKR",
        encoder_type="incremental" if i % 2 == 0 else "absolute",
        ppr=[1024, 2500, None][i % 3],
        resolution_bits=None if i % 2 == 0 else 13,
        output=[["TTL (RS-422)"], ["HTL (push-pull)"], ["SSI"]][i % 3],
        shaft_type="solid" if i % 2 == 0 else "hollow",
        shaft_diameter_mm=[6.0, 10.0, 8.0][i % 3],
        housing_diameter_mm=[58.0, 50.0, 38.0][i % 3],
        supply_min_v=[10.0, 5.0, 4.75][i % 3],
        supply_max_v=[30.0, 5.0, 30.0][i % 3],
        max_rpm=6000,
        ip_rating=[65, 64, 67][i % 3],
    )


class EncoderExtraction(BaseModel):
    """What the LLM fills in from one page. Deliberately loose: Python normalises it."""

    is_product_page: bool
    is_listing_page: bool = False
    is_right_device_type: bool | None = None  # see ENCODER_HINT: an industrial rotary encoder
    title: str | None = None
    supplier: str | None = None
    part_number: str | None = None
    price: float | None = None
    currency: str | None = None
    moq: int | None = None
    encoder_type: str | None = None
    ppr: int | None = None
    resolution_bits: int | None = None
    singleturn_steps: int | None = None  # e.g. 8192 positions per turn, when bits aren't given
    multiturn: bool | None = None
    output: list[str] = []
    shaft_type: str | None = None
    shaft_diameter_mm: float | None = None
    housing_diameter_mm: float | None = None
    supply_min_v: float | None = None
    supply_max_v: float | None = None
    max_rpm: int | None = None
    ip_rating: str | None = None


ENCODER_HINT = (
    "Industrial rotary encoder. is_right_device_type: true for industrial rotary encoders (incremental or "
    "absolute, solid-shaft or hollow-shaft, for motors, conveyors and machine automation; makers like Kubler, "
    "SICK, Omron, Autonics, Baumer, Heidenhain, Pepperl+Fuchs, Hengstler, Lika, Eltra, Koyo, Wachendorff). "
    "false for video or audio encoders (H.264/HDMI/IP streaming), hobby or panel rotary knobs (e.g. KY-040, "
    "EC11 modules), linear encoders, magnetic tape scales and motors sold with a built-in encoder. "
    "encoder_type: incremental or absolute. ppr: pulses per revolution (also called lines, counts or "
    "resolution) for incremental encoders. resolution_bits: single-turn resolution in bits for absolute "
    "encoders; if the page gives positions or steps per turn instead, put that number in singleturn_steps. "
    "multiturn: true for multi-turn absolute encoders. output: every output or interface listed (e.g. TTL, "
    "RS-422, HTL, push-pull, NPN, open collector, PNP, sin/cos, SSI, BiSS, CANopen, PROFINET, EtherCAT). "
    "shaft_type: solid, hollow (through) or blind hollow. shaft_diameter_mm: the shaft or bore diameter in mm. "
    "housing_diameter_mm: the body diameter in mm. supply_min_v / supply_max_v: the supply voltage range "
    "(5 V only -> both 5). max_rpm: the maximum speed. ip_rating: as written, e.g. IP65. "
    "Report the price of a single unit."
)

# --- normalisation: loose LLM text -> the exact values our criteria use ---
_TYPE = [(("absolute",), "absolute"), (("incremental", "quadrature"), "incremental")]
# order matters: "blind hollow" before "hollow", "hollow" before "solid shaft"
_SHAFT = [(("blind", "hub", "semi-hollow", "semi hollow"), "blind hollow"),
          (("hollow", "through bore", "through-bore", "bore"), "hollow"),
          (("solid", "shaft"), "solid")]
# whole-word patterns: short names like "ssi" or "sin" must not match inside "classic" or "single"
_OUTPUT = [
    (r"\bttl\b|rs[- ]?422|line[- ]?driver", "TTL (RS-422)"),
    (r"\bhtl\b|push[- ]?pull|totem", "HTL (push-pull)"),
    (r"\bnpn\b|open[- ]?collector|\bo\.?c\.?(?=\W|$)", "NPN open collector"),
    (r"\bpnp\b", "PNP"),
    (r"\bsin(e|/cos|-cos|cos)?\b|\b1\s?vpp\b", "Sin/Cos 1 Vpp"),
    (r"\bssi\b", "SSI"),
    (r"\bbiss\b", "BiSS"),
    (r"canopen", "CANopen"),
    (r"profinet", "PROFINET"),
    (r"ethercat", "EtherCAT"),
    (r"ethernet\s?/?\s?ip\b", "EtherNet/IP"),
    (r"\banalog(ue)?\b|\b4\s?(-|\.\.|to)\s?20\s?ma\b|\b0\s?(-|\.\.|to)\s?10\s?v\b", "Analog"),
]


def _pick(value, rules):
    """The first canonical value whose words appear in the text (rules are ordered), else None."""
    s = (value or "").lower()
    return next((canon for needles, canon in rules if any(n in s for n in needles)), None)


def _number(value, low, high):
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and low < value <= high
    return value if ok else None


def _outputs(items):
    found = []
    for item in items:
        s = str(item).lower()
        for pattern, canon in _OUTPUT:
            if re.search(pattern, s) and canon not in found:
                found.append(canon)
    return found


def _ip(value):
    m = re.search(r"ip\s*-?\s*(\d)\s*(\d)", (value or "").lower())
    return int(m.group(1) + m.group(2)) if m else None


def normalize_encoder(raw: dict) -> tuple[dict, list[str]]:
    """Loose extraction -> EncoderSpec fields, plus flags. Unknown values become None, never guessed."""
    bits = _number(raw.get("resolution_bits"), 0, 40)
    steps = _number(raw.get("singleturn_steps"), 1, 2**40)
    if bits is None and steps and math.log2(steps).is_integer():
        bits = int(math.log2(steps))  # 8192 steps -> 13 bits: arithmetic in Python, not by the model
    lo, hi = _number(raw.get("supply_min_v"), 0, 60), _number(raw.get("supply_max_v"), 0, 60)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo

    out = {
        "encoder_type": _pick(raw.get("encoder_type"), _TYPE),
        "ppr": int(p) if (p := _number(raw.get("ppr"), 0, 10_000_000)) else None,
        "resolution_bits": int(bits) if bits else None,
        "multiturn": raw.get("multiturn"),
        "output": _outputs(raw.get("output") or []),
        "shaft_type": _pick(raw.get("shaft_type"), _SHAFT),
        "shaft_diameter_mm": _number(raw.get("shaft_diameter_mm"), 0, 200),
        "housing_diameter_mm": _number(raw.get("housing_diameter_mm"), 0, 500),
        "supply_min_v": lo,
        "supply_max_v": hi,
        "max_rpm": int(r) if (r := _number(raw.get("max_rpm"), 0, 200_000)) else None,
        "ip_rating": _ip(raw.get("ip_rating")),
    }
    # an encoder with a single-turn bit resolution is absolute, whatever the wording
    if out["encoder_type"] is None and out["resolution_bits"]:
        out["encoder_type"] = "absolute"

    flags = []
    for name in ("encoder_type", "shaft_type", "ip_rating"):
        if raw.get(name) not in (None, "") and out[name] is None:
            flags.append(f"{name}: unrecognised value {raw[name]!r}")
    if raw.get("output") and not out["output"]:
        flags.append(f"output: unrecognised value {raw['output']!r}")
    return out, flags


# criteria field -> (product spec field, comparison, label)
ENCODER_CHECKS = {
    "encoder_type": ("encoder_type", equals, "Encoder type"),
    "min_ppr": ("ppr", at_least, "Resolution (PPR)"),
    "min_resolution_bits": ("resolution_bits", at_least, "Resolution (bits)"),
    "multiturn": ("multiturn", equals, "Multi-turn"),
    "output": ("output", any_overlap, "Output"),
    "shaft_type": ("shaft_type", equals, "Shaft type"),
    "shaft_diameter": ("shaft_diameter_mm", same_number, "Shaft / bore diameter"),
    "max_housing_diameter": ("housing_diameter_mm", at_most, "Housing diameter"),
    "supply_voltage": (("supply_min_v", "supply_max_v"), within_range, "Supply voltage"),
    "min_rpm": ("max_rpm", at_least, "Max speed"),
    "min_ip": ("ip_rating", at_least, "IP rating"),
}
ENCODER_UNITS = {
    "min_ppr": "PPR", "min_resolution_bits": "bit", "shaft_diameter": "mm", "max_housing_diameter": "mm",
    "supply_voltage": "V", "min_rpm": "rpm",
}


ENCODER = DeviceDefinition(
    key="encoder",
    label="Encoder",
    criteria_model=EncoderCriteria,
    spec_model=EncoderSpec,
    stub_spec=_stub_spec,
    extraction_model=EncoderExtraction,
    extraction_hint=ENCODER_HINT,
    normalize=normalize_encoder,
    checks=ENCODER_CHECKS,
    units=ENCODER_UNITS,
    search_term="industrial rotary encoder",
    search_hint=(
        "The buyer wants an industrial rotary encoder (incremental or absolute; solid or hollow shaft; makers "
        "such as Kubler, SICK, Omron, Autonics, Baumer, Heidenhain, Pepperl+Fuchs). Always say 'rotary encoder', "
        "'incremental encoder' or 'absolute encoder' in the query, or name a maker. Never write queries that "
        "would find video encoders, streaming encoders, hobby rotary knobs (KY-040, EC11) or linear encoders."
    ),
    fields=[
        FieldDef(name="encoder_type", label="Encoder type", kind="select", options=list(get_args(EncoderType))),
        FieldDef(name="min_ppr", label="Resolution", kind="number", unit="PPR",
                 help="Pulses per revolution (incremental encoders)"),
        FieldDef(name="min_resolution_bits", label="Single-turn resolution", kind="number", unit="bit",
                 help="Absolute encoders, e.g. 13 bit = 8192 positions"),
        FieldDef(name="multiturn", label="Multi-turn", kind="toggle", help="Absolute encoders that count turns"),
        FieldDef(name="output", label="Output / interface", kind="multiselect", options=list(get_args(Output))),
        FieldDef(name="shaft_type", label="Shaft type", kind="select", options=list(get_args(ShaftType))),
        FieldDef(name="shaft_diameter", label="Shaft / bore diameter", kind="number", unit="mm"),
        FieldDef(name="max_housing_diameter", label="Housing diameter", kind="number", unit="mm",
                 help="The most it can be, e.g. 58 for a 58 mm space"),
        FieldDef(name="supply_voltage", label="Your supply voltage", kind="number", unit="V",
                 help="Kept when it falls inside the encoder's range"),
        FieldDef(name="min_rpm", label="Max speed", kind="number", unit="rpm"),
        FieldDef(name="min_ip", label="IP rating", kind="number", help="e.g. 65 for IP65"),
        *SHARED_FIELDS,
    ],
)
