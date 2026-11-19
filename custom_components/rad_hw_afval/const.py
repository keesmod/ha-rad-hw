"""Constants for the RAD Hoeksche Waard Afval integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "rad_hw_afval"

# The calendar changes rarely: poll twice a day, but retry sooner after a failure.
SCAN_INTERVAL: Final = timedelta(hours=12)
RETRY_INTERVAL: Final = timedelta(minutes=30)
REQUEST_TIMEOUT: Final = 30  # seconds per API request

CONF_POSTAL_CODE: Final = "postal_code"
CONF_STREET_NUMBER: Final = "street_number"
CONF_HOUSE_LETTER: Final = "house_letter"
# Integration 1.2.x stored the selected waste types in the options. Every waste
# type now has a sensor; the migration in __init__.py disables deselected ones.
CONF_RESOURCES: Final = "resources"
CONF_DATE_FORMAT: Final = "date_format"

DEFAULT_DATE_FORMAT: Final = "%d-%m-%Y"

# Ximmio API, as used by RAD's own online waste calendar.
API_URL: Final = "https://wasteapi2.ximmio.com/api/"
COMPANY_CODE: Final = "13a2cad9-36d0-4b01-b877-efcb421a864d"
COMMUNITY: Final = "Hoeksche Waard"

WASTE_TYPE_REST: Final = "rest"
WASTE_TYPE_GFT: Final = "gft"
WASTE_TYPE_PAPIER: Final = "papier"
WASTE_TYPE_PMD: Final = "pmd"

# Sensor key -> entity name.
SENSOR_TYPES: Final = {
    WASTE_TYPE_REST: "Restafval",
    WASTE_TYPE_GFT: "GFT",
    WASTE_TYPE_PAPIER: "Oud Papier",
    WASTE_TYPE_PMD: "PMD",
}

# Ximmio pickup type code (field "_pickupTypeText") -> sensor key.
PICKUP_TYPES: Final = {
    "GREY": WASTE_TYPE_REST,
    "GREEN": WASTE_TYPE_GFT,
    "PAPER": WASTE_TYPE_PAPIER,
    "PACKAGES": WASTE_TYPE_PMD,
}
