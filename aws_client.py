"""AWS REST/Query API client -- SigV4-signed requests over ctx.http.

WHY MULTIPLE SERVICE ENDPOINTS, NOT ONE BASE_URL.

Unlike every other BYOK connector in the portfolio (one base_url per
connection), AWS has a different host PER SERVICE PER REGION:
`https://<service>.<region>.amazonaws.com`. IAM and STS are the two
exceptions -- they are global services reachable at a fixed host
regardless of region (iam.amazonaws.com, sts.amazonaws.com).

WHY EACH SERVICE HAS ITS OWN REQUEST-BUILDING HELPER.

AWS services do not share one wire protocol:
- EC2 uses the "Query" protocol: form-encoded parameters in the query
  string (GET) with an Action= and Version= parameter, XML response.
- S3 uses REST: bucket/key are path segments, XML response.
- Lambda, Cost Explorer, IAM (though IAM is technically Query too) and
  most newer services use JSON request/response bodies.
This client exposes one thin per-service function set rather than a
single generic "call_aws" -- callers get typed, documented functions
(list_ec2_instances, list_s3_buckets, ...), same shape as every other
*_client.py in the portfolio (gitlab_client.list_pipelines, etc.).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from aws_sigv4 import sign_request

IAM_HOST = "iam.amazonaws.com"
STS_HOST = "sts.amazonaws.com"


class ProviderError(Exception):
    """Raised for any AWS API call that fails, carrying a status_code and
    a human-readable detail so handlers can distinguish SignatureDoesNotMatch
    (bad keys/clock skew) from UnauthorizedOperation/AccessDenied (keys ok,
    insufficient IAM policy) from anything else -- same principle as
    gitlab_client.ProviderError distinguishing 401 from 403."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"AWS API error {status_code}: {detail}")


def _service_host(service: str, region: str) -> str:
    if service in ("iam",):
        return IAM_HOST
    if service in ("sts",):
        return STS_HOST
    return f"{service}.{region}.amazonaws.com"


def _xml_error_detail(text: str) -> tuple[str, str]:
    """AWS Query/REST-XML services (EC2, S3) return XML error bodies with
    <Code> and <Message>. Returns (code, message), best-effort."""
    try:
        root = ET.fromstring(text)
        code_el = root.find(".//Code")
        msg_el = root.find(".//Message")
        return (
            code_el.text if code_el is not None else "",
            msg_el.text if msg_el is not None else "",
        )
    except Exception:
        return "", ""


def _json_error_detail(body) -> tuple[str, str]:
    if not isinstance(body, dict):
        return "", ""
    code = body.get("__type", "") or body.get("Code", "")
    if "#" in code:
        code = code.split("#")[-1]
    message = body.get("message") or body.get("Message") or ""
    return code, message


def _check_status(resp, action: str, json_protocol: bool):
    if resp.status_code in (200, 201, 202, 204):
        if not resp.text:
            return {}
        if json_protocol:
            try:
                return resp.json()
            except Exception:
                return {}
        return resp.text  # caller parses XML with the shape it expects

    if json_protocol:
        try:
            body = resp.json()
        except Exception:
            body = {}
        code, message = _json_error_detail(body)
    else:
        code, message = _xml_error_detail(resp.text or "")

    if resp.status_code in (401, 403) or code in (
        "SignatureDoesNotMatch", "InvalidClientTokenId", "AuthFailure",
        "UnauthorizedOperation", "AccessDenied", "AccessDeniedException",
    ):
        if code in ("SignatureDoesNotMatch",):
            raise ProviderError(
                403,
                f"AWS rejected the signature while trying to {action}: the "
                "Secret Access Key may be wrong, or your system clock is "
                "out of sync (SigV4 requests expire quickly).",
            )
        if code in ("InvalidClientTokenId", "AuthFailure"):
            raise ProviderError(
                401,
                f"AWS didn't recognise the Access Key ID while trying to "
                f"{action}: check the key hasn't been deleted or rotated.",
            )
        raise ProviderError(
            403,
            f"AWS recognised your credentials for {action}, but the "
            "attached IAM policy doesn't allow this action."
            + (f" ({code}: {message})" if message else ""),
        )
    if resp.status_code == 404:
        raise ProviderError(404, f"Not found while trying to {action}.")
    if resp.status_code == 429 or code == "Throttling":
        raise ProviderError(429, f"AWS throttled the request to {action}. Try again shortly.")
    if resp.status_code >= 500:
        raise ProviderError(resp.status_code, f"AWS's own service had a problem while trying to {action}.")
    raise ProviderError(
        resp.status_code,
        f"Unexpected response while trying to {action} (HTTP {resp.status_code})."
        + (f" {code}: {message}" if message else ""),
    )


async def _signed_request(
    ctx, *, method: str, service: str, region: str, path: str = "/",
    query_params: dict | None = None, json_body: dict | None = None,
    extra_headers: dict | None = None, access_key_id: str, secret_access_key: str,
    session_token: str | None = None, action_label: str,
):
    host = _service_host(service, region)
    json_protocol = json_body is not None or service in ("lambda", "ce", "logs", "monitoring")
    body_bytes = b""
    headers = {"Host": host}
    if json_body is not None:
        import json as _json
        body_bytes = _json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/x-amz-json-1.1"
    if extra_headers:
        headers.update(extra_headers)

    signed_headers = sign_request(
        method=method, url_path=path, query_params=query_params, headers=headers,
        body=body_bytes, access_key_id=access_key_id, secret_access_key=secret_access_key,
        session_token=session_token, region=region, service=service,
    )

    url = f"https://{host}{path}"
    if method.upper() == "GET":
        resp = await ctx.http.get(url, headers=signed_headers, params=query_params or {})
    else:
        resp = await ctx.http.post(url, headers=signed_headers, params=query_params or {}, content=body_bytes)
    return _check_status(resp, action_label, json_protocol)


async def check_connection(ctx, access_key_id: str, secret_access_key: str, region: str, session_token: str | None = None) -> dict:
    """sts:GetCallerIdentity -- the lightest possible call to verify a key
    pair is valid and discover the caller's ARN, without reading anything
    from the customer's actual infrastructure (per IDEAL_ONBOARDING §2.3)."""
    xml_text = await _signed_request(
        ctx, method="GET", service="sts", region=region,
        query_params={"Action": "GetCallerIdentity", "Version": "2011-06-15"},
        access_key_id=access_key_id, secret_access_key=secret_access_key,
        session_token=session_token, action_label="verify connection",
    )
    code, _ = "", ""
    try:
        root = ET.fromstring(xml_text)
        ns = {"s": "https://sts.amazonaws.com/doc/2011-06-15/"}
        result = root.find(".//s:GetCallerIdentityResult", ns) or root.find(".//GetCallerIdentityResult")
        if result is not None:
            return {
                "arn": (result.findtext("Arn") or result.findtext("s:Arn", namespaces=ns) or ""),
                "account": (result.findtext("Account") or result.findtext("s:Account", namespaces=ns) or ""),
                "user_id": (result.findtext("UserId") or result.findtext("s:UserId", namespaces=ns) or ""),
            }
    except Exception:
        pass
    return {"arn": "", "account": "", "user_id": ""}


# ──────────────────────────────────────────────────────────────────────────
# EC2 (Query protocol, XML response)
# ──────────────────────────────────────────────────────────────────────────

def _ec2_query(action: str, **params) -> dict:
    q = {"Action": action, "Version": "2016-11-15"}
    q.update({k: v for k, v in params.items() if v is not None and v != ""})
    return q


async def list_ec2_instances(ctx, creds: dict, region: str, state: str | None = None) -> str:
    params = _ec2_query("DescribeInstances")
    if state:
        params["Filter.1.Name"] = "instance-state-name"
        params["Filter.1.Value.1"] = state
    return await _signed_request(
        ctx, method="GET", service="ec2", region=region, query_params=params,
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="list EC2 instances",
    )


async def start_ec2_instance(ctx, creds: dict, region: str, instance_id: str) -> str:
    params = _ec2_query("StartInstances", **{"InstanceId.1": instance_id})
    return await _signed_request(
        ctx, method="GET", service="ec2", region=region, query_params=params,
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="start EC2 instance",
    )


async def stop_ec2_instance(ctx, creds: dict, region: str, instance_id: str) -> str:
    params = _ec2_query("StopInstances", **{"InstanceId.1": instance_id})
    return await _signed_request(
        ctx, method="GET", service="ec2", region=region, query_params=params,
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="stop EC2 instance",
    )


async def list_security_groups(ctx, creds: dict, region: str) -> str:
    params = _ec2_query("DescribeSecurityGroups")
    return await _signed_request(
        ctx, method="GET", service="ec2", region=region, query_params=params,
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="list security groups",
    )


async def list_volumes(ctx, creds: dict, region: str) -> str:
    params = _ec2_query("DescribeVolumes")
    return await _signed_request(
        ctx, method="GET", service="ec2", region=region, query_params=params,
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="list EBS volumes",
    )


# ──────────────────────────────────────────────────────────────────────────
# S3 (REST, XML response, path-style bucket/key addressing)
# ──────────────────────────────────────────────────────────────────────────

async def list_s3_buckets(ctx, creds: dict, region: str) -> str:
    return await _signed_request(
        ctx, method="GET", service="s3", region=region, path="/",
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="list S3 buckets",
    )


async def list_s3_objects(ctx, creds: dict, region: str, bucket: str, prefix: str = "") -> str:
    params = {"list-type": "2"}
    if prefix:
        params["prefix"] = prefix
    return await _signed_request(
        ctx, method="GET", service="s3", region=region, path=f"/{bucket}",
        query_params=params,
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="list S3 objects",
    )


# ──────────────────────────────────────────────────────────────────────────
# RDS (Query protocol, XML response)
# ──────────────────────────────────────────────────────────────────────────

async def list_rds_instances(ctx, creds: dict, region: str) -> str:
    params = {"Action": "DescribeDBInstances", "Version": "2014-10-31"}
    return await _signed_request(
        ctx, method="GET", service="rds", region=region, query_params=params,
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="list RDS instances",
    )


async def list_rds_snapshots(ctx, creds: dict, region: str) -> str:
    params = {"Action": "DescribeDBSnapshots", "Version": "2014-10-31"}
    return await _signed_request(
        ctx, method="GET", service="rds", region=region, query_params=params,
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="list RDS snapshots",
    )


# ──────────────────────────────────────────────────────────────────────────
# Lambda (REST, JSON response)
# ──────────────────────────────────────────────────────────────────────────

async def list_lambda_functions(ctx, creds: dict, region: str) -> dict:
    return await _signed_request(
        ctx, method="GET", service="lambda", region=region, path="/2015-03-31/functions/",
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="list Lambda functions",
    )


async def get_lambda_function(ctx, creds: dict, region: str, function_name: str) -> dict:
    return await _signed_request(
        ctx, method="GET", service="lambda", region=region,
        path=f"/2015-03-31/functions/{function_name}",
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="get Lambda function",
    )


async def invoke_lambda_function(ctx, creds: dict, region: str, function_name: str, payload: dict | None = None) -> dict:
    return await _signed_request(
        ctx, method="POST", service="lambda", region=region,
        path=f"/2015-03-31/functions/{function_name}/invocations",
        json_body=payload or {},
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="invoke Lambda function",
    )


# ──────────────────────────────────────────────────────────────────────────
# IAM (Query protocol, XML response, global service)
# ──────────────────────────────────────────────────────────────────────────

async def list_iam_users(ctx, creds: dict) -> str:
    params = {"Action": "ListUsers", "Version": "2010-05-08"}
    return await _signed_request(
        ctx, method="GET", service="iam", region="us-east-1", query_params=params,
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="list IAM users",
    )


async def list_iam_roles(ctx, creds: dict) -> str:
    params = {"Action": "ListRoles", "Version": "2010-05-08"}
    return await _signed_request(
        ctx, method="GET", service="iam", region="us-east-1", query_params=params,
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="list IAM roles",
    )


async def list_iam_policies(ctx, creds: dict, scope: str = "Local") -> str:
    params = {"Action": "ListPolicies", "Version": "2010-05-08", "Scope": scope}
    return await _signed_request(
        ctx, method="GET", service="iam", region="us-east-1", query_params=params,
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="list IAM policies",
    )


# ──────────────────────────────────────────────────────────────────────────
# CloudWatch (Query protocol for Alarms, JSON for Metrics/Logs)
# ──────────────────────────────────────────────────────────────────────────

async def list_cloudwatch_alarms(ctx, creds: dict, region: str) -> str:
    params = {"Action": "DescribeAlarms", "Version": "2010-08-01"}
    return await _signed_request(
        ctx, method="GET", service="monitoring", region=region, query_params=params,
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="list CloudWatch alarms",
    )


async def get_cloudwatch_metric_statistics(ctx, creds: dict, region: str, namespace: str, metric_name: str, **kw) -> str:
    params = {
        "Action": "GetMetricStatistics", "Version": "2010-08-01",
        "Namespace": namespace, "MetricName": metric_name,
    }
    params.update({k: v for k, v in kw.items() if v is not None})
    return await _signed_request(
        ctx, method="GET", service="monitoring", region=region, query_params=params,
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="get CloudWatch metric statistics",
    )


# ──────────────────────────────────────────────────────────────────────────
# Cost Explorer (REST, JSON response, global service reachable at us-east-1)
# ──────────────────────────────────────────────────────────────────────────

async def get_cost_and_usage(ctx, creds: dict, start_date: str, end_date: str, granularity: str = "MONTHLY", group_by_service: bool = True) -> dict:
    body = {
        "TimePeriod": {"Start": start_date, "End": end_date},
        "Granularity": granularity,
        "Metrics": ["UnblendedCost"],
    }
    if group_by_service:
        body["GroupBy"] = [{"Type": "DIMENSION", "Key": "SERVICE"}]
    return await _signed_request(
        ctx, method="POST", service="ce", region="us-east-1", path="/",
        json_body=body, extra_headers={"X-Amz-Target": "AWSInsightsIndexService.GetCostAndUsage"},
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="get cost and usage",
    )


async def get_cost_forecast(ctx, creds: dict, start_date: str, end_date: str, granularity: str = "MONTHLY") -> dict:
    body = {
        "TimePeriod": {"Start": start_date, "End": end_date},
        "Granularity": granularity,
        "Metric": "UNBLENDED_COST",
    }
    return await _signed_request(
        ctx, method="POST", service="ce", region="us-east-1", path="/",
        json_body=body, extra_headers={"X-Amz-Target": "AWSInsightsIndexService.GetCostForecast"},
        access_key_id=creds["access_key_id"], secret_access_key=creds["secret_access_key"],
        session_token=creds.get("session_token"), action_label="get cost forecast",
    )
