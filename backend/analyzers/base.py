"""Base analyzer interface."""

from abc import ABC, abstractmethod

from backend.models.applicant import Applicant
from backend.models.flags import RiskFlag


class BaseAnalyzer(ABC):
    """Base class for all analyzers."""

    name: str = "base"
    description: str = "Base analyzer"
    requires_auth: bool = False  # Does this analyzer need auth data?

    @abstractmethod
    async def analyze(self, applicant: Applicant) -> list[RiskFlag]:
        """
        Analyze an applicant and return risk flags.

        Args:
            applicant: The applicant to analyze

        Returns:
            List of risk flags identified
        """
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.name}>"
