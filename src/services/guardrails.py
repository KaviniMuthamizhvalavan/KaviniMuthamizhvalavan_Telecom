"""Input guardrails, applied before any retrieval or LLM call (plan §6.4b).

Order: normalization -> gibberish -> prompt injection -> PII redaction -> domain relevance.
Schema/range checks (step 1) are Pydantic in the API layer; filter validation (step 7) is rag.filters.validate.
Relevance = max cosine similarity to telecom anchor sentences; a query in which the rule parser recognizes a
network symptom is always in scope. The "uncertain" band is decided by the classifier when an LLM is
available, and allowed with a warning otherwise.
"""
import logging
import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np

from src.services import query_parser

log = logging.getLogger(__name__)

# Thresholds tuned on tests/test_cases/guardrail_cases.json + golden_queries.json (see run_guardrail_eval.py).
# The plan's starting values (0.55 / 0.35) assumed a wider score spread; bge-small compresses similarities:
# off-topic inputs measured 0.38-0.54, in-domain inputs without a recognized symptom 0.69-0.81.
IN_SCOPE_MIN = 0.65
OUT_OF_SCOPE_MAX = 0.55
# A word that the WordPiece tokenizer splits into 3+ pieces is unlikely to be a real word; real queries
# measured <= 0.14 such words (jargon like "eNodeB RSRP SINR": 0.33), keyboard mashing 1.0.
FRAGMENTED_WORD_SHARE = 0.5

EXAMPLE_QUERIES = [
    "High latency and packet loss with reduced throughput in Texas during winter",
    "Calls drop when users move between cells and handover success is low",
    "Alarm storm with many critical alarms and frequent faults",
]

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)?\s*(instructions|prompts?|rules)",
    r"disregard\s+(all\s+|the\s+|your\s+)?(previous|prior|above)?\s*(instructions|rules|prompts?)",
    r"system\s+prompt", r"\byou\s+are\s+now\b", r"developer\s+mode", r"\bjailbreak", r"reveal\s+your",
    r"\bact\s+as\s+(an?\s+)?(unrestricted|unfiltered|evil|dan)\b", r"\bDAN\b", r"pretend\s+(that\s+)?you\s+have\s+no",
    r"<\|?(im_start|im_end|system|endoftext)\|?>", r"\[/?(INST|SYS)\]", r"^\s*(system|assistant)\s*:",
    r"print\s+(your|the)\s+(instructions|prompt|api\s*key)", r"(api|secret)\s*key",
]
INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.I | re.M)

PII_RULES = [
    ("[EMAIL]", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("[PHONE]", re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}(?!\d)")),
    ("[NUMBER]", re.compile(r"(?<!\d)\d{9,}(?!\d)")),
]

ANCHORS = [
    "High latency and jitter on the transport network",
    "Packet loss on the backhaul link degrades quality of service",
    "Throughput dropped and users experience slow data speeds",
    "Cell congestion with too many users and heavy data traffic",
    "Capacity problem at a busy cell during peak hours",
    "Weak signal strength and poor RSRP coverage",
    "Call setup success rate is low and users cannot connect",
    "Dropped calls are increasing at several cells",
    "Handover failures when users move between cells",
    "Mobility problems with low handover success rate",
    "Cell availability is low and the site keeps going down",
    "Network outage with long mean time to repair",
    "Alarm storm with many critical alarms on the base station",
    "Fault occurrence rate is increasing on network equipment",
    "Hardware fault on a radio unit raises alarms",
    "Parameter changes on cells caused degradation",
    "Configuration change failed and was rolled back",
    "Security incidents and authentication failures on the network",
    "SIM authentication failures are increasing",
    "Possible attack on the mobile core network",
    "5G network performance degradation in a region",
    "LTE and 5G cell site KPI anomaly",
    "Mobile network operations center incident triage",
    "Troubleshoot a telecom network problem and find the root cause",
    "Recommend corrective actions for a cellular network issue",
    "Prioritize network incidents by severity and impact",
    "Similar past incidents with the same KPI symptoms",
    "Network KPIs degraded during snow and rain",
    "Service quality issues for voice and video calls",
    "Video streaming buffering due to network delay",
    "Mobile data speed is slow for customers",
    "Base station or eNodeB / gNodeB failure",
    "Radio access network interference and coverage holes",
    "Network fault risk prediction for a cell",
    "Expected throughput for the current network conditions",
    "Users in a city report poor mobile service",
    "Escalate a critical network incident to the NOC",
    "Telecom operator network monitoring and alarms",
    "Wireless network issue with signal and connectivity",
    "Core network or transport link failure",
]


class GuardrailError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


@dataclass
class GuardrailResult:
    text: str  # normalized and PII-redacted; the only form passed downstream
    relevance: float
    band: str  # in_scope | uncertain | out_of_scope (out_of_scope never returns; it raises)
    rule_symptoms: list[str] = field(default_factory=list)
    redactions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = "".join(ch if (ch in "\n\t" or unicodedata.category(ch)[0] != "C") else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def is_gibberish(text: str, tokenizer=None) -> bool:
    """Fewer than 2 alphabetic words, alphabetic ratio < 0.5, or mostly non-words (WordPiece fragmentation)."""
    words = re.findall(r"[A-Za-z]{2,}", text)
    letters = sum(ch.isalpha() for ch in text)
    non_space = sum(not ch.isspace() for ch in text) or 1
    if len(words) < 2 or letters / non_space < 0.5:
        return True
    if tokenizer is not None:
        fragmented = sum(len(tokenizer.tokenize(w.lower())) >= 3 for w in words)
        return fragmented / len(words) > FRAGMENTED_WORD_SHARE
    return False


def redact_pii(text: str) -> tuple[str, list[str]]:
    found = []
    for token, rx in PII_RULES:
        text, n = rx.subn(token, text)
        if n:
            found.append(token)
    return text, found


class Guardrails:
    def __init__(self, embedder):
        self.embedder = embedder
        self._anchors = embedder.embed_documents(ANCHORS) if embedder is not None else None
        self._tokenizer = getattr(getattr(embedder, "model", None), "tokenizer", None)

    def relevance(self, text: str) -> float:
        if self._anchors is None:
            return 1.0
        q = self.embedder.embed_documents([text])[0]
        return float(np.max(self._anchors @ q))

    def check(self, query: str) -> GuardrailResult:
        text = normalize(query)
        if is_gibberish(text, self._tokenizer):
            raise GuardrailError("GIBBERISH", "The query does not look like a sentence. Describe the network problem "
                                              "in a few words.", {"examples": EXAMPLE_QUERIES})
        m = INJECTION_RE.search(text)
        if m:
            log.warning("guardrail: prompt injection blocked (%r)", m.group(0)[:60])
            raise GuardrailError("PROMPT_INJECTION", "The query contains instructions aimed at the assistant and was "
                                                     "blocked. Describe the network problem instead.",
                                 {"matched": m.group(0)[:60]})
        text, redactions = redact_pii(text)
        warnings = [f"Personal data was removed from the query ({', '.join(redactions)})."] if redactions else []
        symptoms = query_parser.parse(text).symptoms
        score = self.relevance(text)
        if symptoms or score >= IN_SCOPE_MIN:
            band = "in_scope"
        elif score < OUT_OF_SCOPE_MAX:
            raise GuardrailError("OUT_OF_SCOPE", "This assistant answers questions about mobile network operations "
                                                 "(KPIs, incidents, troubleshooting). Try one of the examples.",
                                 {"relevance": round(score, 3), "examples": EXAMPLE_QUERIES})
        else:
            band = "uncertain"
        return GuardrailResult(text=text, relevance=round(score, 3), band=band, rule_symptoms=symptoms,
                               redactions=redactions, warnings=warnings)
