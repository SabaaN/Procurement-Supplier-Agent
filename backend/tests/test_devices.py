import pytest
from pydantic import ValidationError

from app.devices import UnsupportedDevice, get_device, list_devices
from app.devices.camera import CameraCriteria, CameraSpec


def test_valid_camera_criteria():
    c = CameraCriteria.model_validate(
        {
            "min_megapixels": {"value": 5, "required": True},
            "shutter": {"value": "global", "required": True},
            "interface": {"value": ["GigE", "USB3"]},
            "budget_max": 20000,
        }
    )
    assert c.min_megapixels.required is True
    assert c.interface.required is False  # default: preferred, not required
    assert c.quantity == 1 and c.currency == "PKR"


@pytest.mark.parametrize(
    "bad",
    [
        {"shutter": {"value": "electronic"}},  # not a known shutter type
        {"min_megapixels": {"value": -2}},  # must be positive
        {"interface": {"value": ["FireWire"]}},  # not a known interface
        {"budget_min": 500, "budget_max": 100},  # min > max
        {"quantity": 0},
    ],
)
def test_invalid_camera_criteria(bad):
    with pytest.raises(ValidationError):
        CameraCriteria.model_validate(bad)


def test_spec_allows_missing_fields():
    s = CameraSpec(title="X", source_url="https://example.com")
    assert s.megapixels is None and s.price is None and s.interface == []


def test_registry():
    assert get_device("camera").key == "camera"
    with pytest.raises(UnsupportedDevice):
        get_device("plc")


def test_dropdown_lists_all_three_but_only_camera_enabled():
    devices = {d["key"]: d["enabled"] for d in list_devices()}
    assert devices == {"camera": True, "sensor": False, "plc": False}


def test_form_fields_match_criteria_model():
    fields = {f.name for f in get_device("camera").fields}
    model_fields = set(CameraCriteria.model_fields)
    assert fields <= model_fields  # every form field maps to a real criteria field
    assert {"min_megapixels", "min_fps", "shutter"} <= fields
