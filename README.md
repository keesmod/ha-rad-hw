# RAD Hoeksche Waard Afval

Home Assistant custom integration for the waste collection calendar of
[RAD Hoeksche Waard](https://www.radbv.nl/). For one address it creates a date
sensor per waste type (Restafval, GFT, Oud Papier, PMD) that shows the next
collection day.

The data comes from the Ximmio API that RAD's own online waste calendar uses. This
project is not affiliated with RAD Hoeksche Waard or Ximmio.

Requires Home Assistant 2025.3.2 or newer.

## Installation

### Home Assistant 2026.11 and newer (Marketplace)

Since Home Assistant 2026.11, HACS is built into Home Assistant as the
**Marketplace**. This integration is not in the default list, so you add it from a
link:

1. Go to **Settings** > **Marketplace**. Only administrators can open it. The first
   time, you have to accept the warning about community content.
2. In the upper-right corner, select **Add from link**.
3. Under **GitHub link**, enter `keesmod/ha-rad-hw` and select **Add**. Adding a
   custom repository requires a connected GitHub account. If you have not
   connected one yet, the Marketplace asks you to do so. If it asks for the type,
   choose **Integration**.
4. Open the repository in the list, select **Install** and confirm.
5. If the setup dialog does not open on its own, go to **Settings** > **Devices &
   services** > **Add integration** and search for **RAD Hoeksche Waard Afval**.
   If Home Assistant shows a repair asking for a restart, restart first.

If you installed this integration through HACS before updating to 2026.11, the
Marketplace migrates it automatically. You don't need to add it again.

### Home Assistant 2026.10 and older (HACS)

1. Install [HACS](https://hacs.xyz/) if you don't have it yet.
2. In HACS, open the three-dot menu in the upper-right corner and select
   **Custom repositories**.
3. Enter `https://github.com/keesmod/ha-rad-hw`, choose **Integration** as the
   type (category), and select **Add**.
4. Search for **RAD Hoeksche Waard Afval**, download it and restart Home
   Assistant.
5. Go to **Settings** > **Devices & services** > **Add integration** and search
   for **RAD Hoeksche Waard Afval**.

### Manual

1. Copy `custom_components/rad_hw_afval` from this repository to the
   `custom_components` folder in your Home Assistant configuration directory.
2. Restart Home Assistant.
3. Add the integration under **Settings** > **Devices & services** > **Add
   integration**.

## Configuration

Setup asks for:

| Field | Description |
| --- | --- |
| Postal code | Dutch postal code, e.g. `1234AB`. Spaces and lowercase letters are accepted. |
| House number | A number with an optional house letter: `1`, `12a`, `12 A` and `12-a` all work. If your address has a house letter, enter it. Other additions are not supported. |
| Date format | [strftime](https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes) format for the `formatted_date` attribute. Default: `%d-%m-%Y`. |

During setup the integration looks up the address in RAD's calendar, so a typo
is reported straight away (see [Troubleshooting](#troubleshooting)). Each address
can be added once. To track several addresses, add the integration again for
each address.

To change the date format later, go to **Settings** > **Devices & services** >
**RAD Hoeksche Waard Afval** and select the cogwheel (**Configure**) next to the
address. Clear the field to go back to the default. The integration reloads with
the new format.

## Entities

The integration creates one sensor for each waste type. The sensors are grouped
under a service named `RAD HW Afval <postal code> <house number>`, for example
`RAD HW Afval 1234AB 1`.

Don't need a waste type? Disable its sensor:

1. Go to **Settings** > **Devices & services** > **Entities** and select the
   sensor.
2. Select the **Settings** (cogwheel) icon in the upper-right corner.
3. Turn off **Enabled** and select **Update**.

To enable it again, open the service page and select **+N disabled entities**,
or use **Filters** > **Status** > **Disabled** in the entity list. An enabled
sensor appears again after a short delay. See
[Disabling an entity](https://www.home-assistant.io/docs/configuration/customizing-devices/)
in the Home Assistant documentation.

| Waste type | Sensor name | `waste_type` attribute |
| --- | --- | --- |
| Residual waste | Restafval | `rest` |
| Organic waste | GFT | `gft` |
| Paper | Oud Papier | `papier` |
| Plastic, metal and drink cartons | PMD | `pmd` |

**State:** the next collection date. The sensors use the `date` device class, so
the state looks like `2026-11-27`. On collection day the state is today's date.

**Attributes:**

| Attribute | Meaning |
| --- | --- |
| `next_pickup_in_days` | Days until the collection: `0` is today, `1` is tomorrow. Negative when `is_past_date` is `true`. |
| `is_past_date` | `true` when no future date is known and the sensor shows the most recent past collection instead (see [How it works](#how-it-works)). |
| `formatted_date` | The date in the configured date format, e.g. `27-11-2026`. |
| `waste_type` | `rest`, `gft`, `papier` or `pmd`. |

**Updates:**

- The state moves to the next date just after midnight in the Home Assistant time
  zone. This does not call the API.
- The calendar is downloaded at startup and then every 12 hours. If the calendar
  service can't be reached, the integration tries again after 30 minutes.
- While the last download failed, the sensors are unavailable. A sensor is also
  unavailable when the calendar has no dates for that waste type at your address.

### Entity IDs

- **Upgrading from 1.2.x:** your entities keep their entity IDs, for example
  `sensor.rad_hw_afval_restafval`, `sensor.rad_hw_afval_gft`,
  `sensor.rad_hw_afval_oud_papier` and `sensor.rad_hw_afval_pmd`. Your automations
  and dashboards keep working. Waste types you had deselected in 1.2.x are added
  as disabled sensors. If 1.2.x never created that sensor, it gets a new-style
  entity ID, for example `sensor.rad_hw_afval_1234ab_1_pmd`.
- **New installations:** entity IDs are derived from the service name and the
  sensor name, for example `sensor.rad_hw_afval_1234ab_1_restafval` and
  `sensor.rad_hw_afval_1234ab_1_oud_papier`.

To find your entity IDs, go to **Settings** > **Devices & services** >
**Entities** and search for `RAD HW Afval`.

## Examples

Replace the entity IDs in these examples with your own.

### Dashboard

A sections view that shows each waste type with the days until collection and
the date. Add a view to a dashboard, open its YAML editor and paste the complete
view configuration:

```yaml
type: sections
max_columns: 4
title: Afval
path: afval
sections:
  - type: grid
    cards:
      - type: heading
        heading: Afval
        heading_style: title
        icon: mdi:trash-can
      - type: tile
        entity: sensor.rad_hw_afval_1234ab_1_gft
        show_entity_picture: true
        state_content:
          - next_pickup_in_days
          - state
        grid_options:
          columns: full
      - type: tile
        entity: sensor.rad_hw_afval_1234ab_1_pmd
        show_entity_picture: true
        state_content:
          - next_pickup_in_days
          - state
        grid_options:
          columns: full
      - type: tile
        entity: sensor.rad_hw_afval_1234ab_1_restafval
        show_entity_picture: true
        state_content:
          - next_pickup_in_days
          - state
        grid_options:
          columns: full
      - type: tile
        entity: sensor.rad_hw_afval_1234ab_1_oud_papier
        show_entity_picture: true
        state_content:
          - next_pickup_in_days
          - state
        grid_options:
          columns: full
```

### Automation: put the bin out the evening before

Sends a notification at 19:00 when the residual waste is collected the next day.
Replace `notify.mobile_app_your_phone` with your own notify action.

```yaml
alias: Put the bin out
triggers:
  - trigger: time
    at: "19:00:00"
conditions:
  - condition: state
    entity_id: sensor.rad_hw_afval_1234ab_1_restafval
    attribute: next_pickup_in_days
    state: 1
actions:
  - action: notify.mobile_app_your_phone
    data:
      message: "Restafval is collected tomorrow: put the bin out tonight."
```

## How it works

The integration uses two endpoints of the Ximmio waste API at
`https://wasteapi2.ximmio.com/api/`:

1. `FetchAdress` turns the postal code, house number and house letter into a
   Ximmio address ID. The ID is looked up once and reused. The address with the
   exact house letter is used. Without a house letter, the first result is used
   when there is no address without a letter (e.g. `20` finds `20A` if that is
   the only one). After a failed calendar download the ID is looked up again.
2. `GetCalendar` returns the collection dates for that address, from 90 days ago
   up to 31 December two years ahead.

The pickup types in the calendar are mapped to sensors as follows. Other pickup
types are ignored.

| Ximmio pickup type | Sensor |
| --- | --- |
| `GREY` | Restafval (`rest`) |
| `GREEN` | GFT (`gft`) |
| `PAPER` | Oud Papier (`papier`) |
| `PACKAGES` | PMD (`pmd`) |

Each sensor shows the first collection date on or after today. "Today" is the
current date in the Home Assistant time zone.

**Year-end fallback:** RAD publishes the calendar per year. Around the turn of
the year the calendar for the new year may not be available yet. If no future
date is known for a waste type, the sensor shows the most recent past collection,
sets `is_past_date` to `true`, and `next_pickup_in_days` becomes negative. Once
RAD publishes the new calendar, the next 12-hourly update picks it up.

## Troubleshooting

To enable debug logging, add this to `configuration.yaml` and restart Home
Assistant:

```yaml
logger:
  default: info
  logs:
    custom_components.rad_hw_afval: debug
```

Common problems:

- **"RAD Hoeksche Waard does not know this address"** (`address_not_found`): the
  calendar service has no address for this postal code and house number. Check
  both, and check that the address is in the municipality of Hoeksche Waard.
- **"Could not reach the RAD Hoeksche Waard calendar service"**
  (`cannot_connect`): the service could not be reached or returned an error. Try
  again later.
- **Setup keeps retrying after a restart:** the calendar service was unreachable
  when Home Assistant started. Home Assistant retries the setup automatically.
- **All sensors are unavailable:** the last calendar download failed. The
  integration tries again every 30 minutes. Check the log for the error.
- **One sensor is unavailable:** the calendar contains no dates for that waste
  type at your address. You can disable that sensor (see [Entities](#entities)).
- **A sensor shows a past date:** see the year-end fallback in
  [How it works](#how-it-works).
- **Dates differ from the RAD app:** check the postal code, house number and
  house letter. If they are correct, please
  [open an issue](https://github.com/keesmod/ha-rad-hw/issues).

## Changelog

### 1.3.0

- Works on Home Assistant 2026.10 and newer: the integration no longer depends on
  the `async_timeout` package, which recent Home Assistant releases no longer
  include.
- Dates are correct right after midnight. The state moves to the next collection
  at local midnight instead of at the next 12-hourly update, and "today" now
  follows the Home Assistant time zone.
- The address is checked against RAD's calendar during setup, with clear errors
  for an unknown address or an unreachable service.
- House numbers with a house letter, such as `12a`, are supported.
- After a failed update the integration retries after 30 minutes instead of
  12 hours.
- The documentation and issue links in the integration point to this repository.
- The integration is shown as a service instead of a device.
- The integration has its own icon (Home Assistant 2026.3 and newer).
- All four waste types always get a sensor, following Home Assistant's
  guidelines; the waste type selection in setup and options is gone. Disable the
  sensors you don't need. When you upgrade, waste types you had deselected
  become disabled sensors, so nothing new appears on your dashboards.
- Entity names follow Home Assistant's naming rules. The device page shows
  `Restafval` instead of repeating `RAD HW Afval`, and the friendly name now
  includes the address, e.g. `RAD HW Afval 1234AB 1 Restafval`. Entity IDs of
  existing installations do not change.

For earlier versions, see the
[releases](https://github.com/keesmod/ha-rad-hw/releases).

## Credits

This integration is based on the
[Afvalbeheer](https://github.com/pippyn/Home-Assistant-Sensor-Afvalbeheer)
integration.

## License

This integration is licensed under the [MIT License](LICENSE).
