"""Prop-firm rule sets. Each rule set is a dataclass that the simulator
consults at every account-state transition (trade open, trade close,
end-of-day, end-of-week).

A `Rules` object is interchangeable across rule sets — every field used
by the account / sizer / runner is shared (same names, same units). Adding
a new firm = one new dataclass file + an entry here.
"""
from typing import Union

from .fundingpips_zero import FUNDINGPIPS_ZERO, FundingPipsZeroRules
from .ftmo_challenge   import FTMO_CHALLENGE,    FTMOChallengeRules

# Generic alias used by the simulator + sweep so we don't have to bind to
# one concrete dataclass name.
Rules = Union[FundingPipsZeroRules, FTMOChallengeRules]

# Lookup table for CLI use (--ruleset flag).
RULESETS: dict[str, Rules] = {
    "fundingpips_zero": FUNDINGPIPS_ZERO,
    "ftmo":             FTMO_CHALLENGE,
}

__all__ = [
    "FUNDINGPIPS_ZERO", "FundingPipsZeroRules",
    "FTMO_CHALLENGE",   "FTMOChallengeRules",
    "Rules", "RULESETS",
]
