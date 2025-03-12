# RAD Hoeksche Waard Afval

Home Assistant integration for RAD Hoeksche Waard waste collection.

## Installation

### Method 1: HACS (Recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance.
2. Add this repository as a custom repository in HACS:
   - Go to HACS in your Home Assistant instance
   - Click on "Integrations"
   - Click the three dots in the top right corner
   - Select "Custom repositories"
   - Enter `https://github.com/keesmod/ha-rad-hw` in the "Repository" field
   - Select "Integration" as the Category
   - Click "Add"
3. Search for "RAD Hoeksche Waard Afval" in HACS and install it
4. Restart Home Assistant
5. Add the integration via the Home Assistant UI (Settings -> Devices & Services -> Add Integration)
6. Search for "RAD Hoeksche Waard Afval" and follow the configuration steps

### Method 2: Manual Installation

1. Copy the `custom_components/rad_hw_afval` directory to your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Add the integration via the Home Assistant UI.

## Configuration

The integration can be configured via the Home Assistant UI. You will need to provide:

- Postal code (e.g., 3262CD)
- Street number (e.g., 5)

## Features

- Creates sensors for different waste types (rest, gft, papier, pmd)
- Each sensor shows the number of days until the next collection
- The next collection date is available as an attribute
- If a future collection date isn't available, the most recent past date will be shown with an `is_past_date` attribute set to `true`
- Compatible with Home Assistant 2025.3.2 and likely with earlier versions

## Technical Details

This integration uses the Ximmio API to fetch waste collection data for RAD Hoeksche Waard. The API endpoints used are:

- `https://wasteapi2.ximmio.com/api/FetchAdress` - To get the address ID
- `https://wasteapi2.ximmio.com/api/GetCalendar` - To get the waste collection calendar

The integration maps the waste types returned by the API to the following sensor types:

- GREEN -> gft
- GREY -> rest
- PAPER -> papier
- PACKAGES -> pmd

### How It Works

1. The integration retrieves a list of pickup dates for each waste type from the API
2. For each waste type, it finds the earliest upcoming collection date
3. If no future dates are available for a waste type, it falls back to the most recent past date and adds an `is_past_date: true` attribute
4. Sensors show collection dates as attributes along with the days until collection

### Recent Improvements (v1.2.0+)

- Fixed issue with GFT and PMD missing dates by properly processing all dates in the API response
- Added community parameter to API calls for better matching to browser behavior
- Extended date range to retrieve more future dates (3 years instead of 1 year)
- Added support for fallback to past dates when no future dates are available
- Added `is_past_date` attribute to indicate when a shown date is in the past

## Troubleshooting

If you encounter issues with the integration, you can enable debug logging by adding the following to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.rad_hw_afval: debug
```

### Common Issues

- **Missing waste types**: Some waste types might not have future collection dates in the API. The integration will show the most recent past date with the `is_past_date` attribute set to `true`.
- **Different dates than shown in the RAD app**: Verify your postal code and street number are correct. If the dates still differ, please report it as an issue.

## Testing

The integration includes a standalone test script:

- `standalone_test.py` - Tests the API client with live data

To run the test:

```bash
cd custom_components/rad_hw_afval
python3 standalone_test.py YOUR_POSTAL_CODE YOUR_STREET_NUMBER
```

Add the `--include-past` flag to see past collection dates as well:

```bash
python3 standalone_test.py YOUR_POSTAL_CODE YOUR_STREET_NUMBER --include-past
```

## Credits

This integration is based on the [Afvalbeheer](https://github.com/pippyn/Home-Assistant-Sensor-Afvalbeheer) integration.

## License

This integration is licensed under the MIT License.
