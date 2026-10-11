---
category: NORMAL
title: NOC triage, prioritization and escalation
version: 1.0
references: [3GPP TS 32.111-1, ITU-T X.733, 3GPP TS 28.554]
---

## Overview
This runbook covers the first minutes of any network incident: confirm the problem, size its impact, assign a priority and decide who owns it. Use it on its own when no KPI is clearly abnormal, and alongside the category runbook when one is.

## KPI signature
No single KPI dominates. In this network's history, about 1% of records have no degraded KPI at all, and a typical record has around five KPIs worse than the 75th percentile. A report with few or no abnormal KPIs is therefore below the usual severity, and often a localized or perceived issue rather than a network-wide fault.

## Likely root causes
- A customer-side or device-side problem rather than a network fault.
- A short-lived event that has already cleared (transient interference, a brief traffic spike).
- A monitoring gap: the affected KPI is not collected, or is aggregated too coarsely to show the problem.
- An early-stage fault that has not yet crossed degradation thresholds.

## Diagnostic checks
1. Confirm the symptom with a second source: recent KPI samples, drive-test data, or several independent customer reports.
2. Check the alarm list for the affected cells and neighbours (active, cleared in the last 24 hours).
3. Compare current KPIs with the same cell's normal range and with similar historical cases.
4. Check for recent changes: parameter changes, software updates, maintenance windows.
5. Size the blast radius: users served, traffic volume, services affected (voice, data, real-time, access).

## Corrective actions
### Immediate
- Acknowledge the incident, open a ticket and record the symptoms, the affected area and the time of first report.
- Assign priority from severity, impact and fault risk; escalate P1 incidents to the on-call lead at once.
### Short-term
- If no network KPI is abnormal, close the loop with the reporter and ask for device, location and time details.
- Add temporary monitoring at a finer granularity if a monitoring gap is suspected.
### Preventive
- Review recurring low-severity reports monthly; repeated reports from one area are an early warning.
- Keep runbooks and escalation contacts current.

## Verification
The incident is resolved when the reporter confirms normal service and the affected KPIs stay within their usual range for at least one full traffic cycle (normally 24 hours).

## Escalation criteria
- Escalate immediately for P1 incidents, any critical service KPI (availability, call drops, setup success, throughput) at a busy cell, or a suspected security event.
- Escalate to the owning team when the category runbook names one, or when the incident is not improving after the short-term actions.

## Interactions with other categories
Most real incidents combine categories. Work the most service-affecting category first (availability, then mobility or coverage, then transport and congestion), and record secondary categories as contributing factors.

## Environmental considerations
Weather and temperature are context, not causes on their own. Record them with the incident; in this network's history, adverse weather (rain, snow) coincides with higher fault rates.
