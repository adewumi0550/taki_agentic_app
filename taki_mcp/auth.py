"""Mint a Google identity token for calling a private Cloud Run service.

Two paths, chosen automatically:
  * On Cloud Run: the metadata server signs a token for this service's own
    service account, scoped to the audience (the target service URL). No
    credentials in env, nothing to rotate.
  * Locally: fall back to `gcloud auth print-identity-token` (your user creds).

Tokens are cached and refreshed a few minutes before expiry.
"""
from __future__ import annotations

import subprocess
import time

import httpx

_METADATA = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/identity"
)
_cache: dict[str, tuple[str, float]] = {}
_TTL_S = 50 * 60  # Google ID tokens live 60 min


def identity_token(audience: str) -> str:
    now = time.time()
    hit = _cache.get(audience)
    if hit and hit[1] > now:
        return hit[0]

    token = _from_metadata(audience) or _from_gcloud()
    if not token:
        raise RuntimeError(
            "Could not mint an identity token: not on Cloud Run and gcloud is "
            "not logged in. Run `gcloud auth login`."
        )
    _cache[audience] = (token, now + _TTL_S)
    return token


def _from_metadata(audience: str) -> str | None:
    try:
        r = httpx.get(_METADATA, params={"audience": audience, "format": "full"},
                      headers={"Metadata-Flavor": "Google"}, timeout=2.0)
        return r.text.strip() if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def _from_gcloud() -> str | None:
    try:
        out = subprocess.run(["gcloud", "auth", "print-identity-token"],
                             capture_output=True, text=True, check=True, timeout=30)
        return out.stdout.strip() or None
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
