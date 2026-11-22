# Security policy

## Supported versions

gleanly is in alpha. Security fixes go into the latest release only.

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's private
vulnerability reporting instead: open the repository's **Security** tab and choose
**Report a vulnerability**. You can expect a first answer within 7 days.

Useful details: the gleanly version, a minimal input (URL, HTML, PDF or image) that
triggers the problem, and what happens.

## What gleanly treats as untrusted

Everything it fetches or opens: web pages, PDFs, images, robots.txt, ai.txt, TDMRep
files and search results. gleanly parses this input but never executes it; JavaScript
only runs inside the optional Playwright browser (`[browser]` extra), in its sandbox.
Size limits (`max_bytes`) and timeouts apply to every download.

## How dependencies are checked

CI audits the locked dependencies for known vulnerabilities on every push
(`pip-audit`), and new dependencies are license- and maintenance-checked before they are
added (see [docs/dependencies.md](docs/dependencies.md)).
