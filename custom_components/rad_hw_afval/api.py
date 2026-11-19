"""Client for the Ximmio waste API used by RAD Hoeksche Waard."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import aiohttp

from .const import API_URL, COMMUNITY, COMPANY_CODE, PICKUP_TYPES, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

# Past dates are only needed as a fallback when the next calendar year has not
# been published yet.
LOOKBACK = timedelta(days=90)


class RadAfvalError(Exception):
    """The API could not be reached or returned an unusable response."""


class RadAfvalAddressNotFoundError(RadAfvalError):
    """The API does not know the address."""


class RadAfvalApiClient:
    """Fetch pickup dates for one address."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        postal_code: str,
        house_number: str,
        house_letter: str = "",
    ) -> None:
        """Initialize the client."""
        self._session = session
        self.postal_code = postal_code.replace(" ", "").upper()
        self.house_number = house_number.strip()
        self.house_letter = house_letter.strip().upper()
        self._address_id: str | None = None

    async def async_get_address_id(self) -> str:
        """Return the Ximmio address ID, looking it up once."""
        if self._address_id is not None:
            return self._address_id

        number: int | str = (
            int(self.house_number) if self.house_number.isdigit() else self.house_number
        )
        body = await self._post(
            "FetchAdress",
            {
                "companyCode": COMPANY_CODE,
                "postCode": self.postal_code,
                "houseNumber": number,
                "houseLetter": self.house_letter,
                "houseNumberAddition": "",
            },
        )
        candidates = [
            item for item in body.get("dataList") or [] if isinstance(item, dict)
        ]

        # Prefer an exact house letter match. Without a letter, fall back to the
        # first result so that e.g. "20" still resolves when only "20A" exists.
        address = next(
            (
                item
                for item in candidates
                if str(item.get("HouseLetter") or "").upper() == self.house_letter
            ),
            None,
        )
        if address is None and candidates and not self.house_letter:
            address = candidates[0]
        if address is None:
            raise RadAfvalAddressNotFoundError(
                f"Address {self.postal_code} {self.house_number}{self.house_letter} not found"
            )
        if not address.get("UniqueId"):
            raise RadAfvalError("FetchAdress response has no UniqueId")

        self._address_id = str(address["UniqueId"])
        return self._address_id

    async def async_get_pickup_dates(self, today: date) -> dict[str, list[date]]:
        """Return the sorted pickup dates per waste type."""
        address_id = await self.async_get_address_id()
        try:
            body = await self._post(
                "GetCalendar",
                {
                    "companyCode": COMPANY_CODE,
                    "uniqueAddressID": address_id,
                    "startDate": (today - LOOKBACK).isoformat(),
                    "endDate": date(today.year + 2, 12, 31).isoformat(),
                    "community": COMMUNITY,
                },
            )
        except RadAfvalError:
            # Look the address up again next time in case its ID changed.
            self._address_id = None
            raise
        return parse_calendar(body.get("dataList") or [])

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to the API and return the body if the API reports success."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.post(
                    f"{API_URL}{endpoint}", json=payload
                ) as response:
                    response.raise_for_status()
                    body = await response.json(content_type=None)
        except TimeoutError as err:
            raise RadAfvalError(f"Timeout calling {endpoint}") from err
        except (aiohttp.ClientError, ValueError) as err:
            raise RadAfvalError(f"Error calling {endpoint}: {err}") from err

        # Application errors arrive as HTTP 200 with "status": false.
        if not isinstance(body, dict) or body.get("status") is not True:
            code = body.get("messageCode") if isinstance(body, dict) else None
            raise RadAfvalError(f"{endpoint} returned an error (messageCode {code})")
        return body


def parse_calendar(entries: list[Any]) -> dict[str, list[date]]:
    """Map GetCalendar entries to sorted pickup dates per waste type."""
    result: dict[str, set[date]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("_pickupTypeText") or "").upper()
        waste_type = PICKUP_TYPES.get(code)
        if waste_type is None:
            _LOGGER.debug("Ignoring unsupported pickup type %r", code)
            continue
        for raw in entry.get("pickupDates") or []:
            try:
                pickup = date.fromisoformat(str(raw)[:10])
            except ValueError:
                _LOGGER.warning("Ignoring invalid pickup date %r for %s", raw, code)
                continue
            result.setdefault(waste_type, set()).add(pickup)
    return {waste_type: sorted(dates) for waste_type, dates in result.items()}


def next_pickup(dates: list[date], today: date) -> date | None:
    """Return the first pickup on or after today, else the most recent one.

    The fallback covers the weeks around new year when the next calendar has
    not been published yet.
    """
    return next(
        (pickup for pickup in dates if pickup >= today), dates[-1] if dates else None
    )
