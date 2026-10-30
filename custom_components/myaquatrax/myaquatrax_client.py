"""Standalone Python client for myaquatrax.com water usage portal."""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import requests

_LOGGER = logging.getLogger("myaquatrax")

BASE_URL = "https://myaquatrax.com"


@dataclass
class Utility:
    """Represents a water district/agency."""

    utility_id: int
    name: str
    sso_enabled: bool
    invoice_cloud_status: int
    is_registration: bool
    payment_location: str | None = None
    logo: str | None = None


@dataclass
class Account:
    """Represents a customer account."""

    account_number: str
    is_primary: bool = False
    invoice_cloud_guid: str | None = None


@dataclass
class Meter:
    """Represents a water meter."""

    meter_number: str
    account_number: str
    meter_type: str | None = None
    is_ami: bool = False
    is_default: bool = False
    color: str | None = None


@dataclass
class UsageReading:
    """Represents a water usage reading."""

    usage_date: str
    hourly: str | None
    total_value: float | None
    average: float | None
    highest: float | None
    lowest: float | None
    current_usage: float | None


def to_float(value: Any) -> float | None:
    """Convert an API value to float, returning None for null/blank/invalid values."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = str(value).strip().replace(",", "").replace("$", "")
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


class AquaTraxClient:
    """Client for the MyAquaTrax water portal."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            }
        )
        self._utility_id: int | None = None
        self._is_authenticated = False

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_utilities(self) -> list[Utility]:
        """Fetch the list of available water utilities (no auth required)."""
        url = f"{BASE_URL}/common/GetMasterUtilityList"
        resp = self._session.post(url, data={}, timeout=30)
        resp.raise_for_status()
        # Response is sometimes a JSON string wrapping another JSON object
        text = resp.text.strip()
        if text.startswith('"') and text.endswith('"'):
            text = json.loads(text)
        payload = json.loads(text)
        table = payload.get("Results", {}).get("Table", [])
        utilities: list[Utility] = []
        for row in table:
            utilities.append(
                Utility(
                    utility_id=row["UtilityId"],
                    name=row["Name"],
                    sso_enabled=str(row.get("ssoenable", "0")) == "1",
                    invoice_cloud_status=row.get("InvoiceCoudstatus", 0),
                    is_registration=row.get("IsRegistration", False) is True,
                    payment_location=row.get("Paymentlocation") or None,
                    logo=row.get("UtilityLogo") or None,
                )
            )
        return utilities

    def login(self, utility_id: int, username: str, password: str) -> bool:
        """Authenticate with the portal using email/password.

        Returns True on success, raises on failure.
        """
        token = self._fetch_login_token()

        form_data = {
            "__RequestVerificationToken": token,
            "Mfe": "False",
            "utilityId": str(utility_id),
            "InvoiceCoudstatus": "",
            "IsRegistration": "False",
            "IsSSOEnabled": "0",
            "UserName": username,
            "Password": password,
            "RememberMe": "true",
        }

        post_resp = self._do_login_post(f"{BASE_URL}/Account/Login", form_data)
        self._utility_id = utility_id
        self._is_authenticated = True
        _LOGGER.info("Standard login successful for utility %s", utility_id)
        return True

    def login_with_sso(
        self,
        utility_id: int,
        account_number: str,
        email: str,
        street_number: str,
    ) -> bool:
        """Authenticate with the portal using SSO (Account + Email + Street).

        Some utilities (e.g. Newport Beach) do not use passwords.
        Returns True on success, raises on failure.
        """
        token = self._fetch_login_token()

        form_data = {
            "__RequestVerificationToken": token,
            "Mfe": "False",
            "ssoutilityId": str(utility_id),
            "ssoutilityname": "",
            "InvoiceCoudstatus": "",
            "AccountNumber": account_number,
            "UserName": email,
            "Address": street_number,
            "RememberMe": "true",
        }

        post_resp = self._do_login_post(f"{BASE_URL}/Account/LoginWithSso", form_data)
        self._utility_id = utility_id
        self._is_authenticated = True
        _LOGGER.info("SSO login successful for utility %s", utility_id)
        return True

    def get_accounts(self) -> list[Account]:
        """Fetch the list of accounts linked to the logged-in user."""
        self._require_auth()
        url = f"{BASE_URL}/MVPDashboard/GetAccountList"
        resp = self._session.get(url, timeout=30)
        resp.raise_for_status()

        text = resp.text.strip()
        # Response is sometimes a JSON string inside a JSON string
        if text.startswith('"') and text.endswith('"'):
            text = json.loads(text)
        try:
            payload = json.loads(text)
        except ValueError:
            payload = {}

        table = payload.get("Table", [])
        accounts: list[Account] = []
        for row in table:
            accounts.append(
                Account(
                    account_number=row.get("AccountNumber", ""),
                    is_primary=bool(row.get("IsPrimary", 0)),
                    invoice_cloud_guid=row.get("InvoiceCloudGUID") or None,
                )
            )
        return accounts

    def get_meter_details(
        self, utility_id: int, account_number: str, mode: str = ""
    ) -> list[Meter]:
        """Fetch meter details for a given account.

        The GetMeterDetails endpoint returns different data depending on mode:
        - mode="" (empty): returns raw AMI meter serials
        - mode="H"/"D"/"M"/"B": returns the utility meter number used by GetWaterUsage
        """
        self._require_auth()
        params: dict[str, str] = {
            "utilityId": str(utility_id),
            "utilityAccountNumber": account_number,
        }
        if mode:
            params["mode"] = mode

        url = f"{BASE_URL}/MVPUsage/GetMeterDetails"
        resp = self._session.get(url, params=params, timeout=15)
        resp.raise_for_status()

        text = resp.text.strip()
        if text.startswith('"') and text.endswith('"'):
            text = json.loads(text)
        data = json.loads(text)

        return self._parse_meters(data, account_number)

    def get_usage_meters(self, utility_id: int, account_number: str) -> list[Meter]:
        """Fetch the utility meter numbers used by GetWaterUsage."""
        return self.get_meter_details(utility_id, account_number, mode="H")

    def get_raw_meters(self, utility_id: int, account_number: str) -> list[Meter]:
        """Fetch raw AMI meter serial numbers."""
        return self.get_meter_details(utility_id, account_number, mode="")

    def get_water_usage(
        self,
        water_account_number: str,
        meter_number: str,
        mode: str = "H",
        usage_type: str = "G",
        from_date: str | None = None,
        to_date: str | None = None,
        year: int | None = None,
    ) -> dict[str, Any]:
        """Fetch water usage data.

        Parameters:
            water_account_number: e.g. "2450280-657401"
            meter_number: e.g. "2450280-10450-1"
            mode: "H"=Hourly, "D"=Daily, "M"=Monthly, "B"=Bi-monthly
            usage_type: "G"=Gallon, "W"=HCF/CCF, "D"=$, "C"=CF
            from_date: MM/DD/YYYY (ignored for mode "M" / "B")
            to_date: MM/DD/YYYY (ignored for mode "M" / "B")
            year: used for Monthly/Bi-monthly mode instead of date range
        """
        self._require_auth()
        request_payload = {
            "WaterAccountNumber": water_account_number,
            "Mode": mode,
            "Type": usage_type,
            "Year": year,
            "FromDate": from_date,
            "ToDate": to_date,
            "MeterNumber": meter_number,
            "UtilityName": None,
        }
        request_json = json.dumps(request_payload, separators=(",", ":"))

        # Build URL manually to avoid double-encoding by requests
        query = urllib.parse.urlencode({"request": request_json})
        url = f"{BASE_URL}/MVPUsage/GetWaterUsage?{query}"
        resp = self._session.get(url, timeout=30)
        resp.raise_for_status()

        # The response is sometimes a JSON string inside a JSON string
        text = resp.text.strip()
        if text.startswith('"') and text.endswith('"'):
            text = json.loads(text)
        data = json.loads(text)
        return data

    def get_daily_usage(
        self,
        water_account_number: str,
        meter_number: str,
        days: int = 7,
        usage_type: str = "G",
    ) -> list[UsageReading]:
        """Convenience wrapper to get daily usage for the last N days."""
        end = datetime.now()
        start = end - timedelta(days=days)
        data = self.get_water_usage(
            water_account_number=water_account_number,
            meter_number=meter_number,
            mode="D",
            usage_type=usage_type,
            from_date=start.strftime("%m/%d/%Y"),
            to_date=end.strftime("%m/%d/%Y"),
        )
        return self._parse_usage_table(data)

    def get_hourly_usage(
        self,
        water_account_number: str,
        meter_number: str,
        days: int = 1,
        usage_type: str = "G",
    ) -> list[UsageReading]:
        """Convenience wrapper to get hourly usage for the last N days."""
        end = datetime.now()
        start = end - timedelta(days=days)
        data = self.get_water_usage(
            water_account_number=water_account_number,
            meter_number=meter_number,
            mode="H",
            usage_type=usage_type,
            from_date=start.strftime("%m/%d/%Y"),
            to_date=end.strftime("%m/%d/%Y"),
        )
        return self._parse_usage_table(data)

    def get_monthly_usage(
        self,
        water_account_number: str,
        meter_number: str,
        year: int | None = None,
        usage_type: str = "G",
    ) -> list[UsageReading]:
        """Convenience wrapper to get monthly usage for a year."""
        if year is None:
            year = datetime.now().year
        data = self.get_water_usage(
            water_account_number=water_account_number,
            meter_number=meter_number,
            mode="M",
            usage_type=usage_type,
            year=year,
        )
        return self._parse_usage_table(data)

    def get_unit_types(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Return available unit types from a usage response."""
        return data.get("Results", {}).get("Table1", [])

    def get_compare_data(self, usage_type: str = "G") -> dict[str, Any]:
        """Fetch water usage comparison data.

        Returns comparison against previous year, utility average, and zip average.
        The meterNumber parameter must be empty — the server uses the session's
        selected meter.
        """
        self._require_auth()
        url = f"{BASE_URL}/MVPCompare/GetWaterCompareSpending?type={usage_type}&meterNumber="
        resp = self._session.get(url, timeout=30)
        resp.raise_for_status()

        text = resp.text.strip()
        if text.startswith('"') and text.endswith('"'):
            text = json.loads(text)
        data = json.loads(text)
        return data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_login_token(self) -> str:
        """GET login page and extract the anti-forgery token."""
        login_url = f"{BASE_URL}/Account/login"
        get_resp = self._session.get(login_url, timeout=30)
        get_resp.raise_for_status()
        token = self._extract_request_verification_token(get_resp.text)
        if not token:
            raise ValueError("Could not extract __RequestVerificationToken from login page")
        return token

    def _do_login_post(self, url: str, form_data: dict[str, str]) -> requests.Response:
        """POST login form and verify success."""
        post_resp = self._session.post(
            url,
            data=form_data,
            timeout=30,
            allow_redirects=True,
        )
        post_resp.raise_for_status()

        if "/Account/Login" in post_resp.url or "Invalid" in post_resp.text:
            # Look for explicit error messages
            error_match = re.search(
                r'showError\([\'"](.+?)[\'"]\)', post_resp.text
            )
            msg = error_match.group(1) if error_match else "invalid credentials"
            raise AuthenticationError(f"Login failed – {msg}")

        return post_resp

    def _extract_request_verification_token(self, html: str) -> str | None:
        """Parse the ASP.NET anti-forgery token from the login form."""
        match = re.search(
            r'<input[^>]+name="__RequestVerificationToken"[^>]+value="([^"]+)"',
            html,
            re.IGNORECASE,
        )
        if match:
            return match.group(1)
        match = re.search(
            r'<input[^>]+value="([^"]+)"[^>]+name="__RequestVerificationToken"',
            html,
            re.IGNORECASE,
        )
        return match.group(1) if match else None

    def _require_auth(self) -> None:
        if not self._is_authenticated:
            raise AuthenticationError("Not authenticated. Call login() first.")

    @staticmethod
    def _parse_meters(data: Any, account_number: str) -> list[Meter]:
        """Parse meter list from GetMeterDetails response."""
        meters: list[Meter] = []
        table = data.get("Results", {}).get("Table", []) if isinstance(data, dict) else []
        if not isinstance(table, list):
            return meters
        for row in table:
            # GetMeterDetails uses different keys depending on mode
            m = (
                row.get("MeterNumber")
                or row.get("meterNumber")
                or row.get("meternumber")
            )
            if not m:
                continue
            meters.append(
                Meter(
                    meter_number=str(m),
                    account_number=account_number,
                    meter_type=row.get("MeterType") or None,
                    is_ami=bool(row.get("IsAMI", row.get("Isami", False))),
                    is_default=bool(row.get("Default_Meter", row.get("Default_Meter", False))),
                    color=row.get("Color") or row.get("Color") or None,
                )
            )
        return meters

    @staticmethod
    def _parse_usage_table(data: dict[str, Any]) -> list[UsageReading]:
        """Parse the usage Table from a GetWaterUsage response."""
        readings: list[UsageReading] = []
        results = data.get("Results") if isinstance(data, dict) else None
        table = results.get("Table") if isinstance(results, dict) else None
        if not isinstance(table, list):
            return readings
        for row in table:
            if not isinstance(row, dict):
                continue
            readings.append(
                UsageReading(
                    usage_date=row.get("UsageDate", ""),
                    hourly=row.get("Hourly"),
                    total_value=to_float(row.get("TotalValue")),
                    average=to_float(row.get("AVERAGE")),
                    highest=to_float(row.get("HIGHEST")),
                    lowest=to_float(row.get("LOWEST")),
                    current_usage=to_float(row.get("CurrentUsage")),
                )
            )
        return readings


class AuthenticationError(Exception):
    """Raised when login fails."""


class AquaTraxError(Exception):
    """Generic client error."""


# ------------------------------------------------------------------
# CLI for quick testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")

    client = AquaTraxClient()

    if len(sys.argv) > 1 and sys.argv[1] == "list-utilities":
        utilities = client.get_utilities()
        for u in utilities:
            print(f"{u.utility_id}: {u.name} (SSO={u.sso_enabled})")
        sys.exit(0)

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python myaquatrax_client.py list-utilities")
        print("  python myaquatrax_client.py <utility_id> <email> <password>")
        print("  python myaquatrax_client.py sso <utility_id> <account> <email> <street>")
        sys.exit(1)

    if sys.argv[1] == "sso":
        if len(sys.argv) < 6:
            print("Usage: python myaquatrax_client.py sso <utility_id> <account> <email> <street>")
            sys.exit(1)
        utility_id = int(sys.argv[2])
        account = sys.argv[3]
        email = sys.argv[4]
        street = sys.argv[5]
        client.login_with_sso(utility_id, account, email, street)
    else:
        if len(sys.argv) < 4:
            print("Usage: python myaquatrax_client.py <utility_id> <email> <password>")
            sys.exit(1)
        utility_id = int(sys.argv[1])
        email = sys.argv[2]
        password = sys.argv[3]
        client.login(utility_id, email, password)

    accounts = client.get_accounts()
    print("Accounts:", [a.account_number for a in accounts])

    for acct in accounts:
        raw_meters = client.get_raw_meters(utility_id, acct.account_number)
        usage_meters = client.get_usage_meters(utility_id, acct.account_number)
        print(f"  Raw meters for {acct.account_number}:", [m.meter_number for m in raw_meters])
        print(f"  Usage meters for {acct.account_number}:", [m.meter_number for m in usage_meters])
