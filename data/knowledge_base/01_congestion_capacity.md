---
category: CONGESTION_CAPACITY
title: Congestion and capacity
version: 1.0
references: [3GPP TS 28.552, 3GPP TS 28.554, 3GPP TS 32.450]
---

## Overview
Congestion occurs when offered load exceeds what a cell or its backhaul can serve. Users see slow data, buffering video and rising latency, usually at peak hours or during events. The fix is to redistribute or add capacity, not to repair a fault.

## KPI signature
- High user count and high data usage (worse than this network's 75th percentile).
- Low throughput per cell, often with rising latency.
- Accessibility can dip at the busiest moments, while availability and alarms often stay normal. That pattern separates congestion from equipment faults.

## Likely root causes
- Peak-hour demand or a local event exceeding the cell's designed capacity.
- Uneven load: one cell is saturated while its neighbours have headroom (poor load balancing).
- Insufficient spectrum or carriers deployed for the area's growth.
- Backhaul capacity smaller than the radio capacity, so the bottleneck sits on the transport link.
- Heavy users or abnormal traffic (large uploads, misbehaving devices) consuming a disproportionate share.

## Diagnostic checks
1. Plot user count, data volume and throughput for the cell and its neighbours over the last 7 days to confirm a load-driven pattern.
2. Compare radio resource utilization (PRB usage) with throughput: high utilization with low throughput per user means radio congestion.
3. Check backhaul link utilization; if it is near its limit, treat the case as transport congestion as well.
4. Check whether neighbouring cells have spare capacity and whether load-balancing features are enabled.
5. Look for abnormal top talkers or device types driving traffic.

## Corrective actions
### Immediate
- Enable or tune load balancing and traffic steering towards neighbours with headroom (requires change approval).
- Apply temporary QoS prioritization for voice and critical services during the peak.
### Short-term
- Rebalance cell parameters (for example handover offsets or carrier priorities) so edge users move to less loaded cells (requires change approval).
- Activate an additional carrier or bandwidth if licensed spectrum is available (requires change approval).
- Upgrade backhaul capacity if the transport link is the bottleneck.
### Preventive
- Add capacity through cell splitting, small cells or new sectors where growth trends predict sustained congestion.
- Track busy-hour utilization weekly and plan capacity before thresholds are crossed.

## Verification
- Throughput per user and latency return to the cell's normal range at the next busy hour.
- Neighbour cells absorb load without becoming congested themselves.
- No increase in dropped calls or handover failures after the parameter changes.

## Escalation criteria
- Escalate to RAN planning or capacity engineering when congestion recurs on most busy hours for a week.
- Escalate to the transport team when backhaul utilization is the limiting factor.

## Interactions with other categories
- **Transport and QoS:** congestion raises latency and packet loss; check both runbooks.
- **Mobility and handover:** load-balancing changes can raise handover failures if offsets are too aggressive.
- **Radio coverage:** a coverage hole on a neighbour can push its users onto the congested cell.

## Environmental considerations
Events, holidays and seasonal tourism change demand sharply. Rain and snow can concentrate users indoors and shift load between cells.
