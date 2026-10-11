---
category: TRANSPORT_QOS
title: Transport and QoS degradation (latency, jitter, packet loss)
version: 1.0
references: [ITU-T Y.1541, ITU-T G.114, 3GPP TS 28.554]
---

## Overview
Transport degradation affects the path between the radio site and the core: backhaul links, routers and switches. Users see lag, choppy voice and video, and failed sessions even with a strong radio signal. Real-time services suffer first because they are sensitive to delay and jitter.

## KPI signature
- High latency, high jitter and high packet loss (worse than this network's 75th percentile), often together.
- Throughput may fall because lost packets trigger retransmissions.
- Radio KPIs (signal strength, handover success) are typically normal. That separates transport problems from radio problems.

## Likely root causes
- Backhaul link congestion or an under-dimensioned transport link.
- A degraded physical link: fibre damage, a dirty connector, microwave fading or misalignment.
- Interface errors or duplex mismatches on routers and switches.
- QoS misconfiguration, so real-time traffic is not prioritized.
- Routing changes that send traffic over a longer or congested path.

## Diagnostic checks
1. Run latency, jitter and loss measurements (for example TWAMP or ping series) from the site to the core and compare with the baseline.
2. Check interface counters on the site router and aggregation devices for errors, discards and CRC failures.
3. Check backhaul utilization during the affected period.
4. For microwave links, check received signal level and modulation changes; for fibre, check optical power levels.
5. Review recent transport changes: routing, QoS policies, maintenance.

## Corrective actions
### Immediate
- Reroute traffic to a backup or protection path if available (requires change approval).
- Prioritize voice and real-time traffic with QoS marking and queuing if the policy is missing or wrong (requires change approval).
### Short-term
- Repair or replace degraded physical components: clean or replace connectors, realign microwave antennas, repair fibre.
- Correct interface configuration issues such as duplex or MTU mismatches.
- Increase backhaul capacity where utilization is the cause.
### Preventive
- Monitor transport KPIs continuously with alerts on latency, jitter and loss trends.
- Build path diversity for critical sites.

## Verification
- Latency, jitter and packet loss return to the site's baseline for a full traffic cycle.
- Interface error counters stop increasing.
- Voice and video quality complaints stop.

## Escalation criteria
- Escalate to the transport or IP team when the degradation is on shared aggregation links or affects several sites.
- Escalate to field operations for physical repairs (fibre, microwave alignment).

## Interactions with other categories
- **Congestion and capacity:** heavy load can cause transport congestion; confirm which side saturates first.
- **Equipment faults and alarms:** transport alarms (link down, high bit-error rate) often accompany these symptoms.

## Environmental considerations
Heavy rain and snow attenuate microwave links (rain fade) and raise packet loss on radio-based backhaul. High temperatures can affect outdoor transport equipment.
