# CoCo session receipt 03 — SPCS deploys, agent skills, semantic layer
**Dates:** 2026-08-21 → 08-23 · **Account:** DMXGSFN-EYB14592 · **Screenshots:** `img/Screenshot 2026-08-21*.png` +

## SPCS deployment loop
Image repository + compute pool + stage created from `sql/01_spcs_infra.sql`;
service from `sql/02_create_service.sql`. CoCo ran the drop → create →
poll-to-READY → SHOW ENDPOINTS → DESCRIBE (pinned sha verification) loop
across several image iterations. Root cause of the recurring stale-image
mystery was found on the local side (deleted Dockerfile made every
"build" silently fail while pushes re-shipped the old digest) — the
pinned-sha DESCRIBE check CoCo ran is what proved it.

## Agent skills, live-verified
- `/work-order-dispatch explain AWO-00001` — CoCo hit three wrong-column
  errors, **self-corrected by DESCRIBE-ing the tables**, then delivered
  tier reasoning, live stock counts, window logic, and OEE impact math
  with a sample-size caveat.
- `rca-investigation` on AST-007 — verdict + confidence, SHAP factors
  with live values, narrative sections, same-asset vs fleet history
  distinguished, and **synthesis beyond any single table**: bounded
  degradation onset using the clean July PM, flagged the 30%-worn
  coupling insert as a plausible accelerant, generalized lubrication as
  the systemic fleet root cause from three technicians' notes.

## Semantic layer
`sql/07_semantic_agent.sql`: CoCo consulted current docs
(`cortex search docs`), adapted SEMANTIC VIEW dimension syntax and the
AGENT PROFILE clause to the live platform, deployed
PLANT_SEMANTIC_VIEW + FORGEPULSE_AGENT (both confirmed via SHOW), and
synced the file to the deployed syntax. Invocation remains
entitlement-gated; objects are real.
