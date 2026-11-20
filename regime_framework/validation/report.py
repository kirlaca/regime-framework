"""
Egységes megjelenítés minden komponens/osztályozó `validate()` hívásának eredményéhez —
lásd PLAN.md 4. Package-struktúra (`validation/report.py`).
"""

import logging

logger = logging.getLogger(__name__)


def print_validation_report(report):
    logger.info("\n=== %s ===", report.component_name)

    if report.trade_count > 0 or report.win_rate or report.profit_factor == report.profit_factor:
        # stratégia-komponens jellegű riport (van trade-alapú adata)
        logger.info(report.summary_line())

    if report.notes:
        logger.info("  Megjegyzések:")
        for key, value in report.notes.items():
            logger.info("    %s: %s", key, value)

    if report.warnings:
        for warning in report.warnings:
            logger.warning("  ⚠️ %s", warning)
    else:
        logger.info("  ✅ Nincs figyelmeztetés.")
