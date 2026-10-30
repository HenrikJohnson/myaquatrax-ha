"""Constants for the MyAquaTrax integration."""

DOMAIN = "myaquatrax"

CONF_UTILITY_ID = "utility_id"
CONF_ACCOUNT_NUMBER = "account_number"
CONF_METER_NUMBER = "meter_number"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_STREET_NUMBER = "street_number"

DEFAULT_SCAN_INTERVAL = 3600  # seconds

# MyAquaTrax API usage types — we auto-create sensors for all of them
USAGE_TYPE_GALLONS = "G"
USAGE_TYPE_CCF = "W"  # Also called HCF
USAGE_TYPE_CF = "C"
USAGE_TYPE_DOLLARS = "D"

UNIT_LABELS = {
    USAGE_TYPE_GALLONS: "Gallons",
    USAGE_TYPE_CCF: "CCF/HCF",
    USAGE_TYPE_CF: "Cubic Feet",
    USAGE_TYPE_DOLLARS: "Dollars",
}
