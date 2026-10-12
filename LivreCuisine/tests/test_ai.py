import json

import anthropic
import httpx2 as httpx
import pytest

from livrecuisine import ai

RECIPE = {"is_recipe": True, "title": "Tarte aux pommes", "category": "Dessert",
          "servings": "6 parts", "prep_time": "20 min", "cook_time": "35 min",
          "ingredients": [{"group": "", "items": ["4 pommes"]}, {"group": "Vide", "items": []}],
          "steps": ["Étale la pâte."], "tips": "", "tags": ["#Pommes", " "]}


def fake_client(monkeypatch, status=200, body=None, stop_reason="end_turn"):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        if status != 200:
            return httpx.Response(status, json={"type": "error", "error": {
                "type": "authentication_error", "message": "invalid x-api-key"}})
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": ai.MODEL,
            "content": [{"type": "text", "text": json.dumps(body or RECIPE)}],
            "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 300}})

    def make(key):
        return anthropic.Anthropic(api_key=key, max_retries=0,
                                   http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(ai, "_client", make)
    return seen


def test_structure_request_and_cleanup(monkeypatch):
    seen = fake_client(monkeypatch)
    out = ai.structure("sk-test", "Tarte\n4 pommes", "on coupe les pommes", [b"\xff\xd8jpeg"],
                       "mamie")
    body = seen["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in seen["headers"]["anthropic-beta"]
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in body
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    text = content[-1]["text"]
    assert "@mamie" in text and "on coupe les pommes" in text and "4 pommes" in text

    assert out["title"] == "Tarte aux pommes"
    assert out["ingredients"] == [{"group": "", "items": ["4 pommes"]}]  # groupe vide retiré
    assert out["tags"] == ["pommes"]


def test_refusal_and_bad_key(monkeypatch):
    fake_client(monkeypatch, stop_reason="refusal")
    with pytest.raises(ai.AIError):
        ai.structure("sk", "x")
    fake_client(monkeypatch, status=401)
    with pytest.raises(ai.AIError, match="Clé"):
        ai.structure("sk", "x")


def test_schema_is_strict():
    assert ai.SCHEMA["additionalProperties"] is False
    assert set(ai.SCHEMA["required"]) == set(ai.SCHEMA["properties"])
