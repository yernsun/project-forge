from app.events.models import EventEnvelope


def test_event_envelope_serializes_camel_case() -> None:
    envelope = EventEnvelope.new("example.created", {"itemId": "42"})
    payload = envelope.model_dump(by_alias=True, mode="json")
    assert payload["eventType"] == "example.created"
    assert payload["schemaVersion"] == 1
    assert "event_type" not in payload
