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
    # Which kind of source must cover next year for it to count as there: "published" (a publisher, so a
    # projection can't hide a missing year), or "rules" for a calendar with no publisher we capture (CME's,
    # whose rules files are extended a year at a time from its notices).
    next_year_from: str = "published"

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
    # CME's business days for its rates and FX futures (mkt-data docs/phase-4.md, "Calendars"): rules cited from
    # CME's notices, no captured publisher. Next year is due in the rules file from December 1.
    "CME-IR": CalendarDef(
        name="CME-IR",
        description="CME Group U.S. interest rate futures: days with a trade date and settlement",
        timezone="America/Chicago",
        next_year_due=(12, 1),
        next_year_from="rules",
        sources=(SourceDef("CME-IR-RULES", "rules"), SourceDef("CME-IR-PROJECTED", "projected")),
    ),
    # London's bank holidays, for the sterling futures (mkt-data docs/phase-4.md, "Calendars"). gov.uk lists
    # about two years ahead, so next year is always due.
    "GB": CalendarDef(
        name="GB",
        description="England and Wales bank holidays (London): closed weekdays",
        timezone="Europe/London",
        sources=(SourceDef("GB-GOVUK"), SourceDef("GB-RULES", "rules"), SourceDef("GB-PROJECTED", "projected")),
    ),
    # The euro's settlement calendar: the ECB's fixed closing days, a rules file to 2100 (mkt-data
    # docs/phase-4.md, "Calendars"). Next year counts as there from the rules.
    "TARGET": CalendarDef(
        name="TARGET",
        description="TARGET/T2 closing days (euro settlement)",
        timezone="Europe/Berlin",
        next_year_from="rules",
        sources=(SourceDef("TARGET-RULES", "rules"),),
    ),
    # Tokyo's bank holidays (mkt-data docs/phase-4.md, "Calendars"): the Cabinet Office's CSV lists through the
    # end of next year, so next year is always due.
    "JP": CalendarDef(
        name="JP",
        description="Japan bank holidays (Tokyo): national holidays and December 31-January 3",
        timezone="Asia/Tokyo",
        sources=(SourceDef("JP-CAO"), SourceDef("JP-BANK", "rules"), SourceDef("JP-PROJECTED", "projected")),
    ),
    # Canada's payments holidays (mkt-data docs/phase-4.md, "Calendars"): a cited rules file to 2100 is the whole
    # calendar, so next year comes from the rules.
    "CA": CalendarDef(
        name="CA",
        description="Canada payments holidays (Payments Canada, Toronto)",
        timezone="America/Toronto",
        next_year_from="rules",
        sources=(SourceDef("CA-RULES", "rules"),),
    ),
    # Zurich's SIC banking holidays (mkt-data docs/phase-4.md, "Calendars"): SIX's published list (next year) and the
    # cited rules to 2100. SIX lists one year at a time, so the year after comes from the rules.
    "CH": CalendarDef(
        name="CH",
        description="Swiss franc payments holidays (SIC, Zurich)",
        timezone="Europe/Zurich",
        next_year_from="rules",
        sources=(SourceDef("SIX-SIC"), SourceDef("CH-RULES", "rules")),
    ),
    # Sydney's AUD settlement holidays (mkt-data docs/phase-4.md, "Calendars"): a cited rules file to 2100 is the whole
    # calendar, so next year comes from the rules.
    "AU": CalendarDef(
        name="AU",
        description="Australian dollar settlement holidays (Sydney)",
        timezone="Australia/Sydney",
        next_year_from="rules",
        sources=(SourceDef("AU-RULES", "rules"),),
    ),
    # New Zealand's NZD settlement holidays (mkt-data docs/phase-4.md, "Calendars"): a cited rules file to 2100 is the
    # whole calendar, so next year comes from the rules.
    "NZ": CalendarDef(
        name="NZ",
        description="New Zealand dollar settlement holidays (national; ESAS)",
        timezone="Pacific/Auckland",
        next_year_from="rules",
        sources=(SourceDef("NZ-RULES", "rules"),),
    ),
    # Stockholm, Oslo, Copenhagen and Mexico City (mkt-data docs/phase-4.md, "Calendars"): cited rules files to 2100 are the whole
    # calendars for now (Norges Bank's page joins NO once mkt-data parses it), so next year comes from the rules.
    "SE": CalendarDef(
        name="SE",
        description="Swedish krona settlement holidays (Stockholm banks)",
        timezone="Europe/Stockholm",
        next_year_from="rules",
        sources=(SourceDef("SE-RULES", "rules"),),
    ),
    "NO": CalendarDef(
        name="NO",
        description="Norwegian krone settlement holidays (NBO, Oslo)",
        timezone="Europe/Oslo",
        next_year_from="rules",
        sources=(SourceDef("NO-RULES", "rules"),),
    ),
    "DK": CalendarDef(
        name="DK",
        description="Danish krone settlement holidays (Copenhagen banks)",
        timezone="Europe/Copenhagen",
        next_year_from="rules",
        sources=(SourceDef("DK-RULES", "rules"),),
    ),
    "MX": CalendarDef(
        name="MX",
        description="Mexican peso settlement holidays (CNBV, Mexico City)",
        timezone="America/Mexico_City",
        next_year_from="rules",
        sources=(SourceDef("MX-RULES", "rules"),),
    ),
    "CME-FX": CalendarDef(
        name="CME-FX",
        description="CME Group FX futures: days with a trade date and settlement",
        timezone="America/Chicago",
        next_year_due=(12, 1),
        next_year_from="rules",
        sources=(SourceDef("CME-FX-RULES", "rules"), SourceDef("CME-FX-PROJECTED", "projected")),
    ),
}
