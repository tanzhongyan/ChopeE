"""Cognito access-token verification against the pool JWKS (plan 06 Section 5.2, plan 05b SEC-1)."""
from __future__ import annotations

import json
import time
import urllib.request

import jwt

JWKS_TTL_SECONDS = 3600
JWKS_MIN_REFRESH_SECONDS = 60  # unknown-kid refetches are rate-limited to this


class AuthError(Exception):
    pass


class JwtVerifier:
    """Verifies signature, iss, exp, token_use == "access" and client_id.

    ``jwks`` may be injected (tests use a fixture); otherwise it is fetched from the
    pool's well-known URL and cached. The cache is fail-static: a failed refresh keeps
    serving the last good keys. An unknown ``kid`` forces one rate-limited refresh so
    Cognito key rotation is picked up before the TTL expires.
    """

    def __init__(self, region: str, user_pool_id: str, client_id: str, jwks: dict | None = None,
                 clock=time.time):
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.client_id = client_id
        self._clock = clock
        self._jwks = jwks
        self._fetched_at = clock() if jwks else 0.0
        self._attempted_at = self._fetched_at

    def _fetch(self) -> dict:
        with urllib.request.urlopen(f"{self.issuer}/.well-known/jwks.json", timeout=3) as resp:
            return json.load(resp)

    def _refresh(self) -> None:
        self._attempted_at = self._clock()
        try:
            jwks = self._fetch()
            if not {k["kid"] for k in jwks["keys"]}:
                raise ValueError("empty key set")
        except Exception as exc:  # network, throttling, bad JSON
            if self._jwks is None:
                raise AuthError(f"jwks unavailable: {exc}") from exc
            return  # fail-static: keep the cached keys
        self._jwks, self._fetched_at = jwks, self._attempted_at

    def _keys(self, kid: str | None = None) -> dict:
        now = self._clock()
        expired = self._jwks is None or now - self._fetched_at > JWKS_TTL_SECONDS
        if expired and (self._jwks is None or now - self._attempted_at > JWKS_MIN_REFRESH_SECONDS):
            self._refresh()
        keys = {k["kid"]: k for k in self._jwks["keys"]}
        if kid not in keys and now - self._attempted_at > JWKS_MIN_REFRESH_SECONDS:
            self._refresh()
            keys = {k["kid"]: k for k in self._jwks["keys"]}
        return keys

    def verify(self, token: str) -> dict:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            jwk = self._keys(kid).get(kid)
            if jwk is None:
                raise AuthError("unknown signing key")
            key = jwt.PyJWK(jwk).key
            claims = jwt.decode(
                token, key, algorithms=["RS256"], issuer=self.issuer,
                options={"require": ["exp", "iss", "sub"], "verify_aud": False},
            )
        except AuthError:
            raise
        except Exception as exc:  # jwt errors, network errors
            raise AuthError(str(exc)) from exc
        if claims.get("token_use") != "access":
            raise AuthError("token_use must be access")
        if claims.get("client_id") != self.client_id:
            raise AuthError("client_id mismatch")
        return claims

    def subject(self, authorization: str | None) -> str:
        """Return ``sub`` from an ``Authorization: Bearer`` header value."""
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthError("missing bearer token")
        return self.verify(authorization[7:].strip())["sub"]
