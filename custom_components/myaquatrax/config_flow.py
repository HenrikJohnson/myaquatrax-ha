"""Config flow for MyAquaTrax integration."""
from __future__ import annotations

import logging
from typing import Any

import requests
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_ACCOUNT_NUMBER,
    CONF_METER_NUMBER,
    CONF_STREET_NUMBER,
    CONF_UTILITY_ID,
    DOMAIN,
)
from .myaquatrax_client import AquaTraxClient, AuthenticationError

_LOGGER = logging.getLogger(__name__)


async def validate_input(
    hass: HomeAssistant, data: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate the user input allows us to connect and return meters."""

    client = AquaTraxClient()
    utility_id = int(data[CONF_UTILITY_ID])
    email = data[CONF_EMAIL]

    try:
        if CONF_ACCOUNT_NUMBER in data and CONF_STREET_NUMBER in data:
            await hass.async_add_executor_job(
                client.login_with_sso,
                utility_id,
                data[CONF_ACCOUNT_NUMBER],
                email,
                data[CONF_STREET_NUMBER],
            )
        else:
            await hass.async_add_executor_job(
                client.login, utility_id, email, data[CONF_PASSWORD]
            )

        accounts = await hass.async_add_executor_job(client.get_accounts)
        if not accounts:
            raise InvalidAuth("No accounts found for this login")

        # Discover usage meters for each account
        all_meters = []
        for account in accounts:
            meters = await hass.async_add_executor_job(
                client.get_usage_meters, utility_id, account.account_number
            )
            for m in meters:
                all_meters.append(
                    {
                        "account_number": account.account_number,
                        "meter_number": m.meter_number,
                        "label": f"{account.account_number} - {m.meter_number}",
                    }
                )

        if not all_meters:
            raise InvalidAuth("No meters found for this account")

    except AuthenticationError as exc:
        raise InvalidAuth from exc
    except requests.RequestException as exc:
        raise CannotConnect from exc

    return (
        {
            "title": f"MyAquaTrax {accounts[0].account_number}",
            CONF_UTILITY_ID: utility_id,
            CONF_ACCOUNT_NUMBER: accounts[0].account_number,
            CONF_EMAIL: email,
        },
        all_meters,
    )


class AquaTraxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MyAquaTrax."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._utilities: dict[str, tuple[int, bool, str]] = {}
        self._selected_utility_id: int | None = None
        self._selected_sso: bool = False
        self._validated_input: dict[str, Any] = {}
        self._meters: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: select utility."""
        errors: dict[str, str] = {}

        if user_input is None:
            client = AquaTraxClient()
            try:
                utilities = await self.hass.async_add_executor_job(client.get_utilities)
            except requests.RequestException:
                return self.async_abort(reason="cannot_connect")

            self._utilities = {
                f"{u.utility_id} - {u.name}": (u.utility_id, u.sso_enabled, u.name)
                for u in utilities
            }

            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("utility_choice"): vol.In(
                            list(self._utilities.keys())
                        ),
                    }
                ),
                errors=errors,
            )

        choice = user_input["utility_choice"]
        utility_id, sso_enabled, utility_name = self._utilities[choice]
        self._selected_utility_id = utility_id
        self._selected_sso = sso_enabled

        return await self.async_step_credentials()

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the credentials step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_UTILITY_ID] = self._selected_utility_id
            try:
                info, meters = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                self._validated_input = {**user_input, **info}
                self._meters = meters

                if len(self._meters) == 1:
                    return self._create_entry(self._meters[0])

                return await self.async_step_meter()

        if self._selected_sso:
            schema = vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT_NUMBER): str,
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_STREET_NUMBER): str,
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            )

        return self.async_show_form(
            step_id="credentials", data_schema=schema, errors=errors
        )

    async def async_step_meter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the meter selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected = user_input["meter_choice"]
            meter = next((m for m in self._meters if m["label"] == selected), None)
            if meter:
                return self._create_entry(meter)

        meter_choices = {m["label"]: m["label"] for m in self._meters}

        return self.async_show_form(
            step_id="meter",
            data_schema=vol.Schema(
                {vol.Required("meter_choice"): vol.In(list(meter_choices.keys()))}
            ),
            errors=errors,
        )

    def _create_entry(self, meter: dict[str, Any]) -> ConfigFlowResult:
        """Build the final config entry."""
        entry_data = {
            **self._validated_input,
            CONF_ACCOUNT_NUMBER: meter["account_number"],
            CONF_METER_NUMBER: meter["meter_number"],
        }
        return self.async_create_entry(
            title=f"MyAquaTrax {meter['account_number']}", data=entry_data
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
