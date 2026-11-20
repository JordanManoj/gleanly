# Configuring retries

tidekeeper retries failed requests automatically. This page explains which failures are retried, how the delay between attempts grows, and how to change both.

Note

Retries only apply to idempotent methods (GET, HEAD, PUT, DELETE) unless you opt in with `retry_unsafe=True`.

## Defaults

Out of the box, a request is attempted up to three times. The delay doubles after each failure, starting at half a second.

| Setting | Default | Meaning |
| --- | --- | --- |
| `max_attempts` | 3 | Total tries, including the first |
| `backoff` | 0.5 | First delay in seconds |
| `retry_on` | 502, 503, 504 | Status codes that trigger a retry |

## Writing a custom policy

Pass a `RetryPolicy` to the client to override the defaults:

```python
from tidekeeper import Client, RetryPolicy

policy = RetryPolicy(max_attempts=5, backoff=1.0, retry_on={429, 503})
client = Client(retry=policy)
```

Delays are capped at 30 seconds, so a long run of failures never stalls a worker for more than half a minute between attempts.
