# MyAquaTrax — Home Assistant Integration

Pull water usage, cost, and comparison data from [myaquatrax.com](https://myaquatrax.com) into Home Assistant.

## Features

- **Gallons** and **CCF/HCF** usage sensors (billing period total, daily, average, highest, lowest)
- **Dollar** cost sensors (billing period total, daily)
- **Comparison sensors** vs. previous year, utility average, and zip code average
- Energy Dashboard compatible (`device_class=WATER` + `TOTAL_INCREASING`)
- Billing Dashboard compatible (`device_class=MONETARY`)
- Supports both **email/password** and **SSO** (Account + Email + Street) logins
- Auto-discovers water meters after login

## Supported Water Utilities

Any water district that uses the MyAquaTrax portal:

> **Note:** While no providers currently enforce MFA, this integration does not support it. If your provider enables MFA in the future, login will fail.

- City of Newport Beach
- City of American Canyon
- City of Morgan Hill
- City of Gilroy
- City of Goodyear
- City of La Marque
- City of White Plains
- City of San Jose
- Rowland Water District
- Fairview City
- Marshall & Polk Rural Water System
- Myoma Dunes Water Company
- City of Cedar Hills
- Crestline Village Water District
- Laguna Beach County Water District
- City of Lindon
- City of Buena Park
- City of Fountain Valley
- East Orange County Water District

## Installation

### HACS (Recommended)

1. In HACS, click **⋮ → Custom repositories**
2. Add `https://github.com/HenrikJohnson/myaquatrax-ha` as an **Integration** type repository
3. Search for "MyAquaTrax" and install
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/myaquatrax` folder into your Home Assistant `config/custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **"MyAquaTrax"**
3. Select your **Water Utility** from the dropdown
4. Enter credentials:
   - **SSO utilities** (e.g. Newport Beach): Account Number, Email, Street Number
   - **Standard utilities**: Email, Password
5. Select your **Water Meter** from the discovered list

## Sensors

### Water Usage (per unit)

| Sensor | Description |
|--------|-------------|
| `sensor.g_billing_period_total` | Billing period cumulative water |
| `sensor.g_daily_usage` | Most recent day's water usage |
| `sensor.g_average` | Average usage |
| `sensor.g_highest` | Highest usage |
| `sensor.g_lowest` | Lowest usage |
| `sensor.w_billing_period_total` | Same in CCF/HCF |
| `sensor.w_daily_usage` | Same in CCF/HCF |

### Cost

| Sensor | Description |
|--------|-------------|
| `sensor.d_billing_period_cost` | Billing period cumulative cost |
| `sensor.d_daily_cost` | Most recent day's cost |

### Comparison (Gallons)

| Sensor | Description |
|--------|-------------|
| `sensor.compare_current` | Current month vs. your usage |
| `sensor.compare_previous` | Current month vs. same month last year |
| `sensor.compare_utility` | Current month vs. utility average |
| `sensor.compare_zip` | Current month vs. zip code average |

## Energy Dashboard

To track water usage in the Energy Dashboard:

1. Go to **Settings → Devices & Services → Energy**
2. Click **Add water source**
3. Select `sensor.g_billing_period_total` (Gallons) or `sensor.w_billing_period_total` (CCF)
4. To add cost tracking, use `sensor.d_billing_period_cost` with `device_class=MONETARY`

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /Account/Login` | Standard email/password login |
| `POST /Account/LoginWithSso` | SSO login (Account + Email + Street) |
| `GET /common/GetMasterUtilityList` | List water utilities |
| `GET /MVPDashboard/GetAccountList` | Get customer accounts |
| `GET /MVPUsage/GetMeterDetails` | Discover water meters |
| `GET /MVPUsage/GetWaterUsage` | Usage data (mode=H/D/M/B, type=G/W/D/C) |
| `GET /MVPCompare/GetWaterCompareSpending` | Comparison data |

## Development

```bash
# List all utilities
python myaquatrax_client.py list-utilities

# Test SSO login + meter discovery
python myaquatrax_client.py sso <utility_id> <account> <email> <street>

# Test standard login
python myaquatrax_client.py <utility_id> <email> <password>
```

## Requirements

- Home Assistant 2024.1+ (for `ConfigEntry.runtime_data`)
- `requests` Python library

## License

MIT
