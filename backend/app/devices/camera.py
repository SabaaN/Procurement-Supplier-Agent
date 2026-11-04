"""Camera (machine vision / industrial) criteria, product spec and form definition."""
from typing import Literal, get_args

from pydantic import PositiveFloat, PositiveInt
import re
from typing import Literal, get_args

from pydantic import BaseModel, PositiveFloat, PositiveInt

from .base import (
    SHARED_FIELDS,
    DeviceDefinition,
    FieldDef,
    ProductBase,
    Req,
    SharedCriteria,
)

Shutter = Literal["global", "rolling"]
Colour = Literal["colour", "mono"]
ScanType = Literal["area", "line"]
Interface = Literal["GigE", "10GigE", "USB3", "CoaxPress", "Camera Link"]
LensMount = Literal["C", "CS", "S", "F", "M42"]
SensorFormat = Literal['1/2.8"', '1/1.8"', '2/3"', '1"', '1.1"']


class CameraCriteria(SharedCriteria):
    """What the buyer asks for. Every spec is optional and carries its own required flag."""

    min_megapixels: Req[PositiveFloat] | None = None
    min_fps: Req[PositiveFloat] | None = None  # at full resolution
    shutter: Req[Shutter] | None = None
    colour: Req[Colour] | None = None
    scan_type: Req[ScanType] | None = None
    sensor_format: Req[list[SensorFormat]] | None = None  # any of these
    interface: Req[list[Interface]] | None = None  # any of these
    lens_mount: Req[list[LensMount]] | None = None  # any of these
    min_bit_depth: Req[PositiveInt] | None = None
    hardware_trigger: Req[bool] | None = None


class CameraSpec(ProductBase):
    """What was extracted from a product page. Every spec is nullable: not on page -> None."""

    megapixels: float | None = None
    fps: float | None = None  # at full resolution
    shutter: Shutter | None = None
    colour: Colour | None = None
    scan_type: ScanType | None = None
    sensor_format: SensorFormat | None = None
    interface: list[Interface] = []
    lens_mount: LensMount | None = None
    bit_depth: int | None = None
    hardware_trigger: bool | None = None
    extra_specs: dict[str, str] = {}  # anything else found on the page


def _stub_spec(i: int, url: str) -> CameraSpec:
    """Fake product for pipeline testing. Replaced by LLM extraction in a later step."""
    return CameraSpec(
        title=f"Stub camera {i + 1}",
        supplier="stub-supplier",
        source_url=url,
        price=8000 + 3000 * i,
        currency="PKR",
        megapixels=[2.3, 5.0, 12.0][i % 3],
        fps=[60.0, 30.0, 20.0][i % 3],
        shutter="global" if i % 2 == 0 else "rolling",
        interface=["GigE"],
        lens_mount="C",
    )

class CameraExtraction(BaseModel):
    """What the LLM fills in from one page. Deliberately loose (plain strings): Python normalises it."""

    is_product_page: bool
    title: str | None = None
    supplier: str | None = None
    part_number: str | None = None
    price: float | None = None
    currency: str | None = None
    moq: int | None = None
    megapixels: float | None = None
    width_px: int | None = None
    height_px: int | None = None
    fps: float | None = None
    shutter: str | None = None
    colour: str | None = None
    scan_type: str | None = None
    sensor_format: str | None = None
    interface: list[str] = []
    lens_mount: str | None = None
    bit_depth: int | None = None
    hardware_trigger: bool | None = None


CAMERA_HINT = (
    "Machine-vision / industrial camera. megapixels: sensor resolution in MP as stated; if the page only gives "
    "pixel dimensions, fill width_px and height_px instead and leave megapixels null. fps: the maximum frame "
    "rate at full resolution. shutter: global or rolling, as written. interface: every data interface listed "
    "(e.g. GigE, USB3, CoaxPress, Camera Link). lens_mount: e.g. C, CS, S, F, M42. sensor_format: the optical "
    "format, e.g. 1/1.8\". Report the price of a single unit."
)

# --- normalisation: loose LLM text -> the exact values our criteria use ---
_SHUTTER = [(("global",), "global"), (("rolling",), "rolling")]
_COLOUR = [(("mono", "black"), "mono"), (("colour", "color", "rgb", "bayer"), "colour")]
_SCAN = [(("line",), "line"), (("area",), "area")]
# order matters: 10GigE must be tested before GigE
_INTERFACE = [
    (("10gige", "10gbe", "10g"), "10GigE"),
    (("gige", "gig-e", "gigabit", "gbe"), "GigE"),
    (("coaxpress", "cxp"), "CoaxPress"),
    (("cameralink",), "Camera Link"),
]
_LENS = {"c": "C", "cs": "CS", "s": "S", "m12": "S", "f": "F", "m42": "M42"}
_FORMATS = {"1/2.8": '1/2.8"', "1/1.8": '1/1.8"', "2/3": '2/3"', "1": '1"', "1.1": '1.1"'}


def _pick(value, rules):
    """The canonical value if the text matches exactly one rule, else None."""
    s = (value or "").lower()
    hits = {canon for needles, canon in rules if any(n in s for n in needles)}
    return hits.pop() if len(hits) == 1 else None


def _number(value, low, high):
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and low < value <= high
    return value if ok else None


def _interfaces(items):
    found = []
    for item in items:
        for part in re.split(r"[,;/+]", item):
            s = re.sub(r"[\s_]", "", part.lower())
            if not s:
                continue
            if "usb" in s and "3" in s:
                canon = "USB3"
            else:
                canon = next((c for needles, c in _INTERFACE if any(n in s for n in needles)), None)
            if canon and canon not in found:
                found.append(canon)
    return found


def normalize_camera(raw: dict) -> tuple[dict, list[str]]:
    """Loose extraction -> CameraSpec fields, plus flags. Unknown values become None, never guessed."""
    mp = _number(raw.get("megapixels"), 0, 500)
    w, h = raw.get("width_px"), raw.get("height_px")
    if mp is None and raw.get("megapixels") is None and w and h:
        mp = _number(round(w * h / 1_000_000, 2), 0, 500)  # arithmetic in Python, not by the model
    depth = _number(raw.get("bit_depth"), 0, 32)

    out = {
        "megapixels": mp,
        "fps": _number(raw.get("fps"), 0, 100_000),
        "shutter": _pick(raw.get("shutter"), _SHUTTER),
        "colour": _pick(raw.get("colour"), _COLOUR),
        "scan_type": _pick(raw.get("scan_type"), _SCAN),
        "sensor_format": _FORMATS.get(re.sub(r"[^0-9/.]", "", raw.get("sensor_format") or "")),
        "interface": _interfaces(raw.get("interface") or []),
        "lens_mount": _LENS.get(re.sub(r"[^a-z0-9]", "", (raw.get("lens_mount") or "").lower()).replace("mount", "")),
        "bit_depth": int(depth) if depth else None,
        "hardware_trigger": raw.get("hardware_trigger"),
    }
    flags = []
    for name in ("megapixels", "fps", "shutter", "colour", "scan_type", "sensor_format", "lens_mount", "bit_depth"):
        if raw.get(name) not in (None, "") and out[name] is None:
            flags.append(f"{name}: unrecognised value {raw[name]!r}")
    if raw.get("interface") and not out["interface"]:
        flags.append(f"interface: unrecognised value {raw['interface']!r}")
    return out, flags

CAMERA = DeviceDefinition(
    key="camera",
    label="Camera",
    criteria_model=CameraCriteria,
    spec_model=CameraSpec,
    stub_spec=_stub_spec,
    extraction_model=CameraExtraction,
    extraction_hint=CAMERA_HINT,
    normalize=normalize_camera,
    fields=[
        FieldDef(name="min_megapixels", label="Resolution", kind="number", unit="MP"),
        FieldDef(
            name="min_fps",
            label="Frame rate",
            kind="number",
            unit="fps",
            help="At full resolution",
        ),
        FieldDef(name="shutter", label="Shutter type", kind="select", options=list(get_args(Shutter))),
        FieldDef(name="colour", label="Colour", kind="select", options=list(get_args(Colour))),
        FieldDef(name="scan_type", label="Scan type", kind="select", options=list(get_args(ScanType))),
        FieldDef(name="sensor_format", label="Sensor format", kind="multiselect", options=list(get_args(SensorFormat))),
        FieldDef(name="interface", label="Interface", kind="multiselect", options=list(get_args(Interface))),
        FieldDef(name="lens_mount", label="Lens mount", kind="multiselect", options=list(get_args(LensMount))),
        FieldDef(name="min_bit_depth", label="Bit depth", kind="number", unit="bit"),
        FieldDef(name="hardware_trigger", label="Hardware trigger", kind="toggle"),
        *SHARED_FIELDS,
    ],
)
