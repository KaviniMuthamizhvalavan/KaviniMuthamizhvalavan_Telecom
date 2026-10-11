---
category: SECURITY_AUTH
title: Security incidents and authentication failures
version: 1.0
references: [3GPP TS 33.501, NIST SP 800-61]
---

## Overview
Security incidents and authentication failures can signal an attack (signalling floods, credential abuse, rogue devices) or a misconfiguration in the authentication chain. Both can deny service to legitimate users, and attacks also put data at risk.

## KPI signature
- High security-incident count and high authentication failures (worse than this network's 75th percentile).
- Connection setup success may fall if legitimate users are rejected.
- Other KPIs are often normal, which helps separate security issues from radio or transport faults.

## Likely root causes
- A signalling or registration flood from compromised or misbehaving devices.
- Credential problems: expired certificates, subscriber-data mismatches or key issues in the authentication chain.
- Misconfiguration of security functions after a change.
- A rogue base station or other spoofing attempt in the area.
- Clock or time-synchronization errors breaking time-sensitive authentication.

## Diagnostic checks
1. Check whether authentication failures come from many devices (a systemic issue) or a small set (abuse or faulty devices).
2. Review failure causes in core network logs: unknown subscriber, MAC failure, synchronization failure.
3. Check certificate validity and recent changes to authentication or security functions.
4. Look for unusual registration rates or signalling patterns.
5. Check for rogue-cell reports or unexpected cell identities in the area.

## Corrective actions
### Immediate
- Follow the security incident process: isolate and contain before you fix, and preserve logs as evidence.
- Rate-limit or block clearly abusive devices or sources (requires change approval).
- Escalate suspected attacks to the security operations team at once.
### Short-term
- Renew expired certificates and correct subscriber-data or key mismatches.
- Roll back security-related configuration changes that started the failures (requires change approval).
### Preventive
- Monitor authentication failure rates per cause with alert thresholds.
- Keep certificate and key lifecycle management automated.
- Run periodic security audits of network functions.

## Verification
- Authentication failure and security-incident rates return to their normal range.
- Legitimate users register and connect normally.
- The security team confirms containment and closes the incident.

## Escalation criteria
- Always escalate suspected attacks or data exposure to security operations, regardless of service impact.
- Treat critical security incidents together with critical authentication failures as at least P2.

## Interactions with other categories
- **Configuration changes:** security misconfiguration often follows changes to network functions.
- **Congestion and capacity:** signalling floods can look like congestion on the control plane.

## Environmental considerations
Weather has no direct link to security incidents. Attacks often coincide with large public events, when many devices gather in one place.
