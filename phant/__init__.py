"""
PHANT — the PHANG ecosystem intelligence layer.

Identity Lock v1 (frozen):
    Products create reality. PHANT creates understanding.
    Products own execution. PHANT owns cognition.
    Products remain fully functional if PHANT is removed.
    PHANT becomes blind if products are removed.

PHANT is NOT another app inside PHANG. It is the intelligence layer that sits
above every product. The elephant button is the doorway into that layer.

This package owns ONLY cognition:
    contexts · sessions · memories · decisions · outcomes · constraints · divergences

It never owns execution. Tasks, projects, goals, knowledge and revenue actions
live inside the products (MyTodo, InfoPro, NextDoor, …). PHANT observes their
events, remembers what matters, reasons over it, challenges the founder, and
responds through chat.

Boundary rule:
    If a capability is required for a product to operate → the product owns it.
    If a capability exists to understand, explain, connect, challenge or advise
    across products → PHANT owns it.

Runtime: lives inside the MyTodo FastAPI app (Vercel + Neon). It reuses MyTodo's
SQLAlchemy Base/engine/session and the shared DeepSeek client — no new
infrastructure, no second database, no duplicated AI key.
"""

__all__ = ["models", "schemas", "llm", "migrations"]
