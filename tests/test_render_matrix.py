from __future__ import annotations

import ast
import json
import py_compile
import re
from collections.abc import Iterator
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import pytest
import yaml

from project_forge.config import Locale, Profile, ProjectState, dump_state
from project_forge.renderer import render_fresh


class RenderedIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._inside_title = False
        self.title_parts: list[str] = []
        self.description: str | None = None
        self.scripts: list[dict[str, str | None]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "title":
            self._inside_title = True
        elif tag == "meta" and attributes.get("name") == "description":
            self.description = attributes.get("content")
        elif tag == "script":
            self.scripts.append(attributes)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._inside_title = False

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self.title_parts.append(data)


def valid_states() -> Iterator[ProjectState]:
    for profile in Profile:
        auth_values = (False,) if profile is Profile.FRONTEND else (False, True)
        event_values = (False,) if profile is Profile.FRONTEND else (False, True)
        for auth in auth_values:
            for evented in event_values:
                for sample in (False, True):
                    for locale in Locale:
                        yield ProjectState.create(
                            f"Fixture {profile.value} {auth} {evented} {sample} {locale.value}",
                            profile=profile,
                            auth=auth,
                            evented=evented,
                            sample=sample,
                            default_locale=locale,
                        )


STATES = tuple(valid_states())


@pytest.mark.parametrize("state", STATES, ids=lambda state: state.project_slug)
def test_every_valid_combination_renders(state: ProjectState, tmp_path: Path) -> None:
    destination = tmp_path / "project"
    render_fresh(state, destination)
    assert (destination / "FAQ.md").is_file()
    assert (destination / "FAQ.zh-CN.md").is_file()
    assert (destination / "backend").exists() is state.has_backend
    assert (destination / "frontend").exists() is state.has_frontend
    assert (destination / "backend/src/app/auth").exists() is (state.has_backend and state.auth)
    for migration in ("auth.py", "auth_security.py"):
        assert (destination / "backend/src/app/db/migrations" / migration).exists() is (
            state.has_backend and state.auth
        )
    assert (destination / "backend/src/app/db/migrations/auth_items.py").exists() is (
        state.has_backend and state.auth and state.sample
    )
    assert (destination / "frontend/tests/auth.spec.ts").exists() is (
        state.has_frontend and state.auth
    )
    assert (destination / "backend/tests/test_auth_postgres.py").exists() is (
        state.has_backend and state.auth
    )
    assert (destination / "backend/src/app/events").exists() is (
        state.has_backend and state.evented
    )
    assert (destination / "backend/src/app/db/migrations/events.py").exists() is (
        state.has_backend and state.evented
    )
    assert (destination / "backend/src/app/db/migrations/event_idempotency.py").exists() is (
        state.has_backend and state.evented
    )
    assert (destination / "backend/src/app/db/migrations/event_reliability.py").exists() is (
        state.has_backend and state.evented
    )
    assert (destination / "backend/src/app/api/observability.py").exists() is state.has_backend
    assert (destination / "backend/src/app/domain/items.py").exists() is (
        state.has_backend and state.sample
    )
    assert (destination / "frontend/src/features/items").exists() is (
        state.has_frontend and state.sample
    )
    assert not (destination / ".project-forge").exists()
    for cache in ("node_modules", "dist", "coverage"):
        assert not (destination / "frontend" / cache).exists()

    development_environment = (destination / ".env.dev.example").read_text(encoding="utf-8")
    assert (
        "DEV_FRONTEND_BIND_HOST=127.0.0.1" in development_environment
    ) is state.has_frontend
    assert "\nDEV_FRONTEND_BIND_HOST=0.0.0.0\n" not in development_environment
    assert ("DEV_API_BIND_HOST=127.0.0.1" in development_environment) is state.has_backend
    assert "172.20.0.10" in development_environment
    assert "192.168." not in development_environment

    for compose_file in ("docker-compose.dev.yml", "docker-compose.yml"):
        document = yaml.safe_load((destination / compose_file).read_text(encoding="utf-8"))
        assert document["services"]
    if state.has_backend:
        production = yaml.safe_load(
            (destination / "docker-compose.yml").read_text(encoding="utf-8")
        )
        database_url = production["services"]["migrate"]["environment"]["DATABASE_URL"]
        assert database_url.startswith("${DATABASE_URL:?")
        assert "POSTGRES_PASSWORD" not in database_url
    workflow = yaml.safe_load(
        (destination / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    validate = workflow["jobs"]["validate"]
    assert validate["steps"]
    assert "security-audit" in workflow["jobs"]
    emits_production_smoke = state.profile is Profile.FULLSTACK and state.auth and state.sample
    assert ("production-compose-smoke" in workflow["jobs"]) is emits_production_smoke
    workflow_environment = validate.get("env", {})
    if state.profile is Profile.FRONTEND and state.sample:
        assert (
            workflow_environment["FRONTEND_API_UPSTREAM"]
            == "http://host.docker.internal:8000"
        )
    else:
        assert "FRONTEND_API_UPSTREAM" not in workflow_environment

    for path in destination.rglob("*.py"):
        ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
            feature_version=(3, 11),
        )
    if state.has_frontend:
        for locale_name in ("zh-CN.json", "en-US.json"):
            json.loads(
                (destination / "frontend/src/shared/i18n/locales" / locale_name).read_text(
                    encoding="utf-8"
                )
            )


@pytest.mark.parametrize(
    ("auth", "evented"),
    ((False, False), (True, False), (False, True)),
    ids=("core", "auth", "evented"),
)
def test_generated_dependency_commands_only_enable_selected_extras(
    auth: bool,
    evented: bool,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "project"
    render_fresh(
        ProjectState.create(
            "Profile Hygiene",
            profile=Profile.FULLSTACK,
            auth=auth,
            evented=evented,
            sample=False,
        ),
        destination,
    )

    for relative in ("backend/Dockerfile", "README.md", "README.zh-CN.md"):
        content = (destination / relative).read_text(encoding="utf-8")
        assert "--all-extras" not in content
        assert ("--extra auth" in content) is auth
        assert ("--extra evented" in content) is evented

    client = (destination / "frontend/src/shared/api/client.ts").read_text(encoding="utf-8")
    for auth_marker in ("CSRF", "X-CSRF-Token", "AUTH_UNAUTHORIZED"):
        assert (auth_marker in client) is auth
    assert ("openapi-fetch" in client) is auth


@pytest.mark.parametrize(
    ("profile", "auth", "evented", "sample"),
    (
        (Profile.FRONTEND, False, False, False),
        (Profile.FRONTEND, False, False, True),
        (Profile.BACKEND, False, False, True),
        (Profile.BACKEND, False, True, False),
        (Profile.FULLSTACK, True, False, True),
    ),
)
def test_generated_readmes_are_runnable_and_profile_specific(
    profile: Profile,
    auth: bool,
    evented: bool,
    sample: bool,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "project"
    state = ProjectState.create(
        "Documented Fixture",
        profile=profile,
        auth=auth,
        evented=evented,
        sample=sample,
    )
    render_fresh(state, destination)

    for relative in ("README.md", "README.zh-CN.md"):
        content = (destination / relative).read_text(encoding="utf-8")
        assert content.count("```") % 2 == 0
        assert "FAQ" in content
        assert "python harness/check.py" in content
        assert "project-forge update --check ." in content
        assert ("uv sync --frozen --all-groups" in content) is state.has_backend
        assert ("npm ci" in content) is state.has_frontend
        assert ("/api/v1/auth/signup" in content) is auth
        assert ("app auth purge-expired" in content) is auth
        assert ("app.events.worker relay" in content) is evented
        assert ("app config check --json" in content) is state.has_backend
        assert ("app events status --json" in content) is evented
        assert ("npm run test:coverage" in content) is state.has_frontend
        assert "172.20.0.10" in content
        assert "192.168." not in content
        assert ("FRONTEND_API_UPSTREAM" in content) is (
            profile is Profile.FRONTEND and sample
        )
        assert "{%" not in content
        assert "{{" not in content

    english_faq = (destination / "FAQ.md").read_text(encoding="utf-8")
    chinese_faq = (destination / "FAQ.zh-CN.md").read_text(encoding="utf-8")
    assert "[简体中文](FAQ.zh-CN.md)" in english_faq
    assert "[English](FAQ.md)" in chinese_faq
    for content in (english_faq, chinese_faq):
        assert content.count("```") % 2 == 0
        for marker in (
            "APP_ALLOWED_ORIGINS",
            "APP_SESSION_COOKIE_SECURE",
            "APP_AUTH_RATE_LIMIT_SECRET",
            "FORWARDED_ALLOW_IPS",
            "origin_not_allowed",
            "request_validation_failed",
            "workspaceName",
            "HARNESS_STRICT",
            "172.20.0.10",
            "X-Request-ID",
            "app config check --json",
        ):
            assert marker in content
        assert "192.168." not in content
        assert "{%" not in content
        assert "{{" not in content


def test_generated_projects_have_no_source_specific_residue(tmp_path: Path) -> None:
    destination = tmp_path / "project"
    render_fresh(
        ProjectState.create("Clean Fixture", auth=True, evented=True),
        destination,
    )
    forbidden = ("TradeComposer", "async" + "pg", "Statement")
    for path in destination.rglob("*"):
        if path.is_dir():
            assert path.name not in {".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        assert not any(token in text for token in forbidden), path


def test_project_name_is_escaped_for_python_html_vue_markdown_and_yaml(
    tmp_path: Path,
) -> None:
    project_name = 'Acme "Quoted" \\ </title><script>alert(1)</script> & <Lab>'
    state = ProjectState.create(
        project_name,
        project_slug="safe-display-name",
        profile=Profile.FULLSTACK,
        sample=False,
    )
    destination = tmp_path / "project"
    render_fresh(state, destination)

    main_path = destination / "backend/src/app/main.py"
    main_source = main_path.read_text(encoding="utf-8")
    py_compile.compile(
        str(main_path),
        cfile=str(tmp_path / "generated-main.pyc"),
        doraise=True,
    )
    module = ast.parse(main_source)
    fastapi_call = next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "FastAPI"
    )
    title = next(keyword.value for keyword in fastapi_call.keywords if keyword.arg == "title")
    assert ast.literal_eval(title) == f"{project_name} API"

    index = (destination / "frontend/index.html").read_text(encoding="utf-8")
    parser = RenderedIndexParser()
    parser.feed(index)
    assert "".join(parser.title_parts) == project_name
    assert parser.description == project_name
    assert parser.scripts == [{"type": "module", "src": "/src/main.ts"}]
    assert "</title><script>alert(1)</script>" not in index

    app_source = (destination / "frontend/src/app/App.vue").read_text(encoding="utf-8")
    eyebrow = re.search(r'<p class="eyebrow">(.*?)</p>', app_source)
    assert eyebrow is not None
    assert unescape(eyebrow.group(1)) == project_name
    assert "<script>alert(1)</script>" not in eyebrow.group(1)

    for relative, suffix in (
        ("README.md", ""),
        ("README.zh-CN.md", ""),
        ("AGENTS.md", " Agent Guide"),
    ):
        heading = (destination / relative).read_text(encoding="utf-8").splitlines()[0]
        visible_name = unescape(heading.removeprefix("# ").removesuffix(suffix))
        assert visible_name == project_name
        assert "<script>alert(1)</script>" not in heading

    assert yaml.safe_load(dump_state(state))["project_name"] == project_name
