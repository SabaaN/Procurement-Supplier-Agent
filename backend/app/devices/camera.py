"""Camera (machine vision / industrial) criteria, product spec and form definition."""
from typing import Literal, get_args

from pydantic import PositiveFloat, PositiveInt

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


CAMERA = DeviceDefinition(
    key="camera",
    label="Camera",
    criteria_model=CameraCriteria,
    spec_model=CameraSpec,
    stub_spec=_stub_spec,
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
