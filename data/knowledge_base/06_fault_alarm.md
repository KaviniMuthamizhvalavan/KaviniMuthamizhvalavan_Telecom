---
category: FAULT_ALARM
title: Equipment faults and alarm storms
version: 1.0
references: [3GPP TS 32.111-1, ITU-T X.733]
---

## Overview
Alarms report equipment or software faults. A sudden rise in alarm counts, critical alarms in particular, signals degrading hardware or a cascading fault. A high fault occurrence rate means problems keep recurring rather than being fixed.

## KPI signature
- High alarm count and high critical alarm count (worse than this network's 75th percentile).
- High fault occurrence rate.
- Service KPIs often follow: in this network's history, cases with many critical alarms also tend to show low throughput.

## Likely root causes
- Failing hardware: radio units, power modules, fans, transceivers.
- Software defects or memory leaks causing repeated restarts.
- Over-temperature from cooling failures.
- A single upstream fault (transport or power) raising many secondary alarms at once (an alarm storm).
- Previous repairs that treated symptoms only, so the fault recurs.

## Diagnostic checks
1. Group active alarms by type and site to separate the root alarm from secondary alarms.
2. Identify the first alarm in time; storms usually start from one root event.
3. Check hardware health: temperatures, fan status, power-supply readings.
4. Check the fault history of the site for recurring alarm types.
5. Check whether a software version is shared by the affected sites (a common-mode defect).

## Corrective actions
### Immediate
- Suppress duplicate secondary alarms and focus on the root alarm.
- Restart the affected software process or unit when the alarm indicates a software hang (requires change approval).
- Dispatch field operations for critical hardware alarms at busy sites.
### Short-term
- Replace faulty hardware; repair cooling systems.
- Apply vendor patches for known software defects (requires change approval).
### Preventive
- Track fault occurrence per site and component; replace units with repeated failures.
- Tune alarm correlation rules so storms are grouped automatically.
- Do proactive maintenance on cooling and power systems before summer.

## Verification
- Critical alarms clear and do not recur within 72 hours.
- Fault occurrence rate for the site returns to normal.
- Linked service KPIs (throughput, availability) recover.

## Escalation criteria
- Escalate to the vendor when the same alarm recurs after repair, or when a software defect is suspected across several sites.
- Treat critical alarms together with a critical fault rate as at least P2.

## Interactions with other categories
- **Availability and outage:** unresolved critical alarms often end in outages.
- **Transport and QoS:** transport alarms appear together with latency and packet loss.
- **Configuration changes:** a bad change can trigger a sudden alarm storm.

## Environmental considerations
Heat raises hardware failure rates and cooling alarms. Rain and snow can cause water ingress and power faults. In this network's history, rain and snow coincide with markedly higher fault rates.
