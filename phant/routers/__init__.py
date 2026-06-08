"""
phant.routers — the PHANT HTTP surface.

All PHANT endpoints are under /phant/* and require identity authentication.
Routers call services; services call repositories; repositories own queries.
No repository or model import belongs inside a router.
"""
