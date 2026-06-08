"""
phant.services — PHANT's cognition logic.

Services orchestrate repositories, the language interface, and read-only product
data. They contain the rules; repositories contain the queries; routers contain
the HTTP surface.

    ecosystem_service   — read-only product snapshots (PHANT observing reality)
    memory_service      — belief creation (the only writer of memories)
    ingest_service      — Event → Signal(function) → Memory significance gate
    decision_service    — decision + outcome capture and calibration delta
    brief_service       — the daily intelligence brief
    divergence_service  — the challenge engine (what was said vs what happened)
    chat_service        — the elephant-button doorway (two-mode answering)
"""
