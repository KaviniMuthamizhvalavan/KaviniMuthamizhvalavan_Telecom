# Troubleshooting knowledge base (runbooks)

The 5G NetOps dataset contains KPI values only: no incident text, root causes or corrective actions. These nine runbooks are the project's **second data source**. They give the recommender and analyst agents grounded, citable troubleshooting knowledge (plan C1, A6).

## Authorship and status
- **Authored for this project (2026-10-07).** Drafted with LLM assistance from general, vendor-neutral NOC practice and the public standards below, then reviewed by the project author.
- These are **reference runbooks for a capstone**, not an operator's validated procedures. Actions that can disrupt service are marked **(requires change approval)**.
- The KPI signatures use this dataset's **relative** bands: "degraded" means worse than the 75th percentile of the network's history, and "critical" worse than the 90th (plan C7). They are not absolute 3GPP targets.

## Files
| File | Incident type |
|---|---|
| `00_noc_triage_and_escalation.md` | General triage, prioritization and escalation (also used for NORMAL) |
| `01_congestion_capacity.md` | CONGESTION_CAPACITY |
| `02_transport_qos.md` | TRANSPORT_QOS |
| `03_radio_coverage.md` | RADIO_COVERAGE |
| `04_mobility_handover.md` | MOBILITY_HANDOVER |
| `05_availability_outage.md` | AVAILABILITY_OUTAGE |
| `06_fault_alarm.md` | FAULT_ALARM |
| `07_config_change.md` | CONFIG_CHANGE |
| `08_security_auth.md` | SECURITY_AUTH |

## Structure
Each runbook has YAML front-matter (`category`, `title`, `version`, `references`) and the same H2 sections:
- Overview
- KPI signature
- Likely root causes
- Diagnostic checks
- Corrective actions
- Verification
- Escalation criteria
- Interactions with other categories
- Environmental considerations

`src/rag/chunking.py` splits on H2 headings. Chunk IDs follow `KB-<CATEGORY>-<section-slug>[-n]`.

## Public references
- **3GPP TS 32.450:** Key Performance Indicators (KPI) for E-UTRAN, definitions
- **3GPP TS 28.552:** 5G performance measurements
- **3GPP TS 28.554:** 5G end-to-end Key Performance Indicators
- **3GPP TS 32.111-1:** Fault management, requirements (alarm handling)
- **3GPP TS 33.501:** Security architecture and procedures for 5G systems
- **ITU-T Y.1541:** Network performance objectives for IP-based services
- **ITU-T G.114:** One-way transmission time
- **ITU-T X.733:** Alarm reporting function
- **NIST SP 800-61:** Computer Security Incident Handling Guide
- **ITIL 4:** Change enablement practice (general change-management guidance)
