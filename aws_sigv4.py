"""AWS Signature Version 4 (SigV4) request signing -- implemented from
scratch per docs.aws.amazon.com/IAM/latest/UserGuide/reference_sigv-
create-signed-request.html (read 2026-08-24), because no AWS SDK (boto3)
is available inside the extension runtime (confirmed: no httpx/requests/
boto3 anywhere in Apps/*, every *_client.py builds requests directly over
ctx.http).

WHY THIS IS DIFFERENT FROM EVERY OTHER *_client.py IN THE PORTFOLIO.

Every other BYOK connector (GitLab, n8n, MuleSoft, Home Assistant, ...)
authenticates with a single static header value (a Bearer token or a
custom header like PRIVATE-TOKEN) -- the header value never changes
between requests. AWS SigV4 instead derives a NEW signature for every
single request, from: the HTTP method, canonical URI, canonical query
string, canonical headers (including a mandatory x-amz-date and, for most
services, a payload hash), the caller's Access Key ID + Secret Access
Key, the target region, and the target service name. Get any one of
these wrong and AWS returns 403 SignatureDoesNotMatch -- there is no
partial credit.

The algorithm (exactly as AWS documents it, four steps):
1. Canonical request: HTTPMethod + '\\n' + CanonicalURI + '\\n' +
   CanonicalQueryString + '\\n' + CanonicalHeaders + '\\n' +
   SignedHeaders + '\\n' + HashedPayload.
2. String to sign: 'AWS4-HMAC-SHA256' + '\\n' + amz-date + '\\n' +
   credential-scope + '\\n' + hash(canonical request).
3. Signing key: derived by HMAC-chaining the secret key through the
   date, region, service, and the literal 'aws4_request'.
4. Signature: HMAC-SHA256(signing key, string to sign), hex-encoded.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import urllib.parse

ALGORITHM = "AWS4-HMAC-SHA256"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _hmac(f"AWS4{secret_key}".encode("utf-8"), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    return _hmac(k_service, "aws4_request")


def _canonical_query_string(params: dict) -> str:
    if not params:
        return ""
    encoded = []
    for key in sorted(params.keys()):
        value = params[key]
        if value is None:
            continue
        encoded.append((
            urllib.parse.quote(str(key), safe="-_.~"),
            urllib.parse.quote(str(value), safe="-_.~"),
        ))
    encoded.sort()
    return "&".join(f"{k}={v}" for k, v in encoded)


def _canonical_uri(path: str) -> str:
    if not path:
        return "/"
    segments = path.split("/")
    encoded = [urllib.parse.quote(seg, safe="-_.~") for seg in segments]
    return "/".join(encoded) or "/"


def sign_request(
    *,
    method: str,
    url_path: str,
    query_params: dict | None,
    headers: dict,
    body: bytes,
    access_key_id: str,
    secret_access_key: str,
    session_token: str | None,
    region: str,
    service: str,
    now: _dt.datetime | None = None,
) -> dict:
    """Return the full header set (including Authorization) to attach to
    an HTTP request for it to be accepted as a validly signed AWS SigV4
    request. Caller supplies the already-built (unsigned) headers dict
    (must include 'Host'); this function adds x-amz-date, x-amz-content-
    sha256, x-amz-security-token (if a session token is present) and
    Authorization, then returns the merged dict ready to send."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    payload_hash = _sha256_hex(body or b"")

    signed_headers = dict(headers)
    signed_headers["x-amz-date"] = amz_date
    signed_headers["x-amz-content-sha256"] = payload_hash
    if session_token:
        signed_headers["x-amz-security-token"] = session_token

    header_names = sorted(k.lower() for k in signed_headers.keys())
    canonical_headers = "".join(
        f"{name}:{signed_headers[_find_key(signed_headers, name)].strip()}\n"
        for name in header_names
    )
    signed_headers_str = ";".join(header_names)

    canonical_request = "\n".join([
        method.upper(),
        _canonical_uri(url_path),
        _canonical_query_string(query_params or {}),
        canonical_headers,
        signed_headers_str,
        payload_hash,
    ])

    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        ALGORITHM,
        amz_date,
        credential_scope,
        _sha256_hex(canonical_request.encode("utf-8")),
    ])

    key = _signing_key(secret_access_key, date_stamp, region, service)
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"{ALGORITHM} Credential={access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers_str}, Signature={signature}"
    )
    signed_headers["Authorization"] = authorization
    return signed_headers


def _find_key(d: dict, lower_name: str) -> str:
    for k in d.keys():
        if k.lower() == lower_name:
            return k
    raise KeyError(lower_name)
