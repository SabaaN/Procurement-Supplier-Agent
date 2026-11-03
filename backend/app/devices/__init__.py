"""Device registry: the single place that lists which device types exist."""
from .base import DeviceDefinition
from .camera import CAMERA

DEVICES: dict[str, DeviceDefinition] = {CAMERA.key: CAMERA}

# Shown in the dropdown but not selectable yet.
COMING_SOON = {"sensor": "Sensor", "plc": "PLC"}


class UnsupportedDevice(ValueError):
    pass


def get_device(key: str) -> DeviceDefinition:
    try:
        return DEVICES[key]
    except KeyError:
        raise UnsupportedDevice(f"Device type '{key}' is not supported yet") from None


def list_devices() -> list[dict]:
    """What the frontend dropdown needs."""
    live = [{"key": d.key, "label": d.label, "enabled": True} for d in DEVICES.values()]
    soon = [{"key": k, "label": v, "enabled": False} for k, v in COMING_SOON.items()]
    return live + soon
