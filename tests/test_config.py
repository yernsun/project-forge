import pytest
from pydantic import ValidationError

from project_forge.config import Locale, Profile, ProjectState, slugify


def test_noninteractive_defaults_are_fullstack_zh_cn_with_sample() -> None:
    state = ProjectState.create("My App")
    assert state.profile is Profile.FULLSTACK
    assert state.default_locale is Locale.ZH_CN
    assert state.sample is True
    assert state.auth is False
    assert state.evented is False
    assert state.project_slug == "my-app"


@pytest.mark.parametrize("feature", ["auth", "evented"])
def test_backend_features_are_invalid_for_frontend_only(feature: str) -> None:
    values = {feature: True}
    with pytest.raises(ValidationError, match="requires a backend"):
        ProjectState.create("UI", profile=Profile.FRONTEND, **values)  # type: ignore[arg-type]


def test_slug_rejects_names_without_ascii_identity() -> None:
    with pytest.raises(ValueError):
        slugify("工程")


def test_explicit_slug_supports_non_ascii_display_name() -> None:
    state = ProjectState.create("订单服务", project_slug="order-service")
    assert state.project_name == "订单服务"
    assert state.project_slug == "order-service"
