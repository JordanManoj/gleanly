"""The fetch ladder: legitimate routes to content, cheapest first.

Rung 1  http.py      plain HTTP GET with an honest User-Agent
Rung 2  embedded.py  data the page already ships (JSON-LD, __NEXT_DATA__, ...)
Rung 3  browser.py   optional Playwright rendering (the [browser] extra)

Supporting modules: robots.py (RFC 9309), ratelimit.py (per-host politeness),
router.py (when to climb to the next rung).
"""
