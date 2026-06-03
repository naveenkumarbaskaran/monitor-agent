# monitor-agent-ai

An AI-powered agent that **automatically generates monitoring alerts, dashboards, and runbooks** from your application source code.

Give it a source directory; it uses Claude to understand your stack and writes ready-to-use:

- **Prometheus alert rules** YAML (one per concern)
- **Grafana dashboard** JSON (one panel per alert)
- **Markdown runbook** (diagnosis + remediation per alert)

Supported monitoring stacks: `prometheus` (default), `datadog`, `cloudwatch`.

---

## Quick start

```bash
# Install
pip install monitor-agent-ai

# Set your Anthropic API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run against your project
monitor-agent generate --src ./my-app --output ./monitoring --stack prometheus
```

The agent will:
1. Walk your source tree and read relevant files
2. Identify endpoints, databases, queues, and external dependencies
3. Generate one `alerts/`, `dashboards/`, and `runbooks/` file per concern
4. Print a summary of every file written

---

## Installation

```bash
# From PyPI
pip install monitor-agent-ai

# From source
git clone https://github.com/example/monitor-agent-ai
cd monitor-agent-ai
pip install -e .
```

Requires Python 3.11+.

---

## CLI reference

### `generate` — full AI run

```
monitor-agent generate [OPTIONS]

Options:
  --src PATH      Application source directory  [default: .]
  --output TEXT   Output directory              [default: monitoring]
  --stack TEXT    prometheus | datadog | cloudwatch  [default: prometheus]
  --api-key TEXT  Anthropic API key (or ANTHROPIC_API_KEY env var)
  --quiet         Suppress per-step progress output
  --help
```

**Example:**

```bash
monitor-agent generate \
  --src ./services/api \
  --output ./infra/monitoring \
  --stack prometheus
```

### `analyze` — static-only scan (no API call)

```
monitor-agent analyze [OPTIONS]

Options:
  --src PATH  Application source directory  [default: .]
  --help
```

Runs the built-in heuristic scanner and prints a profile of detected languages, frameworks, databases, queues, and external dependencies — no Anthropic API key needed.

```bash
monitor-agent analyze --src ./my-app
```

---

## Output structure

```
monitoring/
  alerts/
    http_error_rate.yaml
    db_connection_pool.yaml
    queue_consumer_lag.yaml
    ...
  dashboards/
    http_error_rate_dashboard.json
    db_connection_pool_dashboard.json
    ...
  runbooks/
    http_error_rate_runbook.md
    db_connection_pool_runbook.md
    ...
```

### Alert rules YAML example

```yaml
groups:
  - name: http_alerts
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m]))
          /
          sum(rate(http_requests_total[5m])) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "HTTP error rate above 5%"
          description: "{{ $value | humanizePercentage }} of requests are failing."
```

### Runbook Markdown example

```markdown
# Runbook: HighErrorRate

## Overview
Fires when more than 5% of HTTP requests return a 5xx status over a 2-minute window.

## Likely causes
- Unhandled exception in application code
- Downstream service returning errors
- Database connection pool exhaustion

## Diagnostic steps
1. Check application logs: `kubectl logs -l app=api --tail=200`
2. Inspect recent deployments: `kubectl rollout history deployment/api`
3. Query error breakdown: `sum by (path, status) (rate(http_requests_total{status=~"5.."}[5m]))`

## Remediation
- Roll back if correlated with a recent deploy
- Scale up replicas if load-related: `kubectl scale deployment/api --replicas=N`
- Check downstream health dashboards
```

---

## Python API

```python
from monitor_agent import MonitorAgent, AppAnalyzer

# Static analysis only
analyzer = AppAnalyzer(src="./my-app")
profile = analyzer.analyse()
print(profile.summary())

# Full AI-powered generation
agent = MonitorAgent(api_key="sk-ant-...")   # or reads ANTHROPIC_API_KEY
summary = agent.generate(
    src="./my-app",
    output="./monitoring",
    stack="prometheus",
)
print(summary)
```

---

## How it works

1. **Static scan (`AppAnalyzer`)** — regex heuristics detect languages, frameworks (FastAPI, Express, Spring, Gin, …), databases (Postgres, Redis, MongoDB, …), queues (Kafka, RabbitMQ, SQS, Celery, …), and external deps (Stripe, Auth0, AWS, …).

2. **AI agent (`MonitorAgent`)** — drives `claude-sonnet-4-6` with three tools:
   - `list_files(dir)` — discover project structure
   - `read_file(path)` — inspect source files
   - `write_file(path, content)` — emit artefacts

   The agent autonomously decides which files to read, what signals to alert on, and writes all three artefact types per concern. The agentic loop continues until Claude signals `end_turn`.

3. **Output** — all files land under `--output` and are ready to load into Prometheus / Grafana / Alertmanager.

---

## Development

```bash
pip install -e ".[dev]"

# Lint
ruff check monitor_agent/

# Type check
mypy monitor_agent/

# Tests
pytest
```

---

## License

MIT
