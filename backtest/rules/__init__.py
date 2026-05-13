"""Prop-firm rule sets. Each rule set is a dataclass that the simulator
consults at every account-state transition (trade open, trade close,
end-of-day, end-of-week)."""
from .fundingpips_zero import FUNDINGPIPS_ZERO, FundingPipsZeroRules

__all__ = ["FUNDINGPIPS_ZERO", "FundingPipsZeroRules"]
