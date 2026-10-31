"""Sensor platform for MyAquaTrax integration."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    USAGE_TYPE_CCF,
    USAGE_TYPE_DOLLARS,
    USAGE_TYPE_GALLONS,
)
from .coordinator import AquaTraxCoordinator
from .myaquatrax_client import to_float


type AquaTraxConfigEntry = ConfigEntry[AquaTraxCoordinator]


# Water sensors per unit type (Gallons, CCF)
WATER_KEYS = [
    ("billing_period_total", "Billing Period Total", SensorStateClass.TOTAL_INCREASING),
    ("daily_usage", "Daily Usage", SensorStateClass.TOTAL_INCREASING),
    ("average", "Average", None),
    ("highest", "Highest", None),
    ("lowest", "Lowest", None),
]

# Cost sensors (Dollars)
COST_KEYS = [
    ("billing_period_cost", "Billing Period Cost", SensorStateClass.TOTAL),
    ("daily_cost", "Daily Cost", SensorStateClass.TOTAL),
]

# Comparison sensors (Gallons)
COMPARE_KEYS = [
    ("compare_current", "Comparison Current Month", None),
    ("compare_previous", "Comparison Previous Year", None),
    ("compare_utility", "Comparison Utility Average", None),
    ("compare_zip", "Comparison Zip Average", None),
]

# Flow rate sensors (per-hour usage, interpreting hourly TotalValue as flow)
FLOW_KEYS = [
    ("current_hour_flow", "Current Hour Flow"),
    ("peak_flow_today", "Peak Flow Today"),
]


def _build_descriptions() -> tuple[SensorEntityDescription, ...]:
    """Build all sensor descriptions."""
    descriptions: list[SensorEntityDescription] = []

    # Gallons
    for key, name, state_class in WATER_KEYS:
        descriptions.append(
            SensorEntityDescription(
                key=f"{USAGE_TYPE_GALLONS}_{key}",
                name=f"{name} (Gallons)",
                state_class=state_class,
                device_class=SensorDeviceClass.WATER,
            )
        )

    # CCF/HCF
    for key, name, state_class in WATER_KEYS:
        descriptions.append(
            SensorEntityDescription(
                key=f"{USAGE_TYPE_CCF}_{key}",
                name=f"{name} (CCF)",
                state_class=state_class,
                device_class=SensorDeviceClass.WATER,
            )
        )

    # Dollars
    for key, name, state_class in COST_KEYS:
        descriptions.append(
            SensorEntityDescription(
                key=f"{USAGE_TYPE_DOLLARS}_{key}",
                name=name,
                state_class=state_class,
                device_class=SensorDeviceClass.MONETARY,
            )
        )

    # Comparison (Gallons)
    for key, name, state_class in COMPARE_KEYS:
        descriptions.append(
            SensorEntityDescription(
                key=f"compare_{key}",
                name=name,
                state_class=state_class,
                device_class=SensorDeviceClass.WATER,
            )
        )

    # Flow rate sensors (per-hour readings converted to per-minute rate)
    # Only Gallons—the CCF hourly data is in CCF units (not ft³/h) so it
    # doesn't translate cleanly to flow rate. Gal/min is the only unit that
    # makes sense for the API data shape.
    for key, name in FLOW_KEYS:
        descriptions.append(
            SensorEntityDescription(
                key=f"{USAGE_TYPE_GALLONS}_flow_{key}",
                name=f"{name} (gal/min)",
                state_class=SensorStateClass.MEASUREMENT,
                device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
            )
        )

    return tuple(descriptions)


SENSOR_DESCRIPTIONS = _build_descriptions()


def _get_unit(key: str) -> str:
    if "flow_" in key:
        return "gal/min"
    if key.startswith(USAGE_TYPE_GALLONS) or key.startswith("compare_"):
        return UnitOfVolume.GALLONS
    if key.startswith(USAGE_TYPE_CCF):
        return "hcf"
    if key.startswith(USAGE_TYPE_DOLLARS):
        return "USD"
    return UnitOfVolume.GALLONS


def _data_key(key: str) -> str:
    if "flow_" in key:
        return "hourly_gallons"
    if key.startswith(USAGE_TYPE_GALLONS):
        return "gallons"
    if key.startswith(USAGE_TYPE_CCF):
        return "ccf"
    if key.startswith(USAGE_TYPE_DOLLARS):
        return "cost"
    if key.startswith("compare_"):
        return "compare"
    return "gallons"


def _reading_key(key: str) -> str:
    # Strip the longest prefix first so that e.g. "G_flow_current_hour_flow"
    # becomes "current_hour_flow", not "flow_current_hour_flow"
    for prefix in (
        f"{USAGE_TYPE_GALLONS}_flow_",
        f"{USAGE_TYPE_GALLONS}_",
        f"{USAGE_TYPE_CCF}_",
        f"{USAGE_TYPE_DOLLARS}_",
    ):
        if key.startswith(prefix):
            return key[len(prefix):]
    if key.startswith("compare_"):
        return key[len("compare_"):]
    return key


def _get_current_month_compare(compare_data: dict[str, Any], table_key: str) -> dict[str, Any] | None:
    """Extract the current month's row from a comparison table."""
    current_month = datetime.now().month
    current_year = datetime.now().year
    table = compare_data.get("Results", {}).get(table_key, [])
    for row in table:
        if row.get("MOD") == current_month and row.get("YOD") == current_year:
            return row
    # Fallback: just return the last row
    return table[-1] if table else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AquaTraxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MyAquaTrax sensor entities."""
    coordinator = entry.runtime_data

    entities: list[SensorEntity] = []
    for description in SENSOR_DESCRIPTIONS:
        entities.append(
            AquaTraxSensorEntity(coordinator, description, _get_unit(description.key))
        )

    async_add_entities(entities)


class AquaTraxSensorEntity(CoordinatorEntity[AquaTraxCoordinator], SensorEntity):
    """Representation of a MyAquaTrax sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AquaTraxCoordinator,
        description: SensorEntityDescription,
        unit: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_native_unit_of_measurement = unit
        self._attr_unique_id = (
            f"{coordinator._account_number}_{coordinator._meter_number}_{description.key}"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator._account_number)},
            "name": f"MyAquaTrax {coordinator._account_number}",
            "manufacturer": "AquaTrax",
        }

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        key = self.entity_description.key
        data_key = _data_key(key)
        rkey = _reading_key(key)

        # Comparison sensors
        if data_key == "compare":
            compare_data = self.coordinator.data.get("compare")
            if not compare_data:
                return None
            table_map = {
                "current": "Table",
                "previous": "Table1",
                "utility": "Table2",
                "zip": "Table3",
            }
            table_name = table_map.get(rkey)
            if not table_name:
                return None
            row = _get_current_month_compare(compare_data, table_name)
            if not row:
                return None
            return to_float(row.get("Consumed"))

        # Standard usage sensors
        readings = self.coordinator.data.get(data_key, [])
        if not readings:
            return None

        # Flow rate sensors: hourly reading (gallons per hour) → per-minute rate
        if rkey == "current_hour_flow":
            for reading in reversed(readings):
                if reading.total_value is not None:
                    return reading.total_value / 60
            return None
        if rkey == "peak_flow_today":
            try:
                peak = max(r.total_value for r in readings if r.total_value is not None)
                return peak / 60
            except ValueError:
                return None

        field = {
            "billing_period_total": "current_usage",
            "billing_period_cost": "current_usage",
            "daily_usage": "total_value",
            "daily_cost": "total_value",
            "average": "average",
            "highest": "highest",
            "lowest": "lowest",
        }.get(rkey)
        if field is None:
            return None

        # The most recent day is often not yet reported (null), so use the
        # latest reading that actually has a value.
        for reading in reversed(readings):
            value = getattr(reading, field)
            if value is not None:
                return value

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        key = self.entity_description.key
        data_key = _data_key(key)

        if data_key == "compare":
            compare_data = self.coordinator.data.get("compare")
            if not compare_data:
                return {}
            rkey = _reading_key(key)
            table_map = {
                "current": "Table",
                "previous": "Table1",
                "utility": "Table2",
                "zip": "Table3",
            }
            row = _get_current_month_compare(compare_data, table_map.get(rkey, "Table"))
            if not row:
                return {}
            return {
                "month": row.get("MOD"),
                "year": row.get("YOD"),
                "allocation": row.get("AllocationValue"),
                "last_update": self.coordinator.data.get("last_update"),
            }

        readings = self.coordinator.data.get(data_key, [])
        if not readings:
            return {}

        latest = readings[-1]
        attrs = {
            "usage_date": latest.usage_date,
            "last_update": self.coordinator.data.get("last_update"),
        }
        rkey = _reading_key(key)
        if rkey in ("current_hour_flow", "peak_flow_today"):
            attrs["hour"] = latest.hourly
            if rkey == "peak_flow_today":
                peak_reading = max(readings, key=lambda r: r.total_value)
                attrs["peak_hour"] = f"{peak_reading.usage_date} {peak_reading.hourly}"
                attrs["peak_value"] = peak_reading.total_value
        return attrs
