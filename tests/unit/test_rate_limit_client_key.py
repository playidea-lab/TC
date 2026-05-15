"""client_rate_key — contributor_id / IP / X-Forwarded-For 우선순위 검증."""

from unittest.mock import MagicMock

from the_commons.api.rate_limit import client_rate_key
from the_commons.auth.jwt_verify import VerifiedClaims


def _mock_request(*, host: str = "127.0.0.1", xff: str | None = None) -> MagicMock:
    request = MagicMock()
    request.client.host = host
    request.headers = {"X-Forwarded-For": xff} if xff else {}
    return request


def _anonymous_claims() -> VerifiedClaims:
    return VerifiedClaims(
        contributor_id="",  # type: ignore[arg-type] — anonymous fall-back
        issuer="cq.pilab.kr",
        audience="the-commons",
        raw_claims={"sub": "x"},
    )


def _named_claims(name: str = "user-abc") -> VerifiedClaims:
    return VerifiedClaims(
        contributor_id=name,
        issuer="cq.pilab.kr",
        audience="the-commons",
        raw_claims={"sub": name},
    )


def test_contributor_id_takes_priority_when_present() -> None:
    """contributor_id가 있으면 IP 무관하게 contrib: 키."""
    request = _mock_request(host="10.0.0.1", xff="1.2.3.4")
    key = client_rate_key(request, _named_claims("user-x"))
    assert key == "contrib:user-x"


def test_falls_back_to_client_host_when_anonymous(monkeypatch) -> None:
    """contributor_id 비어있고 trust_forwarded_for=False면 client.host 사용."""
    from the_commons.settings import settings

    monkeypatch.setattr(settings, "trust_forwarded_for", False)
    request = _mock_request(host="192.168.1.10", xff="1.2.3.4")  # XFF 무시
    key = client_rate_key(request, _anonymous_claims())
    assert key == "ip:192.168.1.10"


def test_uses_forwarded_for_when_trusted(monkeypatch) -> None:
    """trust_forwarded_for=True면 X-Forwarded-For 첫 IP 사용."""
    from the_commons.settings import settings

    monkeypatch.setattr(settings, "trust_forwarded_for", True)
    request = _mock_request(host="10.0.0.1", xff="203.0.113.5, 10.0.0.1")
    key = client_rate_key(request, _anonymous_claims())
    assert key == "ip:203.0.113.5"


def test_falls_back_to_host_when_trusted_but_no_xff(monkeypatch) -> None:
    """trust_forwarded_for=True인데 XFF 없으면 host fallback."""
    from the_commons.settings import settings

    monkeypatch.setattr(settings, "trust_forwarded_for", True)
    request = _mock_request(host="192.168.1.20", xff=None)
    key = client_rate_key(request, _anonymous_claims())
    assert key == "ip:192.168.1.20"
