"""QR code scanner (handheld, presentation, fixed-mount reader or scan engine) criteria, spec and form."""
import re
from typing import Literal, get_args

from pydantic import BaseModel, PositiveFloat, PositiveInt

from .base import SHARED_FIELDS, DeviceDefinition, FieldDef, ProductBase, Req, SharedCriteria
from .compare import all_of, any_overlap, at_least, at_most, equals
from .parse import code_size_mil, ip_rating, length_mm, pick, pick_all

ScannerType = Literal["handheld", "presentation", "fixed mount", "scan engine"]
Code = Literal["QR Code", "Data Matrix", "PDF417", "Aztec", "DotCode", "MaxiCode", "1D barcodes"]
Interface = Literal[
    "USB", "RS-232", "RS-485", "TTL / UART", "Ethernet", "PROFINET", "EtherNet/IP", "Bluetooth", "Wi-Fi",
    "2.4 GHz wireless", "Wiegand",
]


class QrScannerCriteria(SharedCriteria):
    """What the buyer asks for. Every spec is optional and carries its own level."""

    scanner_type: Req[ScannerType] | None = None
    codes: Req[list[Code]] | None = None  # all of these
    reads_screens: Req[bool] | None = None  # QR codes on phone and computer screens
    interface: Req[list[Interface]] | None = None  # any of these
    max_resolution_mil: Req[PositiveFloat] | None = None  # finest code: smaller reads smaller codes
    min_reading_distance: Req[PositiveFloat] | None = None  # mm
    min_ip: Req[PositiveInt] | None = None


class QrScannerSpec(ProductBase):
    """What was extracted from a product page. Every spec is nullable: not on page -> None."""

    scanner_type: ScannerType | None = None
    codes: list[Code] = []
    reads_screens: bool | None = None
    interface: list[Interface] = []
    resolution_mil: float | None = None  # the finest code size stated
    reading_distance_mm: float | None = None  # the longest reading distance stated
    ip_rating: int | None = None
    extra_specs: dict[str, str] = {}


def _stub_spec(i: int, url: str) -> QrScannerSpec:
    """Fake product for pipeline tests (no Groq)."""
    return QrScannerSpec(
        title=f"Stub QR code scanner {i + 1}",
        supplier="stub-supplier",
        source_url=url,
        price=6500 + 9000 * i,
        currency="PKR",
        scanner_type=["handheld", "presentation", "fixed mount"][i % 3],
        codes=[["QR Code", "Data Matrix", "1D barcodes"], ["QR Code", "PDF417", "1D barcodes"],
               ["QR Code", "Data Matrix", "DotCode"]][i % 3],
        reads_screens=[True, True, False][i % 3],
        interface=[["USB"], ["USB", "RS-232"], ["Ethernet", "PROFINET"]][i % 3],
        resolution_mil=[4.0, 5.0, 3.0][i % 3],
        reading_distance_mm=[300.0, 150.0, 500.0][i % 3],
        ip_rating=[42, 52, 65][i % 3],
    )


class QrScannerExtraction(BaseModel):
    """What the LLM fills in from one page. Deliberately loose: Python normalises it."""

    is_product_page: bool
    is_listing_page: bool = False
    is_right_device_type: bool | None = None  # see QR_HINT
    title: str | None = None
    supplier: str | None = None
    part_number: str | None = None
    price: float | None = None
    currency: str | None = None
    moq: int | None = None
    scanner_type: str | None = None
    codes: list[str] | None = None  # null allowed: models write null for 'none found'
    reads_screens: bool | None = None
    interface: list[str] | None = None  # null allowed: models write null for 'none found'
    resolution: str | None = None  # as written, with its unit: "3 mil", ">=4 mil (1D)"
    reading_distance: str | None = None  # as written, with its unit: "0-30 cm", "up to 500 mm"
    ip_rating: str | None = None


QR_HINT = (
    "QR code scanner. is_right_device_type: true for scanners and readers that can read QR codes: handheld "
    "2D scanners, presentation / desktop scanners, fixed-mount and industrial code readers (e.g. Cognex DataMan, "
    "Keyence SR, SICK Lector, Datalogic Matrix), QR access-control readers and 2D scan engines / modules; makers "
    "like Zebra, Honeywell, Datalogic, Newland, Cognex, Keyence, SICK, Opticon, Code, Hikrobot, Netum, Eyoyo, "
    "Inateck, Symcode. false for 1D-only laser or CCD barcode scanners that cannot read QR codes, barcode and "
    "label printers, RFID readers, payment / POS terminals, mobile phones, QR generator apps or software, and "
    "stands, cradles, cables or batteries sold on their own. "
    "scanner_type: handheld, presentation (desktop / countertop / hands-free), fixed mount (industrial, "
    "conveyor, kiosk) or scan engine (OEM module), as written. codes: every code type it reads (e.g. QR Code, "
    "Data Matrix, PDF417, Aztec, DotCode, MaxiCode, 1D such as Code 128 / EAN / UPC). reads_screens: true if "
    "it reads codes on phone or computer screens. interface: every connection listed (e.g. USB, RS-232, TTL, "
    "Ethernet, PROFINET, Bluetooth, Wi-Fi, 2.4G wireless, Wiegand). resolution: the finest code size exactly as "
    "written, with the unit (e.g. '3 mil'). reading_distance: the reading distance or depth of field exactly "
    "as written, with the unit (e.g. '0-30 cm'). ip_rating: as written, e.g. IP54. "
    "Report the price of a single unit."
)

# --- normalisation: loose LLM text -> the exact values our criteria use ---
# order matters: a "desktop" page is presentation even if it says "hands-free scanning module"
_TYPE = [
    (("handheld", "hand-held", "hand held", "gun", "pistol"), "handheld"),
    (("presentation", "desktop", "countertop", "counter-top", "hands-free", "hands free", "platform"),
     "presentation"),
    (("fixed", "industrial reader", "inline", "in-line", "conveyor", "kiosk", "access control", "turnstile",
      "smart camera"), "fixed mount"),
    (("engine", "module", "oem", "embedded"), "scan engine"),
]
_CODES = [
    (r"\bqr\b|qr[\s-]?code|quick response", "QR Code"),
    (r"data[\s-]?matrix", "Data Matrix"),
    (r"pdf[\s-]?417", "PDF417"),
    (r"aztec", "Aztec"),
    (r"dot[\s-]?code", "DotCode"),
    (r"maxi[\s-]?code", "MaxiCode"),
    (r"\b1d\b|code[\s-]?(128|39|93)|\bean|\bupc|codabar|interleaved|\bitf\b|linear", "1D barcodes"),
]
_INTERFACE = [
    (r"\busb\b", "USB"),
    (r"rs[\s-]?232|\bserial\b|\bdb[\s-]?9\b", "RS-232"),
    (r"rs[\s-]?485", "RS-485"),
    (r"\bttl\b|\buart\b", "TTL / UART"),
    (r"profinet", "PROFINET"),
    (r"ethernet\s?/\s?ip|ethernetip", "EtherNet/IP"),
    (r"ethernet(?!\s?/\s?ip)|tcp/ip|\brj-?45\b", "Ethernet"),
    (r"bluetooth|\bbt\b|\bble\b", "Bluetooth"),
    (r"wi-?fi|\bwlan\b", "Wi-Fi"),
    (r"2\.4\s?g|2\.4\s?ghz|\brf\b|wireless (dongle|receiver)|usb receiver", "2.4 GHz wireless"),
    (r"wiegand", "Wiegand"),
]


def normalize_qr_scanner(raw: dict) -> tuple[dict, list[str]]:
    """Loose extraction -> QrScannerSpec fields, plus flags. Unknown values become None, never guessed."""
    codes = pick_all(raw.get("codes") or [], _CODES)
    if "QR Code" not in codes and re.search(r"\bqr\b|qr[\s-]?code", raw.get("title") or "", re.I):
        codes.insert(0, "QR Code")  # a "QR code scanner" reads QR codes, whatever the spec list shows
    out = {
        "scanner_type": pick(raw.get("scanner_type"), _TYPE) or pick(raw.get("title"), _TYPE),
        "codes": codes,
        "reads_screens": raw.get("reads_screens"),
        "interface": pick_all(raw.get("interface") or [], _INTERFACE),
        "resolution_mil": code_size_mil(raw.get("resolution")),
        "reading_distance_mm": length_mm(raw.get("reading_distance")),
        "ip_rating": ip_rating(raw.get("ip_rating")),
    }
    flags = []
    for name, field in [("scanner_type", "scanner_type"), ("resolution", "resolution_mil"),
                        ("reading_distance", "reading_distance_mm"), ("ip_rating", "ip_rating")]:
        if raw.get(name) not in (None, "") and out[field] is None:
            flags.append(f"{name}: unrecognised value {raw[name]!r}")
    if raw.get("interface") and not out["interface"]:
        flags.append(f"interface: unrecognised value {raw['interface']!r}")
    return out, flags


# criteria field -> (product spec field, comparison, label)
QR_CHECKS = {
    "scanner_type": ("scanner_type", equals, "Scanner type"),
    "codes": ("codes", all_of, "Codes it reads"),
    "reads_screens": ("reads_screens", equals, "Reads phone screens"),
    "interface": ("interface", any_overlap, "Interface"),
    "max_resolution_mil": ("resolution_mil", at_most, "Finest code"),
    "min_reading_distance": ("reading_distance_mm", at_least, "Reading distance"),
    "min_ip": ("ip_rating", at_least, "IP rating"),
}
QR_UNITS = {"max_resolution_mil": "mil", "min_reading_distance": "mm"}


QR_SCANNER = DeviceDefinition(
    key="qr_scanner",
    label="QR code scanner",
    criteria_model=QrScannerCriteria,
    spec_model=QrScannerSpec,
    stub_spec=_stub_spec,
    extraction_model=QrScannerExtraction,
    extraction_hint=QR_HINT,
    normalize=normalize_qr_scanner,
    checks=QR_CHECKS,
    units=QR_UNITS,
    search_term="QR code scanner",
    page_words=("qr", "barcode", "bar code", "scanner", "code reader", "2d imager", "symbolog", "data matrix",
                "pdf417"),
    search_hint=(
        "The buyer wants a scanner that reads QR codes (a 2D barcode scanner or code reader: handheld, "
        "presentation, fixed-mount or scan engine; makers such as Zebra, Honeywell, Datalogic, Newland, Cognex, "
        "Keyence). Say 'QR code scanner', '2D barcode scanner' or 'QR code reader' in the query. Never write "
        "queries that would find 1D-only laser scanners, barcode printers, RFID readers, payment terminals or "
        "QR apps."
    ),
    fields=[
        FieldDef(name="scanner_type", label="Scanner type", kind="select", options=list(get_args(ScannerType)),
                 search_word=""),
        FieldDef(name="codes", label="Codes it must read", kind="multiselect", options=list(get_args(Code)),
                 search_word="", help="All of these"),
        FieldDef(name="reads_screens", label="Reads phone screens", kind="toggle",
                 help="QR codes shown on phones or monitors, e.g. payments and tickets"),
        FieldDef(name="interface", label="Interface", kind="multiselect", options=list(get_args(Interface)),
                 search_word="", help="Any of these"),
        FieldDef(name="max_resolution_mil", label="Finest code", kind="number", unit="mil",
                 help="At most, e.g. 5. Smaller reads smaller codes"),
        FieldDef(name="min_reading_distance", label="Reading distance", kind="number", unit="mm",
                 help="At least, e.g. 300 for 30 cm"),
        FieldDef(name="min_ip", label="IP rating", kind="number", help="e.g. 54 for IP54"),
        *SHARED_FIELDS,
    ],
)
