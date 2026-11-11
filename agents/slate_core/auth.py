"""Authentication for the API: verify a bearer token, return the verified user.

Exactly one provider is active per server:

- GoogleAuth: verifies Google ID tokens locally with the google-auth library
  (signature against Google's published certs, issuer, audience = OUR OAuth
  client id, expiry). Stateless on purpose: no session store, so there is no
  server-side session to hijack or fix. The user id is the token's `sub`
  claim, never anything the client sends.
- SupabaseAuth: managed variant - asks Supabase Auth who a token belongs to
  (GET /auth/v1/user). Same guarantee: identity comes from the provider's
  response, not from the request.
- DevAuth: local development and tests only. Accepts "dev:<email>" tokens so
  the app runs without any external account. The app factory refuses DevAuth
  whenever a real provider is configured, so a misconfigured deployment cannot
  silently fall into it.

Hard rules baked in here:
- a user id is NEVER taken from a request parameter or body; it only ever
  comes out of a verified token;
- token verification failures are indistinguishable to the caller (one
  invalid_token error) so probing learns nothing;
- logout/expiry semantics are honest: Google ID tokens live until they expire
  (~1h, Google's clock), and a stateless server cannot revoke them early.
  Sign-out clears the client copy; a stolen token works until expiry. That is
  the documented tradeoff of the stateless design.
"""
import hashlib
import json
import urllib.request


class AuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class User:
    def __init__(self, uid: str, email: str):
        self.id, self.email = uid, email


def _bearer(header) -> str:
    if not header:
        raise AuthError("unauthenticated", "Sign in first: this call needs an Authorization header.")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("unauthenticated", 'Expected "Authorization: Bearer <token>".')
    token = token.strip()
    if len(token) > 8192:  # abuse cap; real ID tokens are ~1 KB
        raise AuthError("invalid_token", "Token rejected.")
    return token


class DevAuth:
    """Explicit local-dev identity. Tokens look like "dev:asha@example.com".

    Only ever active when no real provider is configured (the app factory
    enforces this). Exists so local runs and tests need no external accounts.
    """

    def authenticate(self, header) -> User:
        token = _bearer(header)
        if not token.startswith("dev:") or len(token) <= 4:
            raise AuthError("unauthenticated", "Dev sign-in expects a dev:<email> token from the login box.")
        email = token[4:].strip().lower()
        uid = "dev-" + hashlib.sha256(email.encode()).hexdigest()[:16]
        return User(uid, email)


class GoogleAuth:
    """Verifies Google ID tokens with google-auth: signature, issuer, audience
    (our OAuth client id) and expiry are all checked by the library.

    verifier is injectable so tests never touch the network: it receives
    (token, expected_audience) and returns the decoded claims or raises."""

    def __init__(self, client_id: str, verifier=None):
        if not client_id:
            raise ValueError("GoogleAuth needs the OAuth client id (the token audience).")
        self._client_id = client_id
        self._verifier = verifier

    def _verify(self, token: str) -> dict:
        if self._verifier is not None:
            return self._verifier(token, self._client_id)
        from google.oauth2 import id_token  # lazy: only Google mode needs google-auth installed
        from google.auth.transport import requests as grequests
        return id_token.verify_oauth2_token(token, grequests.Request(), self._client_id)

    def authenticate(self, header) -> User:
        token = _bearer(header)
        try:
            claims = self._verify(token)
        except Exception:
            raise AuthError("invalid_token",
                            "Google sign-in token was rejected (bad signature, audience, issuer, or expired).")
        sub = claims.get("sub")
        if not sub:
            raise AuthError("invalid_token", "Google token carried no subject.")
        return User("g-" + sub, claims.get("email", ""))


class SupabaseAuth:
    """Managed variant: Supabase Auth decides who a token belongs to.

    The token is verified by calling Supabase's own user endpoint; we never
    decode or trust the token locally. No caching on our side: every API call
    re-asks Supabase, so we add no staleness of our own (when Supabase itself
    invalidates a token is Supabase's behavior, not something we guarantee).
    opener is injectable for tests (no network in tests)."""

    def __init__(self, url: str, api_key: str, opener=None):
        if not url or not api_key:
            raise ValueError("SupabaseAuth needs the project URL and anon key.")
        self._url = url.rstrip("/")
        self._key = api_key
        self._opener = opener

    def _fetch_user(self, token: str) -> dict:
        if self._opener is not None:
            return self._opener(self._url, self._key, token)
        req = urllib.request.Request(
            self._url + "/auth/v1/user",
            headers={"Authorization": "Bearer " + token, "apikey": self._key,
                     "User-Agent": "slate-api/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def authenticate(self, header) -> User:
        token = _bearer(header)
        try:
            body = self._fetch_user(token)
        except Exception:
            raise AuthError("invalid_token", "Sign-in token was rejected by the auth service.")
        uid = body.get("id")
        if not uid:
            raise AuthError("invalid_token", "Auth service returned no user.")
        return User("sb-" + uid, body.get("email", ""))
