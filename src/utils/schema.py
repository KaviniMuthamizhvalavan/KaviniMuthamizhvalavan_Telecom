"""Domain schema: the single source of truth for columns, KPIs, symptoms, categories and vocabularies.

Used by preprocessing (offline labelling), runtime KPI assessment, the query parser, the API and
the KB runbook naming, so stored cases and new incidents share one set of definitions (plan §6.1).
"""
from dataclasses import dataclass

NARRATIVE_TEMPLATE_VERSION = "v1"

# Raw CSV column -> normalized snake_case name (27 columns, verified against the HF dataset).
COLUMN_MAP: dict[str, str] = {
    "Season": "season",
    "Cell Availability (%)": "cell_availability_pct",
    "MTTR (hours)": "mttr_hours",
    "Throughput (Mbps)": "throughput_mbps",
    "Latency (ms)": "latency_ms",
    "Packet Loss Rate (%)": "packet_loss_pct",
    "Call Drop Rate (%)": "call_drop_rate_pct",
    "Handover Success Rate (%)": "handover_success_pct",
    "Alarm Count": "alarm_count",
    "Critical Alarm Count": "critical_alarm_count",
    "Parameter Changes": "parameter_changes",
    "Successful Configuration Changes (%)": "config_change_success_pct",
    "Data Usage (GB)": "data_usage_gb",
    "User Count": "user_count",
    "Signal Strength (dBm)": "signal_strength_dbm",
    "Jitter (ms)": "jitter_ms",
    "Connection Setup Success Rate (%)": "cssr_pct",
    "Security Incidents": "security_incidents",
    "Authentication Failures": "auth_failures",
    "Temperature (°C)": "temperature_c",
    "Humidity (%)": "humidity_pct",
    "Weather": "weather",
    "Issue Reported": "issue_reported",
    "City": "city",
    "State": "state",
    "Zip": "zip_code",
    "Fault Occurrence Rate (%)": "fault_occurrence_rate_pct",
}
RAW_COLUMNS = list(COLUMN_MAP)


@dataclass(frozen=True)
class KPISpec:
    name: str
    label: str
    unit: str
    direction: int  # +1 higher is worse, -1 lower is worse, 0 context (no severity)
    symptom: str | None
    plausible_min: float
    plausible_max: float
    service_affecting: bool = False


# 19 severity KPIs (one symptom each) + 2 numeric context fields.
KPI_SPECS: dict[str, KPISpec] = {s.name: s for s in [
    KPISpec("latency_ms", "Latency", "ms", +1, "high_latency", 0, 2000),
    KPISpec("jitter_ms", "Jitter", "ms", +1, "high_jitter", 0, 1000),
    KPISpec("packet_loss_pct", "Packet loss rate", "%", +1, "high_packet_loss", 0, 100),
    KPISpec("throughput_mbps", "Throughput", "Mbps", -1, "low_throughput", 0, 10000, True),
    KPISpec("user_count", "User count", "users", +1, "high_user_load", 0, 100000),
    KPISpec("data_usage_gb", "Data usage", "GB", +1, "high_data_usage", 0, 10000),
    KPISpec("signal_strength_dbm", "Signal strength", "dBm", -1, "weak_signal", -150, -30),
    KPISpec("cssr_pct", "Connection setup success rate", "%", -1, "low_cssr", 0, 100, True),
    KPISpec("call_drop_rate_pct", "Call drop rate", "%", +1, "high_call_drop", 0, 100, True),
    KPISpec("handover_success_pct", "Handover success rate", "%", -1, "low_handover_success", 0, 100),
    KPISpec("cell_availability_pct", "Cell availability", "%", -1, "low_availability", 0, 100, True),
    KPISpec("mttr_hours", "Mean time to repair", "hours", +1, "long_mttr", 0, 1000),
    KPISpec("alarm_count", "Alarm count", "alarms", +1, "high_alarms", 0, 1000),
    KPISpec("critical_alarm_count", "Critical alarm count", "alarms", +1, "high_critical_alarms", 0, 1000),
    KPISpec("fault_occurrence_rate_pct", "Fault occurrence rate", "%", +1, "high_fault_rate", 0, 100),
    KPISpec("parameter_changes", "Parameter changes", "changes", +1, "high_param_changes", 0, 1000),
    KPISpec("config_change_success_pct", "Successful configuration changes", "%", -1, "low_config_success", 0, 100),
    KPISpec("security_incidents", "Security incidents", "incidents", +1, "high_security_incidents", 0, 1000),
    KPISpec("auth_failures", "Authentication failures", "failures", +1, "high_auth_failures", 0, 100000),
    KPISpec("temperature_c", "Temperature", "°C", 0, None, -60, 60),
    KPISpec("humidity_pct", "Humidity", "%", 0, None, 0, 100),
]}
SEVERITY_KPIS = [k for k, s in KPI_SPECS.items() if s.direction != 0]
NUMERIC_COLUMNS = list(KPI_SPECS)
CATEGORICAL_CONTEXT = ["season", "weather", "state", "city"]


@dataclass(frozen=True)
class Symptom:
    code: str
    kpi: str
    label: str
    synonyms: tuple[str, ...]


SYMPTOMS: dict[str, Symptom] = {s.code: s for s in [
    Symptom("high_latency", "latency_ms", "high latency", ("delay", "lag", "slow response", "high rtt")),
    Symptom("high_jitter", "jitter_ms", "high jitter", ("delay variation", "choppy voice", "choppy video")),
    Symptom("high_packet_loss", "packet_loss_pct", "packet loss", ("dropped packets", "plr")),
    Symptom("low_throughput", "throughput_mbps", "low throughput", ("reduced throughput", "slow speeds", "low bandwidth", "slow data")),
    Symptom("high_user_load", "user_count", "high user load", ("heavy load", "crowded cell", "peak traffic", "many users")),
    Symptom("high_data_usage", "data_usage_gb", "high data usage", ("traffic surge", "heavy data", "heavy traffic")),
    Symptom("weak_signal", "signal_strength_dbm", "weak signal", ("poor signal", "low rsrp", "bad coverage", "poor coverage")),
    Symptom("low_cssr", "cssr_pct", "connection setup failures", ("setup failures", "access failures", "cannot connect", "low cssr")),
    Symptom("high_call_drop", "call_drop_rate_pct", "dropped calls", ("call drops", "calls cut off", "call drop rate")),
    Symptom("low_handover_success", "handover_success_pct", "handover failures", ("handover failure", "drops while moving", "mobility issues", "handover success")),
    Symptom("low_availability", "cell_availability_pct", "low cell availability", ("cell down", "outage", "downtime", "unavailable")),
    Symptom("long_mttr", "mttr_hours", "long repair time", ("slow restoration", "long repair", "high mttr")),
    Symptom("high_alarms", "alarm_count", "high alarm count", ("alarm flood", "rising alarm counts", "increasing alarm counts", "many alarms")),
    Symptom("high_critical_alarms", "critical_alarm_count", "critical alarms", ("major alarms", "critical alarm count")),
    Symptom("high_fault_rate", "fault_occurrence_rate_pct", "high fault occurrence", ("frequent faults", "recurring failures", "fault occurrence")),
    Symptom("high_param_changes", "parameter_changes", "frequent parameter changes", ("frequent config changes", "recent changes", "parameter changes")),
    Symptom("low_config_success", "config_change_success_pct", "failed configuration changes", ("failed changes", "rollbacks", "config errors")),
    Symptom("high_security_incidents", "security_incidents", "security incidents", ("attacks", "intrusions", "security breach")),
    Symptom("high_auth_failures", "auth_failures", "authentication failures", ("login failures", "sim authentication failures", "auth failures")),
]}
assert {s.kpi for s in SYMPTOMS.values()} == set(SEVERITY_KPIS)


@dataclass(frozen=True)
class Category:
    code: str
    name: str
    description: str
    symptoms: tuple[str, ...]
    runbook: str


CATEGORIES: dict[str, Category] = {c.code: c for c in [
    Category("CONGESTION_CAPACITY", "Congestion and capacity", "Load exceeds capacity: many users or heavy traffic with low throughput and rising latency.",
             ("high_user_load", "high_data_usage", "low_throughput", "high_latency"), "01_congestion_capacity.md"),
    Category("TRANSPORT_QOS", "Transport and QoS", "Latency, jitter and packet-loss degradation on the transport path.",
             ("high_latency", "high_jitter", "high_packet_loss"), "02_transport_qos.md"),
    Category("RADIO_COVERAGE", "Radio coverage and signal quality", "Weak signal with connection setup failures or dropped calls.",
             ("weak_signal", "low_cssr", "high_call_drop"), "03_radio_coverage.md"),
    Category("MOBILITY_HANDOVER", "Mobility and handover", "Handover failures with dropped calls for moving users.",
             ("low_handover_success", "high_call_drop"), "04_mobility_handover.md"),
    Category("AVAILABILITY_OUTAGE", "Availability and outage", "Cell unavailability and slow restoration.",
             ("low_availability", "long_mttr"), "05_availability_outage.md"),
    Category("FAULT_ALARM", "Equipment faults and alarms", "Alarm storms, critical alarms and frequent faults.",
             ("high_alarms", "high_critical_alarms", "high_fault_rate"), "06_fault_alarm.md"),
    Category("CONFIG_CHANGE", "Configuration changes", "Frequent parameter changes and failed configuration changes.",
             ("high_param_changes", "low_config_success"), "07_config_change.md"),
    Category("SECURITY_AUTH", "Security and authentication", "Security incidents and authentication failures.",
             ("high_security_incidents", "high_auth_failures"), "08_security_auth.md"),
]}
NORMAL = "NORMAL"
NORMAL_RUNBOOK = "00_noc_triage_and_escalation.md"
CATEGORY_CODES = [*CATEGORIES, NORMAL]

SEASONS = ["Spring", "Summer", "Fall", "Winter"]
WEATHER = ["Clear", "Clouds", "Rain", "Snow"]
ADVERSE_WEATHER = {"Rain", "Snow"}
PRIORITIES = ["P1", "P2", "P3", "P4"]

# All 59 state/territory codes present in the dataset, with names for natural-language matching.
STATE_NAMES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "AS": "American Samoa", "FM": "Micronesia",
    "GU": "Guam", "MH": "Marshall Islands", "MP": "Northern Mariana Islands", "PW": "Palau",
    "PR": "Puerto Rico", "VI": "Virgin Islands",
}

DATASET_URL = "https://huggingface.co/datasets/fenar/5g_netops/resolve/main/5G_netops_data_100K.csv.xz"
DATASET_FILENAME = "5G_netops_data_100K.csv.xz"
SAMPLE_FILENAME = "netops_sample_10k.csv"
