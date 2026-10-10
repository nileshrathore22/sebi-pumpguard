import httpx
import pytest

from app.core.config import Settings
from app.core.constants import DISCLAIMER
from app.explain.graph import explain
from app.explain.grounding import check_grounding
from app.explain.llm import FakeLLMClient, OpenAICompatibleClient, get_llm_client
from app.explain.payload import build_payload
from app.explain.templates import template_explanation


@pytest.fixture
def payload():  # type: ignore[no-untyped-def]
    return build_payload(
        symbol="SYNTH_09",
        as_of_date="2023-06-12",
        score=99.874,
        threshold=97.05,
        model_version="iforest-pooled-v1",
        top_features=[
            {"feature": "vol_z20", "value": 4.2311, "robust_z": 6.04},
            {"feature": "ret_5d", "value": 0.1834, "robust_z": 5.51},
            {"feature": "consec_up_days", "value": 5.0, "robust_z": 3.2},
        ],
    )


def test_payload_is_pre_rounded(payload) -> None:  # type: ignore[no-untyped-def]
    assert payload["score"] == 99.9
    assert payload["flagged"] is True
    assert payload["top_features"][1]["value"] == 18.3  # percent


def test_template_passes_grounding(payload) -> None:  # type: ignore[no-untyped-def]
    text = template_explanation(payload)
    assert check_grounding(text, payload).ok, check_grounding(text, payload).problems
    below = payload | {"flagged": False, "score": 40.0}
    assert check_grounding(template_explanation(below), below).ok


def test_no_llm_uses_fallback(payload) -> None:  # type: ignore[no-untyped-def]
    out = explain(payload, None)
    assert out["path"] == "fallback"
    assert out["explanation"].endswith(DISCLAIMER)


def test_grounded_llm_text_accepted(payload) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLMClient(
        "On 2023-06-12 SYNTH_09 scored 99.9, above the threshold of 97. "
        "Volume was 4.2 standard deviations above normal and the price rose 18.3% over 5 days."
    )
    out = explain(payload, llm)
    assert out["path"] == "llm", out["problems"]
    assert llm.calls == 1
    assert DISCLAIMER in out["explanation"]


def test_hallucinated_number_rejected(payload) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLMClient("SYNTH_09 scored 99.9 and its price jumped 45% in a week.")
    out = explain(payload, llm)
    assert out["path"] == "fallback"
    assert any("45" in p for p in out["problems"])


def test_hallucinated_date_rejected(payload) -> None:  # type: ignore[no-untyped-def]
    res = check_grounding("SYNTH_09 was flagged on 2023-06-15.", payload)
    assert not res.ok and "2023-06-15" in res.problems[0]


@pytest.mark.parametrize("word", ["manipulation", "Fraudulent", "guaranteed"])
def test_banned_terms_rejected(payload, word: str) -> None:  # type: ignore[no-untyped-def]
    out = explain(payload, FakeLLMClient(f"This looks like {word} activity in SYNTH_09."))
    assert out["path"] == "fallback"
    assert any("banned" in p for p in out["problems"])


def test_llm_error_falls_back(payload) -> None:  # type: ignore[no-untyped-def]
    def boom(_: str) -> str:
        raise TimeoutError("provider down")

    out = explain(payload, FakeLLMClient(boom))
    assert out["path"] == "fallback" and "provider down" in out["problems"][0]


def test_symbol_digits_not_treated_as_numbers(payload) -> None:  # type: ignore[no-untyped-def]
    assert check_grounding("SYNTH_09 has a score of 99.9.", payload).ok
    assert not check_grounding("", payload).ok


def test_missing_payload_keys() -> None:
    with pytest.raises(ValueError):
        explain({"symbol": "X"}, None)


def test_llm_client_factory() -> None:
    assert get_llm_client(Settings(llm_provider="none")) is None
    assert get_llm_client(Settings(llm_provider="openai", llm_api_key="")) is None
    client = get_llm_client(Settings(llm_provider="openai", llm_api_key="k"))
    assert isinstance(client, OpenAICompatibleClient)


def test_openai_client_parses_response(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_post(url: str, **kw: object) -> httpx.Response:
        assert url.endswith("/chat/completions")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": " hi "}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    assert OpenAICompatibleClient("k", "m", "https://x/v1").complete("s", "u") == "hi"
