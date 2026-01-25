"""Wallet journal analysis for detecting RMT and suspicious transfers."""

from datetime import timedelta

from backend.models.applicant import Applicant, WalletEntry
from backend.models.flags import (
    FlagCategory,
    FlagSeverity,
    RedFlags,
    RiskFlag,
    YellowFlags,
)

from .base import BaseAnalyzer


class WalletAnalyzer(BaseAnalyzer):
    """
    Analyzes wallet journal data to identify:
    - RMT patterns (regular same-amount transactions)
    - Large pre-join transfers (suspicious ISK before corp application)
    - Unusual transaction sources
    """

    name = "wallet"
    description = "Analyzes wallet journal for RMT and suspicious transfers"
    requires_auth = True  # Needs auth bridge data

    # Thresholds
    RMT_SAME_AMOUNT_COUNT = 5  # Same exact amount 5+ times = suspicious
    RMT_MIN_AMOUNT = 100_000_000  # 100M ISK minimum to consider
    RMT_REGULAR_INTERVAL_MIN_HOURS = 100  # ~4 days minimum
    RMT_REGULAR_INTERVAL_MAX_HOURS = 200  # ~8 days maximum
    RMT_INTERVAL_VARIANCE_THRESHOLD = 1000  # Low variance indicates regularity
    LARGE_TRANSFER_ISK = 1_000_000_000  # 1B ISK
    PRE_JOIN_WINDOW_DAYS = 30  # Look 30 days before current corp join

    # Transaction types that indicate player-to-player transfers
    PLAYER_TRANSFER_TYPES = {
        "player_donation",
        "player_trading",
        "contract_price",
        "contract_reward",
    }

    async def analyze(self, applicant: Applicant) -> list[RiskFlag]:
        """Analyze wallet journal for suspicious patterns."""
        flags: list[RiskFlag] = []
        journal = applicant.wallet_journal

        if not journal:
            return flags

        # 1. RMT pattern detection
        flags.extend(self._detect_rmt_patterns(journal))

        # 2. Large pre-join transfers
        flags.extend(self._detect_pre_join_transfers(journal, applicant))

        # 3. Suspicious sources (future: check against known RMT entity list)
        flags.extend(self._detect_suspicious_sources(journal))

        return flags

    def _detect_rmt_patterns(self, journal: list[WalletEntry]) -> list[RiskFlag]:
        """Detect patterns consistent with RMT.

        RMT sellers typically send regular amounts at regular intervals.
        We look for:
        - Same exact amount appearing 5+ times
        - Regular intervals (~weekly)
        - Amount above 100M ISK (small amounts are normal gameplay)
        """
        flags: list[RiskFlag] = []

        # Group incoming player transactions by exact amount
        amount_groups: dict[float, list[WalletEntry]] = {}
        for entry in journal:
            if entry.ref_type in self.PLAYER_TRANSFER_TYPES and entry.amount > 0:
                # Only consider amounts above threshold
                if entry.amount >= self.RMT_MIN_AMOUNT:
                    amount_groups.setdefault(entry.amount, []).append(entry)

        # Flag amounts that appear too regularly
        for amount, entries in amount_groups.items():
            if len(entries) >= self.RMT_SAME_AMOUNT_COUNT:
                # Check if they're also at regular intervals
                if self._has_regular_interval(entries):
                    sorted_entries = sorted(entries, key=lambda x: x.date)
                    flags.append(
                        RiskFlag(
                            severity=FlagSeverity.RED,
                            category=FlagCategory.WALLET,
                            code=RedFlags.RMT_PATTERN,
                            reason=(
                                f"Suspicious pattern: {len(entries)} transactions "
                                f"of {amount:,.0f} ISK at regular intervals"
                            ),
                            evidence={
                                "amount": amount,
                                "count": len(entries),
                                "dates": [e.date.isoformat() for e in sorted_entries[:5]],
                            },
                            confidence=0.85,
                        )
                    )

        return flags

    def _has_regular_interval(self, entries: list[WalletEntry]) -> bool:
        """Check if entries occur at suspiciously regular intervals.

        RMT typically happens weekly or bi-weekly. We check for:
        - Consistent time between transactions
        - Intervals in the 4-8 day range (weekly-ish)
        """
        if len(entries) < 3:
            return False

        sorted_entries = sorted(entries, key=lambda e: e.date)
        intervals: list[float] = []
        for i in range(1, len(sorted_entries)):
            delta = (sorted_entries[i].date - sorted_entries[i - 1].date).total_seconds() / 3600
            intervals.append(delta)

        if not intervals:
            return False

        # Check for consistent ~weekly intervals
        avg_interval = sum(intervals) / len(intervals)
        variance = sum((i - avg_interval) ** 2 for i in intervals) / len(intervals)

        # Low variance + near-weekly = suspicious
        is_low_variance = variance < self.RMT_INTERVAL_VARIANCE_THRESHOLD
        is_weekly_interval = (
            self.RMT_REGULAR_INTERVAL_MIN_HOURS < avg_interval < self.RMT_REGULAR_INTERVAL_MAX_HOURS
        )
        return is_low_variance and is_weekly_interval

    def _detect_pre_join_transfers(
        self,
        journal: list[WalletEntry],
        applicant: Applicant,
    ) -> list[RiskFlag]:
        """Detect large ISK transfers just before joining current corp.

        Suspicious pattern: receiving large amounts of ISK shortly before
        applying to a corp could indicate being paid to infiltrate.
        """
        flags: list[RiskFlag] = []

        # Get current corp join date
        if not applicant.corp_history:
            return flags

        # First entry in corp_history is current corp
        join_date = applicant.corp_history[0].start_date
        window_start = join_date - timedelta(days=self.PRE_JOIN_WINDOW_DAYS)

        # Find incoming player transfers in window (sum all, then check threshold)
        pre_join_transfers = [
            e
            for e in journal
            if window_start <= e.date <= join_date
            and e.amount > 0
            and e.ref_type in self.PLAYER_TRANSFER_TYPES
        ]

        total_received = sum(e.amount for e in pre_join_transfers)

        if total_received >= self.LARGE_TRANSFER_ISK:
            flags.append(
                RiskFlag(
                    severity=FlagSeverity.YELLOW,
                    category=FlagCategory.WALLET,
                    code=YellowFlags.LARGE_PRE_JOIN_TRANSFER,
                    reason=f"Received {total_received / 1e9:.1f}B ISK in 30 days before joining",
                    evidence={
                        "total_isk": total_received,
                        "transfer_count": len(pre_join_transfers),
                        "join_date": join_date.isoformat(),
                    },
                    confidence=0.7,
                )
            )

        return flags

    def _detect_suspicious_sources(self, journal: list[WalletEntry]) -> list[RiskFlag]:
        """Detect payments from known suspicious sources.

        Future enhancement: check against a database of known RMT entities.
        For now, this is a placeholder for that functionality.
        """
        # Placeholder for future known RMT entity detection
        # Would check first_party_id against a list of known RMT sellers
        return []
