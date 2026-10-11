---
category: AVAILABILITY_OUTAGE
title: Cell availability, outage and restoration
version: 1.0
references: [3GPP TS 32.450, 3GPP TS 28.554, 3GPP TS 32.111-1]
---

## Overview
An availability problem means a cell is out of service for part of the time. Every service in its area is affected, so availability incidents are usually the highest priority. Slow restoration (long MTTR) multiplies the impact.

## KPI signature
- Low cell availability (lower than this network's 25th percentile; critical below the 10th).
- Long mean time to repair.
- Usually accompanied by alarms. When availability is critical, other KPIs are often unreliable because the cell carried little traffic.

## Likely root causes
- Power failure at the site: mains outage, rectifier or battery failure.
- Hardware failure of radio or baseband units.
- Transmission loss: the site cannot reach the core.
- Software crashes or failed upgrades leaving the cell locked or restarting.
- Restoration delays: no spare parts, access restrictions, or no field staff available.

## Diagnostic checks
1. Check active alarms for power, hardware and transmission at the site.
2. Confirm whether the cell is down, locked administratively, or restarting repeatedly.
3. Check whether neighbouring sites on the same power or transport path are also down.
4. Review recent software upgrades or configuration changes.
5. For long MTTR, check spare-parts availability, site access and field dispatch times.

## Corrective actions
### Immediate
- Treat critical availability as at least P2; dispatch field operations for power or hardware failures.
- Attempt a remote restart of the failed unit when the alarm indicates a software or hang condition (requires change approval).
- Expand neighbour coverage temporarily if parameters allow (requires change approval).
### Short-term
- Replace failed hardware; restore power systems including batteries and rectifiers.
- Roll back a failed software upgrade.
### Preventive
- Maintain backup power (batteries, generators) sized for expected outage durations.
- Keep spare parts at regional depots to cut MTTR.
- Track repeat outages per site and fix the underlying cause.

## Verification
- Cell availability returns to normal and the cell carries traffic again.
- Alarms clear and stay clear for 24 hours.
- MTTR for the incident is recorded for trend analysis.

## Escalation criteria
- Escalate immediately to field operations and the on-call lead for any site down at a busy location.
- Escalate to the vendor or equipment support when hardware or software failures repeat.

## Interactions with other categories
- **Equipment faults and alarms:** outages almost always raise alarms; use the alarm runbook for the root cause.
- **Configuration changes:** failed upgrades or changes are a common outage trigger.

## Environmental considerations
Storms, snow and extreme heat cause power failures and slow site access, raising both outage frequency and MTTR. Plan field resources ahead of severe weather.
