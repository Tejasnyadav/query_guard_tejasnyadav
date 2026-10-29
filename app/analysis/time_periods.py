import re

from datetime import date


 

from app.agents.models import ResolvedTimeContext, TermResolution, TimeWindow


 

_MONTHS = {

    "january": 1,

    "february": 2,

    "march": 3,

    "april": 4,

    "may": 5,

    "june": 6,

    "july": 7,

    "august": 8,

    "september": 9,

    "october": 10,

    "november": 11,

    "december": 12,

}

_MONTH_PATTERN = re.compile(

    r"\b(" + "|".join(_MONTHS) + r")\s+(20\d{2})\b",

    flags=re.IGNORECASE,

)

_COMPARISON_WORDS = {

    "why",

    "decrease",

    "decreased",

    "decline",

    "declined",

    "change",

    "changed",

    "increase",

    "increased",

    "compare",

    "compared",

    "versus",

    "vs",

    "contributed",

    "previous month",

}



 

def _month_start(value: date) -> date:

    return value.replace(day=1)



 

def _add_months(value: date, months: int) -> date:

    zero_based = value.year * 12 + value.month - 1 + months

    year, month_index = divmod(zero_based, 12)

    return date(year, month_index + 1, 1)



 

def _window(role: str, start: date, as_of_date: date) -> TimeWindow:

    end = _add_months(start, 1)

    current_month_start = _month_start(as_of_date)

    return TimeWindow(

        role=role,  # type: ignore[arg-type]

        label=start.strftime("%B %Y"),

        start=start,

        end_exclusive=end,

        is_complete=end <= current_month_start,

    )



 

def resolve_time_context(

    *,

    question: str,

    resolution: TermResolution,

    as_of_date: date,

) -> ResolvedTimeContext:

    normalized = question.casefold()

    explicit: list[date] = []

    for match in _MONTH_PATTERN.finditer(question):

        month_name, year_text = match.groups()

        month_start = date(int(year_text), _MONTHS[month_name.casefold()], 1)

        if month_start not in explicit:

            explicit.append(month_start)


 

    warnings: list[str] = []

    windows: list[TimeWindow] = []


 

    if explicit:

        windows.append(_window("primary", explicit[0], as_of_date))

        if len(explicit) > 1:

            windows.append(_window("comparison", explicit[1], as_of_date))

        basis = "Explicit calendar month(s) found in the question."

    elif "last month" in normalized or resolution.time_intent.startswith("last_complete_month"):

        primary = _add_months(_month_start(as_of_date), -1)

        windows.append(_window("primary", primary, as_of_date))

        needs_comparison = (

            resolution.time_intent == "last_complete_month_vs_previous"

            or any(word in normalized for word in _COMPARISON_WORDS)

        )

        if needs_comparison:

            windows.append(_window("comparison", _add_months(primary, -1), as_of_date))

        basis = (

            "Relative dates were resolved against the dataset as-of date, not the computer date."

        )

    else:

        basis = (

            "No date restriction was inferred; use all available data unless "

            "the plan narrows it."

        )


 

    for item in windows:

        if not item.is_complete:

            warnings.append(f"{item.label} is not a complete month in this dataset.")


 

    return ResolvedTimeContext(basis=basis, windows=windows, warnings=warnings)


 