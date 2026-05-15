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
from .mff              import MFF_EVALUATION,    MFFEvaluationRules
from .apex             import APEX_DRAWDOWN_ZERO, ApexDrawdownZeroRules
from .the5ers          import THE5ERS_HIGH_STAKES, The5ersHighStakesRules

# Generic alias used by the simulator + sweep so we don't have to bind to
# one concrete dataclass name.
Rules = Union[
    FundingPipsZeroRules, FTMOChallengeRules, MFFEvaluationRules,
    ApexDrawdownZeroRules, The5ersHighStakesRules,
]

# Lookup table for CLI use (--ruleset flag).
RULESETS: dict[str, Rules] = {
    "fundingpips_zero": FUNDINGPIPS_ZERO,
    "ftmo":             FTMO_CHALLENGE,
    "mff":              MFF_EVALUATION,
    "apex":             APEX_DRAWDOWN_ZERO,
    "the5ers":          THE5ERS_HIGH_STAKES,
}

__all__ = [
    "FUNDINGPIPS_ZERO",   "FundingPipsZeroRules",
    "FTMO_CHALLENGE",     "FTMOChallengeRules",
    "MFF_EVALUATION",     "MFFEvaluationRules",
    "APEX_DRAWDOWN_ZERO", "ApexDrawdownZeroRules",
    "THE5ERS_HIGH_STAKES","The5ersHighStakesRules",
    "Rules", "RULESETS",
]
