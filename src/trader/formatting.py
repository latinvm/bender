"""Common formatting utilities for consistent display across the application"""

from typing import List, Tuple


def format_currency(value: float, sign: str = "", min_width: int = 0) -> str:
    """Format a currency value with sign and proper spacing

    Args:
        value: The monetary value (can be negative)
        sign: Optional sign to prepend ('+' or '-')
        min_width: Minimum width for the formatted value (excluding sign and €)

    Returns:
        Formatted string like '+€10.50' or '-€1234.56'
    """
    abs_value = abs(value)
    formatted = f"{abs_value:.2f}"

    if min_width > 0:
        formatted = formatted.rjust(min_width)

    return f"{sign}€{formatted}"


def format_percentage(value: float, sign: str = "", min_width: int = 0) -> str:
    """Format a percentage value with sign and proper spacing

    Args:
        value: The percentage value (can be negative)
        sign: Optional sign to prepend ('+' or '-')
        min_width: Minimum width for the formatted value (excluding sign and %)

    Returns:
        Formatted string like '+10.50%' or '-1234.56%'
    """
    abs_value = abs(value)
    formatted = f"{abs_value:.2f}"

    if min_width > 0:
        formatted = formatted.rjust(min_width)

    return f"{sign}{formatted}%"


def calculate_max_width(values: List[float]) -> int:
    """Calculate the maximum width needed to display a list of values

    Args:
        values: List of numeric values

    Returns:
        Maximum width needed (including decimal places but excluding sign)
    """
    if not values:
        return 0

    max_width = 0
    for val in values:
        formatted = f"{abs(val):.2f}"
        max_width = max(max_width, len(formatted))

    return max_width


def format_pl_values(pl_values: List[float]) -> Tuple[List[str], List[str]]:
    """Format a list of P/L values (percentage and EUR) with consistent widths

    Args:
        pl_values: List of tuples (pl_pct, pl_eur)

    Returns:
        Tuple of (formatted_percentages, formatted_euros)
    """
    if not pl_values:
        return [], []

    pl_pcts = [pct for pct, _ in pl_values]
    pl_eurs = [eur for _, eur in pl_values]

    pct_width = calculate_max_width(pl_pcts)
    eur_width = calculate_max_width(pl_eurs)

    formatted_pcts = []
    formatted_eurs = []

    for pl_pct, pl_eur in pl_values:
        pct_sign = "+" if pl_pct >= 0 else "-"
        eur_sign = "+" if pl_eur >= 0 else "-"

        formatted_pcts.append(format_percentage(pl_pct, pct_sign, pct_width))
        formatted_eurs.append(format_currency(pl_eur, eur_sign, eur_width))

    return formatted_pcts, formatted_eurs
