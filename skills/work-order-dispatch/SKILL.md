---
name: work-order-dispatch
description: Create, inspect, or explain maintenance work orders - tier rules, parts availability from inventory, and scheduling into the lowest-load production window, plus the OEE impact of planned vs unplanned intervention. Use when asked "create a work order", "when is maintenance scheduled", "are parts in stock", or "what is the OEE impact".
---

# Work-order dispatch

The ACT layer's logic, explained and operable.

## Data sources
- `OEE_DB.ANALYTICS.WORK_ORDERS_GENERATED` - auto-created work orders
  (`AWO-...`), tier, parts, schedule, status
- `OEE_DB.ERP.SPARE_PARTS_INVENTORY` - stock levels and lead times
- `OEE_DB.ERP.PRODUCTION_SCHEDULE` - shift loads (window selection input)
- `OEE_DB.ERP.WORK_ORDER_HISTORY` - historical downtime per failure mode
- `OEE_DB.ANALYTICS.NOTIFICATIONS_LOG` - dispatch receipts

## Tier rules (deterministic - never overridden by any model)
- Tier A: HIGH severity on criticality HIGH assets - schedule earliest
  low-load window; reserve parts; notify maintenance lead.
- Tier B: MEDIUM - next planned window within 7 days.
- Tier C: LOW / watch - bundle into monthly PM.
- SENSOR_FAULT (FP-03) is NEVER a parts dispatch: instrumentation ticket.

## Procedure
1. To explain an order: join the work order to its finding and event;
   show tier reasoning, parts check (stock at least the required count),
   chosen window and why (lowest planned load in PRODUCTION_SCHEDULE).
2. OEE impact: avg unplanned downtime for the mode from WORK_ORDER_HISTORY
   vs the planned 4h stop -> avoided hours -> availability delta over the
   weekly window -> projected OEE (A x P x Q). State history sample size.
3. To create one manually, CALL OEE_DB.ANALYTICS.ACT_ON_FINDINGS() after
   confirming with the user - creation is normally autonomous.

## Rules
- Idempotency: one open work order per asset+mode; check before creating.
- Quote wo_id, part numbers, stock counts, and window timestamps verbatim
  from queries.
