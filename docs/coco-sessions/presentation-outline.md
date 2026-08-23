# ForgePulse — presentation (8-10 slides)

1. **Title.** ForgePulse — Predictive Maintenance and OEE Command Center.
   Snowflake CoCo CLI Hackathon 2026. Mrinal Desai (solo). Deployed URL +
   repo QR.
2. **Problem.** Unplanned downtime is the OEE killer; plants drown in
   sensor streams and paper repair history nobody reads. Problem
   statement named verbatim.
3. **Doctrine.** Rules own safety · Retrieval owns grounding · Model owns
   reasoning. One line each on why.
4. **Architecture.** Stream → Detect → Diagnose → Enrich → Act → Show →
   Prove. One diagram, the autonomous DAG at the center; SPCS console on
   the right; local-adapter boxes dashed with the Cortex targets named.
5. **It acts by itself.** Screenshot: task history SUCCEEDED chain +
   AWO-00001 with parts and window. "Detected days early, investigated,
   scheduled — no human in the loop."
6. **It explains itself.** Screenshot: Diagnosis panel — verdict 98.9%,
   SHAP factors, similar scanned repairs, question buttons, live parts
   stock.
7. **It reads paper.** Scanned handwritten report → extracted row →
   100/100 validation → VECTOR search citing it in a live diagnosis.
8. **It moves OEE.** The bridge: 9.2h unplanned avg → 4h planned = hours
   avoided → availability → +2.6 OEE points on L2. (The track's title,
   answered with arithmetic.)
9. **Snowflake services (the list slide).** ~16 services named; CoCo as
   deployment agent + 3 custom skills; honest gate note: Cortex
   inference entitlement-blocked on trial accounts — ticketed, adapters
   documented, definitions shipped.
10. **Close.** Built solo, deployed in Snowflake, receipts in the repo.
    URL + video link.
