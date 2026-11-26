"""PLC (programmable logic controller) criteria, product spec and form definition."""
import re
from typing import Literal, get_args

from pydantic import BaseModel, NonNegativeInt, PositiveFloat, PositiveInt

from .base import SHARED_FIELDS, DeviceDefinition, FieldDef, ProductBase, Req, SharedCriteria
from .compare import all_of, any_overlap, at_least, contains, equals
from .parse import frequency_khz, number, pick, pick_all

Brand = Literal[
    "Siemens", "Mitsubishi", "Allen-Bradley", "Omron", "Delta", "Schneider", "Keyence", "Panasonic", "LS",
    "Fatek", "Unitronics", "Beckhoff", "ABB", "Inovance", "Xinje", "Wecon", "IDEC", "AutomationDirect",
]
PlcType = Literal["compact", "modular", "micro"]
OutputType = Literal["relay", "transistor (sink / NPN)", "transistor (source / PNP)"]
Supply = Literal["24 V DC", "12 V DC", "100–240 V AC"]
Comm = Literal[
    "Ethernet", "PROFINET", "EtherNet/IP", "Modbus TCP", "Modbus RTU", "RS-485", "RS-232", "USB",
    "CANopen", "EtherCAT", "PROFIBUS",
]


class PlcCriteria(SharedCriteria):
    """What the buyer asks for. Every spec is optional and carries its own level."""

    plc_type: Req[PlcType] | None = None
    min_digital_inputs: Req[PositiveInt] | None = None
    min_digital_outputs: Req[PositiveInt] | None = None
    output_type: Req[list[OutputType]] | None = None  # any of these
    min_analog_inputs: Req[PositiveInt] | None = None
    min_analog_outputs: Req[PositiveInt] | None = None
    supply: Req[Supply] | None = None
    communication: Req[list[Comm]] | None = None  # all of these
    min_hsc_khz: Req[PositiveFloat] | None = None  # fastest high-speed counter input
    min_pulse_axes: Req[PositiveInt] | None = None  # pulse-train outputs for steppers / servos
    expandable: Req[bool] | None = None


class PlcSpec(ProductBase):
    """What was extracted from a product page. Every spec is nullable: not on page -> None."""

    brand: Brand | None = None  # read off the page and shown in results; not a search requirement
    series: str | None = None  # e.g. S7-1200, FX5U, DVP-SS2: shown, not checked
    plc_type: PlcType | None = None
    digital_inputs: NonNegativeInt | None = None
    digital_outputs: NonNegativeInt | None = None
    output_type: list[OutputType] = []
    analog_inputs: NonNegativeInt | None = None
    analog_outputs: NonNegativeInt | None = None
    supply: list[Supply] = []
    communication: list[Comm] = []
    hsc_khz: float | None = None
    pulse_axes: NonNegativeInt | None = None
    expandable: bool | None = None
    extra_specs: dict[str, str] = {}


def _stub_spec(i: int, url: str) -> PlcSpec:
    """Fake product for pipeline tests (no Groq)."""
    return PlcSpec(
        title=f"Stub PLC {i + 1}",
        supplier="stub-supplier",
        source_url=url,
        price=45000 + 30000 * i,
        currency="PKR",
        brand=["Siemens", "Delta", "Mitsubishi"][i % 3],
        series=["S7-1200", "DVP-SS2", "FX5U"][i % 3],
        plc_type="compact",
        digital_inputs=[14, 8, 16][i % 3],
        digital_outputs=[10, 6, 16][i % 3],
        output_type=[["transistor (source / PNP)"], ["relay"], ["transistor (sink / NPN)"]][i % 3],
        analog_inputs=[2, 0, 0][i % 3],
        analog_outputs=[0, 0, 0][i % 3],
        supply=[["24 V DC"], ["24 V DC"], ["100–240 V AC"]][i % 3],
        communication=[["Ethernet", "PROFINET"], ["RS-485", "Modbus RTU"], ["Ethernet", "RS-485", "USB"]][i % 3],
        hsc_khz=[100.0, 20.0, 200.0][i % 3],
        pulse_axes=[4, 2, 4][i % 3],
        expandable=True,
    )


class PlcExtraction(BaseModel):
    """What the LLM fills in from one page. Deliberately loose: Python normalises it."""

    is_product_page: bool
    is_listing_page: bool = False
    is_right_device_type: bool | None = None  # see PLC_HINT
    title: str | None = None
    supplier: str | None = None
    part_number: str | None = None
    price: float | None = None
    currency: str | None = None
    moq: int | None = None
    brand: str | None = None
    series: str | None = None
    plc_type: str | None = None
    digital_inputs: int | None = None
    digital_outputs: int | None = None
    output_type: str | None = None  # as written: "relay", "transistor (sink)", "PNP"
    analog_inputs: int | None = None
    analog_outputs: int | None = None
    supply: str | None = None  # as written: "24 V DC", "100-240 V AC"
    communication: list[str] | None = None  # null allowed: models write null for 'none found'
    high_speed_counter: str | None = None  # as written, with its unit: "6 x 100 kHz"
    pulse_axes: int | None = None
    expandable: bool | None = None


PLC_HINT = (
    "PLC (programmable logic controller). is_right_device_type: true for PLCs and PLC CPUs, including compact "
    "'brick' PLCs, modular CPUs, micro/nano PLCs and controllers with a built-in display that run PLC programs "
    "(e.g. Siemens S7-1200/1500/LOGO!, Mitsubishi FX/iQ-R, Allen-Bradley Micro800/CompactLogix, Omron CP/NX, "
    "Delta DVP/AS, Schneider Modicon, Unitronics). false for I/O or expansion modules sold on their own, "
    "communication modules, HMI touch panels without a controller, programming cables, software licences, "
    "VFDs, servo drives, relays, power supplies, and hobby boards (Arduino, Raspberry Pi) not sold as an "
    "industrial PLC. brand: the maker. series: the family, e.g. S7-1200, FX5U, DVP-SS2. plc_type: compact, "
    "modular or micro, as written. digital_inputs / digital_outputs / analog_inputs / analog_outputs: the built-in "
    "counts on the CPU itself, not with expansion. output_type: as written (relay, transistor sink/NPN, "
    "transistor source/PNP). supply: the power supply as written, e.g. 24 V DC or 100-240 V AC. communication: "
    "every built-in port or protocol (e.g. Ethernet, PROFINET, Modbus TCP/RTU, RS-485, RS-232, USB). "
    "high_speed_counter: the high-speed counter inputs exactly as written, with the unit (e.g. '6 x 100 kHz'). "
    "pulse_axes: the number of pulse-train (PTO) outputs or axes. expandable: true if expansion modules can be "
    "added. Report the price of a single unit."
)

# --- normalisation: loose LLM text -> the exact values our criteria use ---
_BRAND = [
    (r"siemens|simatic|\bs7-?\d|\blogo!?\b", "Siemens"),
    (r"mitsubishi|melsec|\bfx\d", "Mitsubishi"),
    (r"allen[- ]?bradley|rockwell|micrologix|compactlogix|controllogix|micro8[0-9]0", "Allen-Bradley"),
    (r"omron|sysmac", "Omron"),
    (r"\bdelta\b|\bdvp\b", "Delta"),
    (r"schneider|modicon|telemecanique", "Schneider"),
    (r"keyence", "Keyence"),
    (r"panasonic", "Panasonic"),
    (r"\bls\b(?! ?[0-9])|\blsis\b|ls electric|\bxgb\b|\bxgt\b", "LS"),
    (r"fatek", "Fatek"),
    (r"unitronics", "Unitronics"),
    (r"beckhoff", "Beckhoff"),
    (r"\babb\b", "ABB"),
    (r"inovance", "Inovance"),
    (r"xinje", "Xinje"),
    (r"wecon", "Wecon"),
    (r"\bidec\b", "IDEC"),
    (r"automationdirect|automation direct|\bkoyo\b|\bclick plc\b", "AutomationDirect"),
]
_TYPE = [(("modular", "rack", "backplane"), "modular"), (("micro", "nano", "pico", "mini"), "micro"),
         (("compact", "brick", "all-in-one", "all in one", "integrated"), "compact")]
_OUTPUT = [
    (r"relay", "relay"),
    (r"sink|\bnpn\b", "transistor (sink / NPN)"),
    (r"source|sourcing|\bpnp\b", "transistor (source / PNP)"),
]
_COMM = [
    (r"profinet", "PROFINET"),
    (r"ethernet\s?/\s?ip|ethernetip", "EtherNet/IP"),
    (r"modbus[\s/-]?tcp", "Modbus TCP"),
    (r"modbus[\s/-]?rtu|modbus(?![\s/-]?tcp)", "Modbus RTU"),
    (r"ethercat", "EtherCAT"),
    (r"canopen|\bcan\b", "CANopen"),
    (r"profibus", "PROFIBUS"),
    (r"rs[\s-]?485", "RS-485"),
    (r"rs[\s-]?232", "RS-232"),
    (r"\busb\b", "USB"),
    (r"ethernet(?!\s?/\s?ip)|\brj-?45\b|\blan\b|\btcp/ip\b", "Ethernet"),
]


def _supply(value) -> list[str]:
    s = str(value or "").lower().replace(" ", "")
    found = []
    if re.search(r"ac|~|mains", s) and re.search(r"(8[5-9]|9\d|1[0-2]\d|2[0-6]\d)", s):
        found.append("100–240 V AC")
    if re.search(r"dc", s):
        found.append("12 V DC" if re.search(r"(?<!\d)12(?!\d)", s) and not re.search(r"(?<!\d)24(?!\d)", s)
                     else "24 V DC")
    return found


def normalize_plc(raw: dict) -> tuple[dict, list[str]]:
    """Loose extraction -> PlcSpec fields, plus flags. Unknown values become None, never guessed."""
    brand = pick_all(raw.get("brand") or "", _BRAND) or pick_all(raw.get("title") or "", _BRAND)

    def count(name):
        v = number(raw.get(name), -1, 10_000)
        return int(v) if v is not None else None

    out = {
        "brand": brand[0] if brand else None,
        "series": (raw.get("series") or "").strip()[:60] or None,
        "plc_type": pick(raw.get("plc_type"), _TYPE),
        "digital_inputs": count("digital_inputs"),
        "digital_outputs": count("digital_outputs"),
        "output_type": pick_all(raw.get("output_type") or "", _OUTPUT),
        "analog_inputs": count("analog_inputs"),
        "analog_outputs": count("analog_outputs"),
        "supply": _supply(raw.get("supply")),
        "communication": pick_all(raw.get("communication") or [], _COMM),
        "hsc_khz": frequency_khz(raw.get("high_speed_counter")),
        "pulse_axes": count("pulse_axes"),
        "expandable": raw.get("expandable"),
    }
    flags = []
    if raw.get("output_type") and "transistor" in str(raw["output_type"]).lower() and not any(
            o.startswith("transistor") for o in out["output_type"]):
        flags.append("transistor outputs: sink or source not stated")
    for name, field in [("brand", "brand"), ("plc_type", "plc_type"), ("supply", "supply"),
                        ("high_speed_counter", "hsc_khz")]:
        if raw.get(name) not in (None, "") and not out[field]:
            flags.append(f"{name}: unrecognised value {raw[name]!r}")
    if raw.get("communication") and not out["communication"]:
        flags.append(f"communication: unrecognised value {raw['communication']!r}")
    return out, flags


# criteria field -> (product spec field, comparison, label)
PLC_CHECKS = {
    "plc_type": ("plc_type", equals, "PLC type"),
    "min_digital_inputs": ("digital_inputs", at_least, "Digital inputs"),
    "min_digital_outputs": ("digital_outputs", at_least, "Digital outputs"),
    "output_type": ("output_type", any_overlap, "Output type"),
    "min_analog_inputs": ("analog_inputs", at_least, "Analog inputs"),
    "min_analog_outputs": ("analog_outputs", at_least, "Analog outputs"),
    "supply": ("supply", contains, "Supply"),
    "communication": ("communication", all_of, "Communication"),
    "min_hsc_khz": ("hsc_khz", at_least, "High-speed counter"),
    "min_pulse_axes": ("pulse_axes", at_least, "Pulse outputs"),
    "expandable": ("expandable", equals, "Expandable"),
}
PLC_UNITS = {
    "min_digital_inputs": "DI", "min_digital_outputs": "DO", "min_analog_inputs": "AI", "min_analog_outputs": "AO",
    "min_hsc_khz": "kHz", "min_pulse_axes": "axes",
}


PLC = DeviceDefinition(
    key="plc",
    label="PLC",
    criteria_model=PlcCriteria,
    spec_model=PlcSpec,
    stub_spec=_stub_spec,
    extraction_model=PlcExtraction,
    extraction_hint=PLC_HINT,
    normalize=normalize_plc,
    checks=PLC_CHECKS,
    units=PLC_UNITS,
    search_term="PLC",
    page_words=("plc", "programmable logic", "programmable controller", "digital input", "digital output",
                "di/do", "i/o", "ladder", "cpu"),
    search_hint=(
        "The buyer wants a PLC (programmable logic controller) CPU, from any maker. Always say 'PLC' in the query; "
        "don't restrict it to one brand. Common PLC families (e.g. Siemens S7-1200, Mitsubishi FX5U, Delta DVP, "
        "Allen-Bradley Micro800, Omron CP1E) are fine as examples across makers. Never write queries that would "
        "find I/O or expansion modules on their own, HMI panels, programming cables, VFDs or Arduino boards."
    ),
    fields=[
        FieldDef(name="plc_type", label="PLC type", kind="select", options=list(get_args(PlcType)), search_word=""),
        FieldDef(name="min_digital_inputs", label="Digital inputs", kind="number", unit="DI",
                 help="Built into the CPU, at least"),
        FieldDef(name="min_digital_outputs", label="Digital outputs", kind="number", unit="DO",
                 help="Built into the CPU, at least"),
        FieldDef(name="output_type", label="Output type", kind="multiselect", options=list(get_args(OutputType)),
                 search_word="output", help="Any of these"),
        FieldDef(name="min_analog_inputs", label="Analog inputs", kind="number", unit="AI"),
        FieldDef(name="min_analog_outputs", label="Analog outputs", kind="number", unit="AO"),
        FieldDef(name="supply", label="Power supply", kind="select", options=list(get_args(Supply)), search_word=""),
        FieldDef(name="communication", label="Communication", kind="multiselect", options=list(get_args(Comm)),
                 search_word="", help="All of these, built in"),
        FieldDef(name="min_hsc_khz", label="High-speed counter", kind="number", unit="kHz",
                 help="Fastest counter input, e.g. 100 for an encoder"),
        FieldDef(name="min_pulse_axes", label="Pulse outputs", kind="number", unit="axes",
                 help="For stepper or servo drives"),
        FieldDef(name="expandable", label="Expandable", kind="toggle", help="Takes expansion modules"),
        *SHARED_FIELDS,
    ],
)
