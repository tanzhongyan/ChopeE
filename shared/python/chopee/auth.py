"""Cognito access-token verification against the pool JWKS (plan 06 Section 5.2)."""
from __future__ import annotations

import json
import time
import urllib.request

import jwt

JWKS_TTL_SECONDS = 3600


class AuthError(Exception):
    pass


class JwtVerifier:
    """Verifies signature, iss, exp, token_use == "access" and client_id.

    ``jwks`` may be injected (tests use a fixture); otherwise it is fetched from the
    pool's well-known URL and cached.
    """

    def __init__(self, region: str, user_pool_id: str, client_id: str, jwks: dict | None = None):
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.client_id = client_id
        self._jwks = jwks
        self._fetched_at = time.time() if jwks else 0.0

    def _keys(self) -> dict:
        if self._jwks is None or (self._fetched_at and time.time() - self._fetched_at > JWKS_TTL_SECONDS):
            with urllib.request.urlopen(f"{self.issuer}/.well-known/jwks.json", timeout=3) as resp:
                self._jwks = json.load(resp)
            self._fetched_at = time.time()
        return {k["kid"]: k for k in self._jwks["keys"]}

    def verify(self, token: str) -> dict:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            jwk = self._keys().get(kid)
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
