#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Kevin White
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""
Count the NARA Catalog API requests this computer has made each month.

NARA allows each API key 10,000 queries a month by default. Going over
blocks the key until the first of the next month, when the count starts
again. The API does not report how many queries are used or left, so
GWizard counts them itself: every request that got an answer from NARA
(any HTTP status) is counted, by calendar month in UTC. Requests that never
reached NARA (no network, a timeout before connecting) are not.

The count is kept in a small JSON file in the Gramps user folder, shared by
every NARA window and the Multi-Archive Record Scan. It only knows about
requests made from this Gramps user account: queries made with the same key
elsewhere are not included.

Rate-limit or quota headers in NARA's answers, should NARA ever send any,
are saved with the count so they can be read later.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import datetime
import json
import logging
import os
import threading
from typing import Any, Callable, Mapping

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

# NARA's default allowance per API key and month.
NARA_MONTHLY_LIMIT = 10000

# What a request was for.
KIND_SEARCH = "search"  # a catalog search
KIND_RECORD = "record"  # the machine-read page text of one record
KIND_VALIDATE = "validate"  # the check of the API key

_FILE_VERSION = 1
# Months of counts kept in the file.
_MONTHS_KEPT = 24
# Answer headers worth keeping (matched on the lower-cased name).
_HEADER_WORDS = ("ratelimit", "rate-limit", "quota", "retry-after", "usage")


def _utc_now() -> datetime.datetime:
    """Return the current time in UTC."""
    return datetime.datetime.now(datetime.timezone.utc)


def month_key(when: datetime.datetime) -> str:
    """Return the "YYYY-MM" key of a time's month."""
    return f"{when.year:04d}-{when.month:02d}"


def next_reset(when: datetime.datetime) -> datetime.date:
    """Return the first day of the month after ``when``."""
    if when.month == 12:
        return datetime.date(when.year + 1, 1, 1)
    return datetime.date(when.year, when.month + 1, 1)


def default_usage_path() -> str:
    """Return the usage file in the Gramps user folder."""
    from gramps.gen.const import USER_DATA

    return os.path.join(USER_DATA, "gwizard", "nara", "usage.json")


def limit_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    """Return the rate-limit and quota headers of an answer, if any."""
    found: dict[str, str] = {}
    for name, value in dict(headers or {}).items():
        low = str(name).casefold()
        if any(word in low for word in _HEADER_WORDS):
            found[str(name)] = str(value)
    return found


# ------------------------------------------------------------
#
# NaraUsage
#
# ------------------------------------------------------------
class NaraUsage:
    """
    The monthly count of NARA API requests, kept in a JSON file.

    Each ``record`` reads the file, adds the request and writes it back, so
    two Gramps windows (or two Gramps instances) add to the same count.
    Safe to call from a worker thread.
    """

    def __init__(
        self,
        path: str | None = None,
        limit: int = NARA_MONTHLY_LIMIT,
        clock: Callable[[], datetime.datetime] = _utc_now,
    ) -> None:
        """
        :param path: The usage file; None keeps the count in memory only.
        :param limit: The monthly allowance shown with the count.
        :param clock: Returns the current time (replaced in tests).
        """
        self.path = path
        self.limit = int(limit)
        self._clock = clock
        self._lock = threading.Lock()
        self._memory: dict[str, Any] = {}

    # -- file ----------------------------------------------------------
    def _read(self) -> dict[str, Any]:
        """Return the stored counts (empty when there is no usable file)."""
        if not self.path:
            return self._memory
        try:
            with open(self.path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as err:
            LOG.warning("Ignoring unreadable NARA usage file %s: %s", self.path, err)
            return {}
        if not isinstance(raw, dict) or raw.get("version") != _FILE_VERSION:
            return {}
        return raw

    def _write(self, data: dict[str, Any]) -> None:
        """Store the counts."""
        data["version"] = _FILE_VERSION
        if not self.path:
            self._memory = data
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError as err:
            LOG.warning("Could not save the NARA usage file %s: %s", self.path, err)

    # -- counting ------------------------------------------------------
    def record(
        self,
        kind: str,
        status: int | None = None,
        headers: Mapping[str, Any] | None = None,
    ) -> int:
        """
        Count one request that NARA answered, and return this month's total.

        :param kind: KIND_SEARCH, KIND_RECORD or KIND_VALIDATE.
        :param status: The HTTP status of the answer.
        :param headers: The answer's headers; rate-limit headers are kept.
        """
        now = self._clock()
        key = month_key(now)
        with self._lock:
            data = self._read()
            months = data.setdefault("months", {})
            month = months.setdefault(key, {"total": 0})
            month["total"] = int(month.get("total") or 0) + 1
            month[kind] = int(month.get(kind) or 0) + 1
            if status is not None and status != 200:
                failed = month.setdefault("failed", {})
                failed[str(status)] = int(failed.get(str(status)) or 0) + 1
            if status == 429:
                month["blocked_at"] = now.isoformat(timespec="seconds")
            month["last_request"] = now.isoformat(timespec="seconds")
            kept = limit_headers(headers)
            if kept:
                data["last_limit_headers"] = kept
            for old in sorted(months)[:-_MONTHS_KEPT]:
                months.pop(old, None)
            self._write(data)
            return month["total"]

    def used(self) -> int:
        """Return how many requests were counted this month."""
        with self._lock:
            month = self._read().get("months", {}).get(month_key(self._clock()), {})
        return int(month.get("total") or 0)

    def remaining(self) -> int:
        """Return how many requests are left this month (never below 0)."""
        return max(0, self.limit - self.used())

    def blocked(self) -> bool:
        """Return True when NARA answered 429 (too many requests) this month."""
        with self._lock:
            month = self._read().get("months", {}).get(month_key(self._clock()), {})
        return bool(month.get("blocked_at"))

    def month_detail(self) -> dict[str, Any]:
        """Return this month's stored counts (total, per kind, failures)."""
        with self._lock:
            month = self._read().get("months", {}).get(month_key(self._clock()), {})
        return dict(month)

    def last_limit_headers(self) -> dict[str, str]:
        """Return the rate-limit headers NARA last sent, if it ever sent any."""
        with self._lock:
            return dict(self._read().get("last_limit_headers") or {})

    def summary_text(self) -> str:
        """
        Return a one-line summary, such as
        "NARA: 1,234 of 10,000 queries used this month; resets Dec 1".
        """
        now = self._clock()
        used = self.used()
        reset = next_reset(now)
        text = _(
            "NARA: %(used)s of %(limit)s queries used this month; resets %(reset)s"
        ) % {
            "used": f"{used:,}",
            "limit": f"{self.limit:,}",
            "reset": reset.strftime("%b %d").replace(" 0", " "),
        }
        if self.blocked():
            text += " " + _("(NARA refused requests: over the limit)")
        return text


_SHARED: NaraUsage | None = None
_SHARED_LOCK = threading.Lock()


def shared_usage() -> NaraUsage:
    """Return the usage counter every NARA client shares by default."""
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            try:
                path: str | None = default_usage_path()
            except Exception:
                LOG.warning("No Gramps user folder; NARA usage kept in memory")
                path = None
            _SHARED = NaraUsage(path)
        return _SHARED
