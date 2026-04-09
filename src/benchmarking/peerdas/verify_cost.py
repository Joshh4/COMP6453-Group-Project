"""
Symbolic costs for KZG opening verification (Section 4.2, Equations (3)–(5)).

Pairing counts only; no curve arithmetic. Batched verification uses two pairings
for an entire batch of L cell openings (KDF22 / universal verification).
"""


def naive_pairing_count(num_openings: int, num_rows: int) -> int:
    """
    One multiproof per (row, column cell): 2 pairings per check (Equation (3)).

    num_openings is L (cells being checked); each cell needs one proof per row.
    """
    # Equation (3): each proof check is two pairings.
    # Total checks = num_openings * num_rows.
    return 2 * num_openings * num_rows


def batched_pairing_count() -> int:
    """One batched equation (5): two pairings total."""
    # Equation (5) compresses all checks into one pairing identity.
    return 2
