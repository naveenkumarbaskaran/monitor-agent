"""MonitorAgent: uses Claude to analyse an app and generate monitoring artefacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import anthropic

# ---------------------------------------------------------------------------
# Tool implementations (called by the agent loop)
# ---------------------------------------------------------------------------

def _read_file(path: str) -> str:
    """Return the contents of *path*.  Returns an error message on failure."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return f"ERROR: file not found: {path}"
    except PermissionError:
        return f"ERROR: permission denied: {path}"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc}"


def _list_files(directory: str) -> str:
    """Return a JSON array of file paths inside *directory* (recursive, max 500)."""
    try:
        base = Path(directory)
        if not base.is_dir():
            return f"ERROR: not a directory: {directory}"
        paths = [
            str(p.relative_to(base))
            for p in sorted(base.rglob("*"))
            if p.is_file()
        ][:500]
        return json.dumps(paths)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc}"


def _write_file(path: str, content: str) -> str:
    """Write *content* to *path*, creating parent directories as needed."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"OK: wrote {len(content)} bytes to {path}"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc}"


# ---------------------------------------------------------------------------
# Tool schemas (JSON Schema objects describing each tool for the API)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": (
            "Read the complete content of a single file from disk. "
            "Use this to inspect source files, configuration files, "
            "Docker / Compose files, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": (
            "Recursively list all files inside a directory. "
            "Returns a JSON array of relative paths (up to 500 entries). "
            "Use this to discover the project structure before reading files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dir": {
                    "type": "string",
                    "description": "Path to the directory to list.",
                },
            },
            "required": ["dir"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write text content to a file, creating any missing parent directories. "
            "Use this to emit Prometheus alert rules YAML, Grafana dashboard JSON, "
            "and Markdown runbook files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Destination path for the file.",
                },
                "content": {
                    "type": "string",
                    "description": "Full text content to write.",
                },
            },
            "required": ["path", "content"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

TOOL_FN = {
    "read_file": lambda inp: _read_file(inp["path"]),
    "list_files": lambda inp: _list_files(inp["dir"]),
    "write_file": lambda inp: _write_file(inp["path"], inp["content"]),
}


def _dispatch_tool(name: str, tool_input: dict[str, Any]) -> str:
    fn = TOOL_FN.get(name)
    if fn is None:
        return f"ERROR: unknown tool '{name}'"
    return fn(tool_input)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are MonitorAgent, an expert SRE and observability engineer.

Your task:
1. Explore the source directory provided by the user with `list_files` and
   `read_file` to understand the application stack.
2. Identify: HTTP endpoints, database connections, message-queue consumers,
   external service dependencies, and any existing instrumentation.
3. For EVERY significant alert-worthy concern (latency, error rate, saturation,
   missing heartbeat, dependency failure, queue depth, etc.) generate:

   a) A Prometheus alert rule in valid YAML (groups/rules format).
      File: <output_dir>/alerts/<alert_name>.yaml

   b) A Grafana dashboard JSON panel configuration covering the same signal.
      File: <output_dir>/dashboards/<alert_name>_dashboard.json

   c) A Markdown runbook explaining the alert, probable causes, diagnostic
      steps, and remediation actions.
      File: <output_dir>/runbooks/<alert_name>_runbook.md

4. Write all files using `write_file`.
5. After writing all files, summarise what you generated and why.

Be thorough. An alert without a runbook is incomplete.
Use industry-standard metric names (http_requests_total, process_cpu_seconds_total, etc.).
"""


# ---------------------------------------------------------------------------
# MonitorAgent
# ---------------------------------------------------------------------------

class MonitorAgent:
    """Agentic monitoring-setup assistant powered by Claude claude-sonnet-4-6."""

    MODEL = "claude-sonnet-4-6"
    MAX_TOKENS = 8192

    def __init__(self, api_key: str | None = None, verbose: bool = True) -> None:
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )
        self.verbose = verbose

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        src: str,
        output: str,
        stack: str = "prometheus",
    ) -> str:
        """Run the agent and return the final text summary.

        Parameters
        ----------
        src:
            Path to the application source tree to analyse.
        output:
            Directory where monitoring artefacts will be written.
        stack:
            Monitoring stack hint ("prometheus", "datadog", "cloudwatch").
        """
        src_path = str(Path(src).resolve())
        out_path = str(Path(output).resolve())

        user_message = (
            f"Analyse the application in directory '{src_path}' and generate "
            f"monitoring configuration for the '{stack}' stack. "
            f"Write all output files under '{out_path}'."
        )

        if self.verbose:
            print(f"[MonitorAgent] source={src_path}  output={out_path}  stack={stack}")
            print(f"[MonitorAgent] model={self.MODEL}")
            print()

        return self._run_loop(user_message)

    # ------------------------------------------------------------------
    # Internal agentic loop
    # ------------------------------------------------------------------

    def _run_loop(self, user_message: str) -> str:
        """Run the manual agentic loop until Claude returns end_turn."""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_message}
        ]
        final_text = ""

        while True:
            response = self._client.messages.create(
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOLS,  # type: ignore[arg-type]
                messages=messages,
            )

            if self.verbose:
                self._print_response_summary(response)

            # Accumulate any text blocks
            for block in response.content:
                if block.type == "text":
                    final_text = block.text

            # Append assistant turn
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason != "tool_use":
                # pause_turn or unexpected — just stop
                break

            # Execute every tool call and collect results
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                if self.verbose:
                    print(f"  [tool] {block.name}({json.dumps(block.input)[:120]})")

                result_text = _dispatch_tool(block.name, block.input)  # type: ignore[arg-type]

                if self.verbose:
                    preview = result_text[:200].replace("\n", " ")
                    print(f"         -> {preview}")

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        return final_text

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _print_response_summary(self, response: Any) -> None:
        text_blocks = [b for b in response.content if b.type == "text"]
        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        usage = response.usage
        print(
            f"[MonitorAgent] stop_reason={response.stop_reason} "
            f"text_blocks={len(text_blocks)} tool_calls={len(tool_blocks)} "
            f"in={usage.input_tokens} out={usage.output_tokens}"
        )
