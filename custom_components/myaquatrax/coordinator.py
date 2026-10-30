"""DataUpdateCoordinator for MyAquaTrax."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ACCOUNT_NUMBER,
    CONF_EMAIL,
    CONF_METER_NUMBER,
    CONF_PASSWORD,
    CONF_STREET_NUMBER,
    CONF_UTILITY_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    USAGE_TYPE_CCF,
    USAGE_TYPE_DOLLARS,
    USAGE_TYPE_GALLONS,
)
from .myaquatrax_client import AquaTraxClient, AuthenticationError

_LOGGER = logging.getLogger(__name__)


type AquaTraxData = dict[str, Any]


class AquaTraxCoordinator(DataUpdateCoordinator[AquaTraxData]):
    """MyAquaTrax data update coordinator."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the coordinator."""
        self._config = config
        self._client = AquaTraxClient()
        self._utility_id = int(config[CONF_UTILITY_ID])
        self._account_number = config[CONF_ACCOUNT_NUMBER]
        self._meter_number = config[CONF_METER_NUMBER]
        self._email = config[CONF_EMAIL]

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> AquaTraxData:
        """Fetch data from MyAquaTrax for all units (Gallons, CCF, Dollars)."""
        try:
            # Re-authenticate
            if CONF_STREET_NUMBER in self._config:
                await self.hass.async_add_executor_job(
                    self._client.login_with_sso,
                    self._utility_id,
                    self._account_number,
                    self._email,
                    self._config[CONF_STREET_NUMBER],
                )
            else:
                await self.hass.async_add_executor_job(
                    self._client.login,
                    self._utility_id,
                    self._email,
                    self._config[CONF_PASSWORD],
                )

            end = datetime.now()
            start = end - timedelta(days=7)
            from_date = start.strftime("%m/%d/%Y")
            to_date = end.strftime("%m/%d/%Y")

            # Fetch usage in Gallons
            raw_gallons = await self.hass.async_add_executor_job(
                self._client.get_water_usage,
                self._account_number,
                self._meter_number,
                "D",
                USAGE_TYPE_GALLONS,
                from_date,
                to_date,
            )

            # Fetch usage in CCF/HCF
            raw_ccf = await self.hass.async_add_executor_job(
                self._client.get_water_usage,
                self._account_number,
                self._meter_number,
                "D",
                USAGE_TYPE_CCF,
                from_date,
                to_date,
            )

            # Fetch cost in Dollars
            raw_cost = await self.hass.async_add_executor_job(
                self._client.get_water_usage,
                self._account_number,
                self._meter_number,
                "D",
                USAGE_TYPE_DOLLARS,
                from_date,
                to_date,
            )

            # Fetch comparison data (Gallons)
            raw_compare = await self.hass.async_add_executor_job(
                self._client.get_compare_data, USAGE_TYPE_GALLONS
            )

            return {
                "gallons": self._client._parse_usage_table(raw_gallons),
                "ccf": self._client._parse_usage_table(raw_ccf),
                "cost": self._client._parse_usage_table(raw_cost),
                "compare": raw_compare,
                "unit_types": self._client.get_unit_types(raw_gallons),
                "last_update": datetime.now().isoformat(),
            }

        except AuthenticationError as exc:
            raise UpdateFailed(f"Authentication failed: {exc}") from exc
        except Exception as exc:
            _LOGGER.exception("Unexpected error fetching MyAquaTrax data")
            raise UpdateFailed(f"Error fetching data: {exc}") from exc
