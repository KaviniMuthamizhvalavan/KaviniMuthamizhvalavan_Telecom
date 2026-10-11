---
category: RADIO_COVERAGE
title: Radio coverage and signal quality
version: 1.0
references: [3GPP TS 32.450, 3GPP TS 28.552]
---

## Overview
Coverage problems occur where the radio signal is too weak or too noisy for reliable service. Users see few signal bars, failed call setups and dropped calls, typically at cell edges, indoors or behind obstacles.

## KPI signature
- Weak signal strength (lower than this network's 25th percentile).
- Low connection setup success rate and higher call drop rate.
- Throughput may fall at the edge. Transport KPIs are usually normal.

## Likely root causes
- A coverage hole: inadequate site density, terrain or new buildings blocking the signal.
- Antenna problems: wrong tilt or azimuth, damaged antenna or feeder, water ingress.
- Reduced transmit power from a hardware fault or a configuration error.
- Uplink or downlink interference raising the noise floor.
- Indoor penetration loss where users are mostly inside buildings.

## Diagnostic checks
1. Map the weak-signal reports and compare them with the predicted coverage of the serving and neighbouring cells.
2. Check transmit power and antenna configuration (tilt, azimuth) against the planned values.
3. Check feeder and antenna alarms and VSWR readings at the site.
4. Measure interference (uplink noise rise) on the affected cells.
5. Review recent changes to antenna tilt, power or neighbour cells.

## Corrective actions
### Immediate
- Restore planned transmit power or antenna settings if a recent change reduced them (requires change approval).
- Dispatch field operations for a damaged antenna or feeder.
### Short-term
- Optimize antenna tilt and azimuth to close the gap (requires change approval).
- Remove or mitigate interference sources.
- Adjust neighbour relations so users at the edge are served by the best cell.
### Preventive
- Add coverage with new sites, small cells or indoor solutions in persistent weak areas.
- Schedule periodic drive tests or use crowd-sourced measurements to detect gaps early.

## Verification
- Signal strength and connection setup success return to the area's normal range.
- Call drop rate falls back to baseline.
- No new coverage complaints from the area over the following week.

## Escalation criteria
- Escalate to RAN optimization for tilt and neighbour changes, and to radio planning when new sites are needed.
- Escalate to field operations for hardware repairs.

## Interactions with other categories
- **Mobility and handover:** weak signal at cell edges often appears as handover failures and drops.
- **Congestion and capacity:** a coverage hole can push users onto distant, overloaded cells.

## Environmental considerations
Foliage, heavy rain and snow add attenuation at higher frequency bands. Seasonal changes such as leaves on trees can create coverage changes that come and go.
