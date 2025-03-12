"""Constants for the RAD Hoeksche Waard Afval integration."""
from datetime import timedelta

DOMAIN = "rad_hw_afval"
SCAN_INTERVAL = timedelta(hours=12)
CONF_POSTAL_CODE = "postal_code"
CONF_STREET_NUMBER = "street_number"
CONF_RESOURCES = "resources"
CONF_DATE_FORMAT = "date_format"

# Default values
DEFAULT_DATE_FORMAT = "%d-%m-%Y"

# API URL for RAD Hoeksche Waard Afval
API_URL = "https://wasteapi2.ximmio.com/api/"

# Company code for RAD Hoeksche Waard
COMPANY_CODE = "13a2cad9-36d0-4b01-b877-efcb421a864d"

# Waste types
WASTE_TYPE_REST = "rest"
WASTE_TYPE_GFT = "gft"
WASTE_TYPE_PAPIER = "papier"
WASTE_TYPE_PMD = "pmd"

# Sensor attributes
ATTR_NEXT_DATE = "next_date"
ATTR_DAYS_UNTIL = "days_until"

# Sensor names
SENSOR_TYPES = {
    WASTE_TYPE_REST: "Restafval",
    WASTE_TYPE_GFT: "GFT",
    WASTE_TYPE_PAPIER: "Oud Papier",
    WASTE_TYPE_PMD: "PMD",
}
