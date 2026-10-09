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
    # Stockholm, Oslo, Copenhagen and Mexico City (mkt-data docs/phase-4.md, "Calendars"): cited rules files to 2100,
    # with Norges Bank's settlement days page beside NO's. That page lists a year at a time, so next year comes from the
    # rules.
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
        sources=(SourceDef("NO-NBO"), SourceDef("NO-RULES", "rules")),
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
    # The emerging-market FX futures' calendars (mkt-data docs/phase-4.md, step 2d): cited rules files, with ANBIMA's
    # spreadsheet beside BR's (kept raw until its parser is written). Next year comes from the rules.
    "BR": CalendarDef(
        name="BR",
        description="Brazilian real settlement holidays (national holidays; ANBIMA)",
        timezone="America/Sao_Paulo",
        next_year_from="rules",
        sources=(SourceDef("BR-ANBIMA"), SourceDef("BR-RULES", "rules")),
    ),
    "ZA": CalendarDef(
        name="ZA",
        description="South African rand settlement holidays (SAMOS, Johannesburg)",
        timezone="Africa/Johannesburg",
        next_year_from="rules",
        sources=(SourceDef("ZA-RULES", "rules"),),
    ),
    "PL": CalendarDef(
        name="PL",
        description="Polish zloty settlement holidays (SORBNET, Warsaw)",
        timezone="Europe/Warsaw",
        next_year_from="rules",
        sources=(SourceDef("PL-RULES", "rules"),),
    ),
    "CZ": CalendarDef(
        name="CZ",
        description="Czech koruna settlement holidays (CERTIS, Prague)",
        timezone="Europe/Prague",
        next_year_from="rules",
        sources=(SourceDef("CZ-RULES", "rules"),),
    ),
    "HU": CalendarDef(
        name="HU",
        description="Hungarian forint settlement holidays (VIBER, Budapest)",
        timezone="Europe/Budapest",
        next_year_from="rules",
        sources=(SourceDef("HU-RULES", "rules"),),
    ),
    # Lunar and announced holidays: each rules file covers only the years published and is extended a year at a
    # time, so next year is due from when its publisher usually lists it.
    "CL": CalendarDef(
        name="CL",
        description="Chilean peso settlement holidays (LBTR, Santiago)",
        timezone="America/Santiago",
        next_year_due=(12, 1),
        next_year_from="rules",
        sources=(SourceDef("CL-RULES", "rules"),),
    ),
    "IL": CalendarDef(
        name="IL",
        description="Israeli shekel settlement holidays (Zahav, Tel Aviv)",
        timezone="Asia/Jerusalem",
        next_year_due=(9, 1),
        next_year_from="rules",
        sources=(SourceDef("IL-RULES", "rules"),),
    ),
    "TR": CalendarDef(
        name="TR",
        description="Turkish lira settlement holidays (EFT, Istanbul)",
        timezone="Europe/Istanbul",
        next_year_due=(12, 1),
        next_year_from="rules",
        sources=(SourceDef("TR-RULES", "rules"),),
    ),
    "HK": CalendarDef(
        name="HK",
        description="Hong Kong dollar settlement holidays (CHATS, Hong Kong)",
        timezone="Asia/Hong_Kong",
        next_year_due=(7, 1),
        next_year_from="rules",
        sources=(SourceDef("HK-RULES", "rules"),),
    ),
    "CN": CalendarDef(
        name="CN",
        description="Onshore renminbi settlement holidays (CNAPS, Beijing)",
        timezone="Asia/Shanghai",
        next_year_due=(12, 1),
        next_year_from="rules",
        sources=(SourceDef("CN-RULES", "rules"),),
    ),
    "SG": CalendarDef(
        name="SG",
        description="Singapore dollar settlement holidays (MEPS+, Singapore)",
        timezone="Asia/Singapore",
        next_year_due=(7, 1),
        next_year_from="rules",
        sources=(SourceDef("SG-RULES", "rules"),),
    ),
    "TH": CalendarDef(
        name="TH",
        description="Thai baht settlement holidays (BAHTNET, Bangkok)",
        timezone="Asia/Bangkok",
        next_year_due=(10, 1),
        next_year_from="rules",
        sources=(SourceDef("TH-RULES", "rules"),),
    ),
    "ID": CalendarDef(
        name="ID",
        description="Indonesian rupiah settlement holidays (BI-RTGS, Jakarta)",
        timezone="Asia/Jakarta",
        next_year_due=(10, 1),
        next_year_from="rules",
        sources=(SourceDef("ID-RULES", "rules"),),
    ),
    "IN": CalendarDef(
        name="IN",
        description="Indian rupee settlement holidays (RTGS and CCIL, Mumbai)",
        timezone="Asia/Kolkata",
        next_year_due=(12, 1),
        next_year_from="rules",
        sources=(SourceDef("IN-RULES", "rules"),),
    ),
    "KR": CalendarDef(
        name="KR",
        description="Korean won settlement holidays (BOK-Wire+, Seoul)",
        timezone="Asia/Seoul",
        next_year_due=(7, 1),
        next_year_from="rules",
        sources=(SourceDef("KR-RULES", "rules"),),
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
