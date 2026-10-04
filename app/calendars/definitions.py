"""The calendars calendar-svc owns, and their sources in precedence order.

Moved here from mkt-data's CALENDARS (app/calendars/service.py) in phase 2,
Part A: mkt-data keeps fetching and parsing each source into near-raw rows;
which sources make up a calendar, and which one wins a date, is decided
here. Source names are mkt-data's (`CalendarSources.ListSources`).

kind: "published" (a publisher's page or document), "rules" (a rules file
with cited exceptions) or "projected" (rules run forward to 2100; fills only
years no other source covers, and always a calendar's last source).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceDef:
    name: str
    kind: str = "published"

    @property
    def projected(self) -> bool:
        return self.kind == "projected"


@dataclass(frozen=True)
class CalendarDef:
    name: str
    description: str
    timezone: str
    sources: tuple[SourceDef, ...]  # highest precedence first
    # (month, day) from which next year's dates should be published (the
    # "next year published" check). K.8 and NYSE list years ahead, so for them
    # next year is always due; SIFMA publishes in mid-December.
    next_year_due: tuple[int, int] = (1, 1)

    @property
    def source_names(self) -> list[str]:
        return [x.name for x in self.sources]


CALENDARS: dict[str, CalendarDef] = {
    "FED": CalendarDef(
        name="FED",
        description="Federal Reserve Banks and Fedwire: closed weekdays",
        timezone="America/New_York",
        sources=(
            SourceDef("FED-K8"),
            *(SourceDef(f"FED-NYFED-{year}") for year in range(2009, 2002, -1)),
            SourceDef("FED-RULES", "rules"),
            SourceDef("FED-PROJECTED", "projected"),
        ),
    ),
    "SIFMA-US": CalendarDef(
        name="SIFMA-US",
        description="US bond market (SIFMA recommendations): full closes and early closes",
        timezone="America/New_York",
        next_year_due=(12, 20),
        sources=(
            SourceDef("SIFMA-US-HOLIDAYS"),
            SourceDef("SIFMA-US-ARCHIVE"),
            SourceDef("SIFMA-US-HISTORY"),
            SourceDef("SIFMA-US-EXCEPTIONS", "rules"),
            SourceDef("SIFMA-US-PROJECTED", "projected"),
        ),
    ),
    "NYSE": CalendarDef(
        name="NYSE",
        description="NYSE equities: full closes and early closes (equities close time)",
        timezone="America/New_York",
        sources=(
            SourceDef("NYSE-HOURS"),
            SourceDef("NYSE-HISTORY"),
            SourceDef("NYSE-RULES", "rules"),
            SourceDef("NYSE-PROJECTED", "projected"),
        ),
    ),
}
