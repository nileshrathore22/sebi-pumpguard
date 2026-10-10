"""Project-wide constants."""

DISCLAIMER = (
    "PumpGuard outputs statistical anomaly risk scores for research and education only. "
    "A high score is not an accusation of wrongdoing and is not investment advice "
    "or a buy/sell signal."
)

SYNTHETIC_PREFIX = "SYNTH_"

# Words the explanation layer must never use: the system flags anomalies, it does not judge intent.
BANNED_TERMS = ("manipulation", "manipulated", "fraud", "fraudulent", "guaranteed", "guarantee")

MIN_VERIFIED_CASES = 15
