"""API client for RAD Hoeksche Waard Afval."""

import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Optional, Any

import aiohttp

from .const import API_URL, COMPANY_CODE


_LOGGER = logging.getLogger(__name__)


class ApiError(Exception):
    """Exception raised for API communication errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        """Initialize the exception."""
        self.status_code = status_code
        super().__init__(message)


class RadAfvalApiClient:
    """API client for RAD Hoeksche Waard Afval."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        postal_code: str,
        street_number: str,
    ) -> None:
        """Initialize the API client."""
        self.session = session
        self.postal_code = postal_code.strip().replace(" ", "")  # Format postal code
        self.street_number = street_number
        self.base_url = API_URL
        self.company_code = COMPANY_CODE
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json",
            "Referer": "https://radhw.ximmio.com/",
        }

    async def async_get_data(self) -> Optional[Dict[str, Dict]]:
        """Get waste collection data from the API."""
        try:
            _LOGGER.debug("Requesting waste collection data from %s", self.base_url)

            # Step 1: Get the address ID
            address_id = await self._get_address_id()
            if not address_id:
                return None

            # Step 2: Get the calendar data using the address ID
            calendar_data = await self._get_calendar_data(address_id)
            if not calendar_data:
                return None

            # Step 3: Process the calendar data
            result = self._process_data(calendar_data)
            return result

        except ApiError as error:
            _LOGGER.error("API Error: %s", error)
            return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            _LOGGER.error("Connection error: %s", error)
            return None
        except Exception as error:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error: %s", error)
            return None

    async def _get_address_id(self) -> Optional[str]:
        """Get the address ID from the API."""
        url = f"{self.base_url}FetchAdress"

        # Convert house_number to integer if it's numeric
        house_number = self.street_number
        try:
            if isinstance(house_number, str) and house_number.isdigit():
                house_number = int(house_number)
        except (ValueError, TypeError):
            pass  # Keep original value if conversion fails

        payload = {
            "companyCode": self.company_code,
            "postCode": self.postal_code,
            "houseNumber": house_number,
            "houseLetter": "",
            "houseNumberAddition": "",
        }

        _LOGGER.debug("Getting address ID with payload: %s", payload)

        try:
            async with self.session.post(
                url, headers=self._headers, json=payload
            ) as response:
                if response.status != 200:
                    raise ApiError(
                        f"Error getting address ID: {response.status} {response.reason}",
                        response.status,
                    )

                address_data = await response.json()

                if not address_data.get("dataList"):
                    _LOGGER.error(
                        "No addresses found for postal code %s and house number %s",
                        self.postal_code,
                        self.street_number,
                    )
                    return None

                # Note: The API returns "UniqueId" with a capital U
                address_id = address_data["dataList"][0]["UniqueId"]
                _LOGGER.debug("Found address ID: %s", address_id)
                return address_id

        except aiohttp.ClientResponseError as error:
            raise ApiError(
                f"HTTP error fetching address ID: {error.status}", error.status
            ) from error
        except (KeyError, IndexError) as error:
            raise ApiError(f"Invalid address data response: {error}") from error

    async def _get_calendar_data(self, address_id: str) -> Optional[Dict[str, Any]]:
        """Get calendar data from the API."""
        url = f"{self.base_url}GetCalendar"
        now = datetime.now()

        # Use a longer date range to match what the browser is doing
        start_date = date(now.year, now.month, 1)
        start_date = start_date - timedelta(days=90)  # Look back 3 months
        end_date = date(now.year + 3, 1, 31)  # Look ahead 3 years

        payload = {
            "companyCode": self.company_code,
            "uniqueAddressID": address_id,
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "community": "Hoeksche Waard",  # Add community parameter
        }

        _LOGGER.debug("Getting calendar data with payload: %s", payload)

        try:
            async with self.session.post(
                url, headers=self._headers, json=payload
            ) as response:
                if response.status != 200:
                    raise ApiError(
                        f"Error getting calendar data: {response.status} {response.reason}",
                        response.status,
                    )

                calendar_data = await response.json()

                if calendar_data is None:
                    raise ApiError("Received empty calendar data from the API")

                _LOGGER.debug(
                    "Received calendar data with %d items",
                    len(calendar_data.get("dataList", [])),
                )

                return calendar_data

        except aiohttp.ClientResponseError as error:
            raise ApiError(
                f"HTTP error fetching calendar data: {error.status}", error.status
            ) from error

    def _process_data(self, calendar_data: Dict[str, Any]) -> Dict[str, Dict]:
        """Process the calendar data and extract waste collection dates."""
        result = {}
        today = datetime.now().date()

        # Mapping of Ximmio waste types to our waste types
        waste_type_mapping = {
            # Exact matches from the API
            "GREEN": "gft",
            "GREY": "rest",
            "PAPER": "papier",
            "PACKAGES": "pmd",
            "PLASTIC": "pmd",
            "TEXTIEL": "textiel",
            "GLAS": "glas",
            # Additional mappings for flexibility
            "REST": "rest",
            "GFT": "gft",
            "PAPIER": "papier",
            "PMD": "pmd",
            "Restafval": "rest",
            "GFT-container": "gft",
            "Papiercontainer": "papier",
            "PMD-container": "pmd",
            "Plastic": "pmd",
            "Textiel": "textiel",
            "Glas": "glas",
        }

        # Store most recent past dates as fallback
        most_recent_past_dates = {}

        try:
            pickup_entries = calendar_data.get("dataList", [])

            if not pickup_entries:
                _LOGGER.warning("No pickup entries found in calendar data")
                return result

            _LOGGER.debug("Processing %d pickup entries", len(pickup_entries))

            # Process all entries
            for pickup_entry in pickup_entries:
                try:
                    # Extract pickup type
                    pickup_type = self._extract_pickup_type(pickup_entry)
                    if not pickup_type:
                        continue

                    # Find the normalized waste type
                    normalized_type = self._normalize_waste_type(
                        pickup_type, waste_type_mapping
                    )
                    if not normalized_type:
                        continue

                    # Process all pickup dates in the array
                    pickup_dates = pickup_entry.get("pickupDates", [])
                    if not pickup_dates:
                        continue

                    _LOGGER.debug(
                        "Found %d dates for %s: %s",
                        len(pickup_dates),
                        pickup_type,
                        pickup_dates,
                    )

                    for pickup_date_str in pickup_dates:
                        try:
                            # Parse the date string
                            if (
                                isinstance(pickup_date_str, str)
                                and "T" in pickup_date_str
                            ):
                                pickup_date_str = pickup_date_str.split("T")[0]

                            pickup_date = datetime.strptime(
                                pickup_date_str, "%Y-%m-%d"
                            ).date()

                            # Calculate days until pickup
                            days_until = (pickup_date - today).days

                            if pickup_date >= today:
                                # Future date - this is ideal
                                if normalized_type in result:
                                    existing_date = result[normalized_type]["next_date"]
                                    if pickup_date < existing_date:
                                        result[normalized_type] = {
                                            "next_date": pickup_date,
                                            "days_until": days_until,
                                        }
                                else:
                                    result[normalized_type] = {
                                        "next_date": pickup_date,
                                        "days_until": days_until,
                                    }
                                    _LOGGER.debug(
                                        "Found %s waste with pickup date: %s (%d days from now)",
                                        normalized_type,
                                        pickup_date.isoformat(),
                                        days_until,
                                    )
                            else:
                                # Past date - store as fallback if it's the most recent
                                if normalized_type in most_recent_past_dates:
                                    if (
                                        pickup_date
                                        > most_recent_past_dates[normalized_type][
                                            "next_date"
                                        ]
                                    ):
                                        most_recent_past_dates[normalized_type] = {
                                            "next_date": pickup_date,
                                            "days_until": days_until,
                                        }
                                else:
                                    most_recent_past_dates[normalized_type] = {
                                        "next_date": pickup_date,
                                        "days_until": days_until,
                                    }
                                    _LOGGER.debug(
                                        "Found past %s waste with pickup date: %s (%d days ago)",
                                        normalized_type,
                                        pickup_date.isoformat(),
                                        abs(days_until),
                                    )
                        except ValueError as err:
                            _LOGGER.warning(
                                "Invalid date format: %s - Error: %s",
                                pickup_date_str,
                                err,
                            )
                except Exception as err:
                    _LOGGER.warning("Error processing pickup entry: %s", err)

            # Fill in most recent past dates for waste types that don't have future dates
            for waste_type, past_data in most_recent_past_dates.items():
                if waste_type not in result:
                    _LOGGER.info(
                        "No future %s dates found, using most recent past date: %s (%d days ago)",
                        waste_type,
                        past_data["next_date"].isoformat(),
                        abs(past_data["days_until"]),
                    )
                    result[waste_type] = past_data

        except (KeyError, TypeError) as err:
            _LOGGER.error("Error processing calendar data: %s", err)

        return result

    def _extract_pickup_type(self, pickup: Dict[str, Any]) -> Optional[str]:
        """Extract pickup type from the pickup object."""
        # Try different field names that might contain the pickup type
        for field in [
            "pickupTypeText",  # common field name in API
            "_pickupTypeText",  # sometimes present with underscore
            "pickupType",
            "description",
            "wastetype",
        ]:
            if field in pickup and pickup[field]:
                _LOGGER.debug(
                    "Found pickup type in field '%s': %s", field, pickup[field]
                )
                return pickup[field]

        _LOGGER.debug("Could not find pickup type in pickup object")
        return None

    def _extract_pickup_date(self, pickup: Dict[str, Any]) -> Optional[str]:
        """Extract pickup date from the pickup object."""
        # Try different field names that might contain the pickup date
        for field in ["pickupDates", "date", "pickupDate"]:
            if field in pickup:
                if isinstance(pickup[field], list) and pickup[field]:
                    _LOGGER.debug(
                        "Found pickup date in list field '%s': %s",
                        field,
                        pickup[field][0],
                    )
                    return pickup[field][0]
                elif pickup[field]:
                    _LOGGER.debug(
                        "Found pickup date in field '%s': %s", field, pickup[field]
                    )
                    return pickup[field]

        _LOGGER.debug("Could not find pickup date in pickup object")
        return None

    def _process_pickup(
        self,
        result: Dict[str, Dict],
        pickup_type: str,
        pickup_date_str: str,
        waste_type_mapping: Dict[str, str],
        today: date,
    ) -> None:
        """Process a single pickup entry and add it to the result if valid."""
        try:
            # Parse the date string (format is usually 'YYYY-MM-DD')
            if isinstance(pickup_date_str, str) and "T" in pickup_date_str:
                pickup_date_str = pickup_date_str.split("T")[0]

            pickup_date = datetime.strptime(pickup_date_str, "%Y-%m-%d").date()

            # Find the normalized waste type
            normalized_type = self._normalize_waste_type(
                pickup_type, waste_type_mapping
            )
            if not normalized_type:
                return

            # Only process future dates
            if pickup_date >= today:
                # Check if we already have a closer date for this waste type
                if normalized_type in result:
                    existing_date = result[normalized_type]["next_date"]
                    if pickup_date < existing_date:
                        days_until = (pickup_date - today).days
                        result[normalized_type] = {
                            "next_date": pickup_date,
                            "days_until": days_until,
                        }
                else:
                    days_until = (pickup_date - today).days
                    result[normalized_type] = {
                        "next_date": pickup_date,
                        "days_until": days_until,
                    }
                    _LOGGER.debug(
                        "Found %s waste with pickup date: %s (%d days from now)",
                        normalized_type,
                        pickup_date.isoformat(),
                        days_until,
                    )
        except ValueError as err:
            _LOGGER.warning("Invalid date format: %s - Error: %s", pickup_date_str, err)

    def _normalize_waste_type(
        self, pickup_type: str, waste_type_mapping: Dict[str, str]
    ) -> Optional[str]:
        """Normalize the waste type based on mapping."""
        # First try exact match
        if str(pickup_type) in waste_type_mapping:
            return waste_type_mapping[str(pickup_type)]

        # Try partial match
        for key, value in waste_type_mapping.items():
            if key.lower() in str(pickup_type).lower():
                return value

        _LOGGER.debug("Unknown pickup type: %s", pickup_type)
        return None
