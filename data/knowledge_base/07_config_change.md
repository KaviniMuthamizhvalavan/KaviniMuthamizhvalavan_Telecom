---
category: CONFIG_CHANGE
title: Configuration change issues
version: 1.0
references: [3GPP TS 28.552, ITIL 4 change enablement]
---

## Overview
Configuration and parameter changes are a leading cause of self-inflicted incidents. Many changes in a short time, or changes that fail or are only partly applied, leave cells in an inconsistent state that degrades service.

## KPI signature
- Many parameter changes (more than this network's 75th percentile).
- Low successful-configuration-change rate (lower than the 25th percentile).
- Service KPIs that start degrading right after a change window.

## Likely root causes
- Changes applied without enough review or testing.
- Partially applied changes: some cells updated, others not.
- Conflicting changes from different teams or automation tools.
- Wrong parameter values (typos, wrong cell lists, wrong units).
- Software incompatibility between the new configuration and the running version.

## Diagnostic checks
1. Pull the change log for the affected cells and compare change times with KPI degradation onset.
2. Identify failed or partially applied changes and their error messages.
3. Compare the current configuration with the last known-good baseline.
4. Check whether several teams or tools changed the same cells.
5. Confirm the software version supports the changed parameters.

## Corrective actions
### Immediate
- Roll back the most recent change linked to the degradation (requires change approval).
- Freeze further changes on the affected cells until the cause is understood.
### Short-term
- Re-apply failed changes correctly, or complete partial changes consistently across all target cells (requires change approval).
- Fix wrong parameter values against the design baseline.
### Preventive
- Use change enablement with peer review, test windows and rollback plans.
- Automate configuration-consistency audits against a golden baseline.
- Track change success rate per team and tool.

## Verification
- The configuration matches the intended baseline on all target cells.
- Service KPIs return to their pre-change range.
- The successful-change rate recovers for subsequent changes.

## Escalation criteria
- Escalate to the change manager when a change caused a service-affecting incident.
- Escalate to the vendor when configuration fails because of software incompatibility.

## Interactions with other categories
Configuration errors can show up as any other category: handover failures after neighbour changes, coverage loss after tilt changes, outages after failed upgrades. Always check the change log before deeper troubleshooting.

## Environmental considerations
Avoid change windows during severe weather or major events, when the network has less headroom and field access is harder.
