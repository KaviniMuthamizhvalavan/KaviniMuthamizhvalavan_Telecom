"""Rule-based query understanding: symptoms, categories, filters and severity hint from text.

Used for /search query expansion, as the classifier's fallback in reduced mode, and as a
relevance signal for guardrails (plan §6.2). Deterministic and dependency-free.
"""
import re
from dataclasses import dataclass, field

from src.utils.schema import STATE_NAMES, SYMPTOMS

# Extra trigger phrases beyond each symptom's label and synonyms (bare KPI nouns imply a problem in a query).
EXTRA_TRIGGERS = {
    "high_latency": ["latency", "delay", "lag", "laggy", "slow response"],
    "high_jitter": ["jitter"],
    "high_packet_loss": ["packet loss", "packet-loss", "losing packets"],
    "low_throughput": ["throughput", "slow speed", "slow internet", "low speed"],
    "high_user_load": ["congestion", "congested", "overloaded", "too many users", "user count", "busy cell"],
    "high_data_usage": ["data usage", "heavy data traffic", "traffic spike"],
    "weak_signal": ["signal strength", "weak rsrp", "rsrp", "signal quality", "poor signal", "weak signal"],
    "low_cssr": ["connection setup", "setup success", "cssr", "call setup", "cannot connect", "can't connect", "fail to connect"],
    "high_call_drop": ["call drop", "dropped call", "calls drop", "calls dropping", "drop calls"],
    "low_handover_success": ["handover", "hand-over", "handoff"],
    "low_availability": ["availability", "outage", "cell down", "going down", "unavailable", "downtime"],
    "long_mttr": ["mttr", "repair time", "slow repair", "repairs take", "restoration time"],
    "high_alarms": ["alarm count", "alarms", "alarm storm", "alarm flood"],
    "high_critical_alarms": ["critical alarm", "major alarm"],
    "high_fault_rate": ["fault occurrence", "faults", "fault rate", "frequent failures"],
    "high_param_changes": ["parameter change", "config changes", "configuration changes"],
    "low_config_success": ["failed configuration", "configuration change failed", "changes failed", "rolled back", "rollback"],
    "high_security_incidents": ["security incident", "security", "attack", "intrusion"],
    "high_auth_failures": ["authentication", "auth failure", "login failure"],
}
CATEGORY_TRIGGERS = {
    "TRANSPORT_QOS": ["transport", "backhaul", "qos"],
    "CONGESTION_CAPACITY": ["congestion", "capacity", "overloaded"],
    "RADIO_COVERAGE": ["coverage", "radio"],
    "MOBILITY_HANDOVER": ["mobility", "handover"],
    "AVAILABILITY_OUTAGE": ["outage", "availability"],
    "FAULT_ALARM": ["alarm", "fault", "hardware"],
    "CONFIG_CHANGE": ["configuration", "parameter change", "config"],
    "SECURITY_AUTH": ["security", "authentication", "attack"],
}
SEASON_WORDS = {"winter": "Winter", "summer": "Summer", "spring": "Spring", "fall": "Fall", "autumn": "Fall"}
WEATHER_WORDS = {"snow": "Snow", "snowy": "Snow", "snowstorm": "Snow", "snowfall": "Snow", "rain": "Rain",
                 "rainy": "Rain", "raining": "Rain", "rainfall": "Rain", "cloudy": "Clouds", "clouds": "Clouds",
                 "overcast": "Clouds", "clear weather": "Clear", "clear sky": "Clear", "clear skies": "Clear"}
SEVERITY_WORDS = {"critical": "critical", "severe": "critical", "outage": "critical", "major": "high",
                  "urgent": "high", "minor": "low", "slight": "low"}
# Two-letter codes that are also common English words are only matched via full state names.
AMBIGUOUS_CODES = {"IN", "OR", "ME", "OK", "HI", "AS", "ID", "AL", "DE", "PA", "MA", "CO", "LA", "MO", "OH", "GU"}


@dataclass
class RuleParse:
    symptoms: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    filters: dict = field(default_factory=dict)
    severity_hint: str = "unknown"
    expansion_terms: list[str] = field(default_factory=list)


def _has(text: str, phrase: str) -> bool:
    return re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", text) is not None


def parse(text: str) -> RuleParse:
    low = text.lower()
    out = RuleParse()
    for code, sym in SYMPTOMS.items():
        phrases = [sym.label, *sym.synonyms, *EXTRA_TRIGGERS.get(code, [])]
        if any(_has(low, p) for p in phrases):
            out.symptoms.append(code)
    out.categories = [c for c, words in CATEGORY_TRIGGERS.items() if any(_has(low, w) for w in words)]

    states = {code for name, code in ((n.lower(), c) for c, n in STATE_NAMES.items()) if _has(low, name)}
    states |= {m for m in re.findall(r"\b([A-Z]{2})\b", text) if m in STATE_NAMES and m not in AMBIGUOUS_CODES}
    if "washington dc" in low or "washington, dc" in low:
        states.discard("WA")
        states.add("DC")
    seasons = {v for k, v in SEASON_WORDS.items() if _has(low, k)}
    weather = {v for k, v in WEATHER_WORDS.items() if _has(low, k)}
    if states:
        out.filters["state"] = sorted(states)
    if seasons:
        out.filters["season"] = sorted(seasons)
    if weather:
        out.filters["weather"] = sorted(weather)

    for word, level in SEVERITY_WORDS.items():
        if _has(low, word):
            out.severity_hint = level
            break
    out.expansion_terms = [SYMPTOMS[c].label for c in out.symptoms if SYMPTOMS[c].label not in low]
    return out
