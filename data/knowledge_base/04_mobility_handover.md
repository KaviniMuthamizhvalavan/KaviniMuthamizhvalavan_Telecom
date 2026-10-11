---
category: MOBILITY_HANDOVER
title: Mobility and handover failures
version: 1.0
references: [3GPP TS 32.450, 3GPP TS 28.552]
---

## Overview
A handover moves an active connection from one cell to another as the user moves. When handovers fail, moving users (drivers, train passengers) lose calls and data sessions even if coverage looks adequate when standing still.

## KPI signature
- Low handover success rate (lower than this network's 25th percentile).
- Higher call drop rate, especially along roads and railways.
- Coverage and transport KPIs may look normal for stationary users.

## Likely root causes
- Missing or wrong neighbour relations, so the target cell is not prepared.
- Handover thresholds, offsets or timers that trigger too late (drops) or too early (ping-pong).
- Overloaded target cells rejecting incoming handovers.
- Inter-frequency or inter-technology handover misconfiguration.
- Synchronization or timing problems between sites.

## Diagnostic checks
1. Break down handover failures by target cell to find the failing neighbour pairs.
2. Check neighbour lists for missing or outdated relations, including recently added sites.
3. Review handover parameters (offsets, hysteresis, time-to-trigger) against the design defaults.
4. Check target-cell load and admission rejections.
5. Check site synchronization alarms.

## Corrective actions
### Immediate
- Add missing neighbour relations for the worst failing pairs (requires change approval).
- Roll back any recent handover parameter change linked to the start of the failures (requires change approval).
### Short-term
- Tune handover offsets, hysteresis and time-to-trigger on the failing pairs (requires change approval).
- Relieve overloaded target cells (see the congestion runbook).
- Fix synchronization issues at the affected sites.
### Preventive
- Enable automatic neighbour relation features where available, with operator review.
- Monitor handover success per neighbour pair and alert on sudden drops.

## Verification
- Handover success returns to the area's normal range.
- Call drops along the affected route fall to baseline, confirmed by a drive test where possible.
- No ping-pong increase after the parameter changes.

## Escalation criteria
- Escalate to RAN optimization for parameter and neighbour changes.
- Escalate to the transport or synchronization team when timing alarms are present.

## Interactions with other categories
- **Radio coverage:** weak edge coverage is a frequent hidden cause of handover failure.
- **Configuration changes:** handover problems often follow parameter changes; check change logs first.
- **Congestion and capacity:** loaded target cells reject handovers.

## Environmental considerations
Weather changes traffic patterns (more driving in rain, fewer pedestrians). Snow and rain can alter edge coverage enough to expose marginal handover settings.
