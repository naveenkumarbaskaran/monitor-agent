"""AppAnalyzer: static heuristics to detect app components from source."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class AppProfile:
    """Detected components of an application."""

    endpoints: list[str] = field(default_factory=list)
    db_connections: list[str] = field(default_factory=list)
    queues: list[str] = field(default_factory=list)
    external_deps: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=== Application Profile ===",
            f"Languages  : {', '.join(self.languages) or 'unknown'}",
            f"Frameworks : {', '.join(self.frameworks) or 'none detected'}",
            f"Endpoints  : {', '.join(self.endpoints[:10]) or 'none detected'}",
            f"Databases  : {', '.join(self.db_connections) or 'none detected'}",
            f"Queues     : {', '.join(self.queues) or 'none detected'}",
            f"Ext. deps  : {', '.join(self.external_deps[:10]) or 'none detected'}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pattern libraries
# ---------------------------------------------------------------------------

# (display_name, list_of_regex_patterns)
_FRAMEWORK_PATTERNS: list[tuple[str, list[str]]] = [
    # Python
    ("FastAPI", [r"from fastapi", r"import fastapi", r"FastAPI\("]),
    ("Flask", [r"from flask", r"import flask", r"Flask\("]),
    ("Django", [r"from django", r"import django", r"django\.conf"]),
    ("Tornado", [r"import tornado"]),
    ("Starlette", [r"from starlette"]),
    ("aiohttp", [r"from aiohttp", r"import aiohttp"]),
    # JavaScript / TypeScript
    ("Express", [r"require\(['\"']express['\"']\)", r"from ['\"']express['\"']"]),
    ("NestJS", [r"@Module\(", r"from '@nestjs"]),
    ("Koa", [r"require\(['\"']koa['\"']\)", r"from ['\"']koa['\"']"]),
    ("Hapi", [r"require\(['\"']@hapi"]),
    # Java / Kotlin
    ("Spring", [r"@RestController", r"@SpringBootApplication", r"import org\.springframework"]),
    ("Quarkus", [r"import io\.quarkus"]),
    # Go
    ("Gin", [r'"github\.com/gin-gonic/gin"']),
    ("Echo", [r'"github\.com/labstack/echo"']),
    ("Chi", [r'"github\.com/go-chi/chi"']),
    # Ruby
    ("Rails", [r"Rails\.application", r"ActionController"]),
    ("Sinatra", [r"require ['\"']sinatra['\"']"]),
    # PHP
    ("Laravel", [r"use Illuminate\\\\", r"Artisan::"]),
    ("Symfony", [r"use Symfony\\\\"]),
    # Rust
    ("Actix", [r"use actix_web", r"actix_web::"]),
    ("Axum", [r"use axum", r"axum::"]),
]

_DB_PATTERNS: list[tuple[str, list[str]]] = [
    ("PostgreSQL", [r"postgres", r"psycopg2", r"asyncpg", r"pg\.Pool", r"DATABASE_URL.*postgres"]),
    ("MySQL", [r"mysql", r"pymysql", r"aiomysql", r"mysql2"]),
    ("MongoDB", [r"mongodb", r"pymongo", r"mongoose", r"MongoClient"]),
    ("Redis", [r"redis", r"aioredis", r"ioredis", r"REDIS_URL"]),
    ("SQLite", [r"sqlite3", r"sqlite"]),
    ("Cassandra", [r"cassandra", r"datastax"]),
    ("Elasticsearch", [r"elasticsearch", r"Elasticsearch\("]),
    ("DynamoDB", [r"dynamodb", r"DynamoDB"]),
]

_QUEUE_PATTERNS: list[tuple[str, list[str]]] = [
    ("RabbitMQ", [r"rabbitmq", r"pika", r"amqplib", r"amqp://"]),
    ("Kafka", [r"kafka", r"confluent_kafka", r"kafkajs", r"KafkaProducer", r"KafkaConsumer"]),
    ("SQS", [r"sqs", r"boto3.*sqs", r"aws-sdk.*sqs", r"SQSClient"]),
    ("Celery", [r"from celery", r"import celery", r"@app\.task"]),
    ("BullMQ", [r"bullmq", r"bull"]),
    ("NATS", [r"nats", r"nats\.connect"]),
    ("Pulsar", [r"pulsar", r"PulsarClient"]),
]

_ENDPOINT_PATTERNS: list[tuple[str, str]] = [
    # (framework_hint, regex capturing the path)
    ("FastAPI/Flask", r'@(?:app|router)\.(?:get|post|put|patch|delete|options)\(["\']([^"\']+)["\']'),
    ("Express", r'(?:app|router)\.(?:get|post|put|patch|delete)\s*\(["\']([^"\']+)["\']'),
    ("Spring", r'@(?:GetMapping|PostMapping|PutMapping|DeleteMapping|RequestMapping)\s*\(["\']([^"\']+)["\']'),
    ("Rails", r'(?:get|post|put|patch|delete)\s+["\']([^"\']+)["\']'),
    ("Gin/Echo", r'\.(?:GET|POST|PUT|PATCH|DELETE)\s*\(["\`]([^"\`]+)["\`]'),
]

_EXTERNAL_PATTERNS: list[tuple[str, list[str]]] = [
    ("Stripe", [r"stripe", r"STRIPE_"]),
    ("Twilio", [r"twilio"]),
    ("SendGrid", [r"sendgrid"]),
    ("AWS S3", [r"s3\.amazonaws\.com", r"S3Client", r"boto3.*s3"]),
    ("AWS Lambda", [r"lambda\.amazonaws\.com", r"LambdaClient"]),
    ("GCP", [r"googleapis\.com", r"google-cloud"]),
    ("Auth0", [r"auth0", r"AUTH0_"]),
    ("Sentry", [r"sentry", r"SENTRY_DSN"]),
    ("Datadog", [r"datadog", r"DD_API_KEY"]),
    ("OpenAI", [r"openai", r"OPENAI_API_KEY"]),
    ("Anthropic", [r"anthropic", r"ANTHROPIC_API_KEY"]),
    ("Slack", [r"slack_sdk", r"SlackClient", r"SLACK_TOKEN"]),
    ("GitHub", [r"github\.com/[a-z]", r"GITHUB_TOKEN", r"PyGithub"]),
]

_LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".jsx": "JavaScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".go": "Go",
    ".rb": "Ruby",
    ".php": "PHP",
    ".rs": "Rust",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
}

_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".next",
    "target", "vendor",
}


# ---------------------------------------------------------------------------
# AppAnalyzer
# ---------------------------------------------------------------------------

class AppAnalyzer:
    """Static heuristic analyser — no LLM calls."""

    def __init__(self, src: str) -> None:
        self.src = Path(src).resolve()

    def analyse(self) -> AppProfile:
        """Walk the source tree and return an AppProfile."""
        profile = AppProfile()
        lang_counts: dict[str, int] = {}
        all_content_lines: list[str] = []

        for path in self._iter_files():
            ext = path.suffix.lower()
            lang = _LANGUAGE_EXTENSIONS.get(ext)
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1

            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue

            lines = text.splitlines()
            all_content_lines.extend(lines)

            # Endpoints
            for _hint, pat in _ENDPOINT_PATTERNS:
                for m in re.finditer(pat, text, re.IGNORECASE):
                    ep = m.group(1)
                    if ep not in profile.endpoints:
                        profile.endpoints.append(ep)

        # Determine primary languages (top 3 by file count)
        profile.languages = [
            lang
            for lang, _ in sorted(lang_counts.items(), key=lambda x: -x[1])[:3]
        ]

        joined = "\n".join(all_content_lines)

        # Frameworks
        for name, patterns in _FRAMEWORK_PATTERNS:
            if self._any_match(joined, patterns) and name not in profile.frameworks:
                profile.frameworks.append(name)

        # Databases
        for name, patterns in _DB_PATTERNS:
            if self._any_match(joined, patterns) and name not in profile.db_connections:
                profile.db_connections.append(name)

        # Queues
        for name, patterns in _QUEUE_PATTERNS:
            if self._any_match(joined, patterns) and name not in profile.queues:
                profile.queues.append(name)

        # External deps
        for name, patterns in _EXTERNAL_PATTERNS:
            if self._any_match(joined, patterns) and name not in profile.external_deps:
                profile.external_deps.append(name)

        return profile

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _iter_files(self):
        """Yield Path objects for all non-skipped files under src."""
        for p in sorted(self.src.rglob("*")):
            if p.is_file() and not any(
                part in _SKIP_DIRS for part in p.relative_to(self.src).parts
            ):
                yield p

    @staticmethod
    def _any_match(text: str, patterns: list[str]) -> bool:
        return any(re.search(pat, text, re.IGNORECASE) for pat in patterns)
