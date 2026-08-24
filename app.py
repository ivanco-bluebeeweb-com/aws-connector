"""Extension declaration, secrets, lifecycle hooks.

WHY BYOK (bring-your-own-key), SAME REASONING AS GitLab CI/CD / n8n /
MuleSoft Connector. AWS lives inside the USER'S OWN account -- Imperal
cannot and should not broker access to someone else's AWS account
centrally, and every AWS account's IAM boundary is exactly the boundary
the user controls by scoping the Access Key they create.

WHY access_key_id + secret_access_key + region + optional session_token
(A CONNECTION RECORD), NOT A SINGLE TOKEN, UNLIKE MOST OF THE PORTFOLIO.

AWS has no single bearer token. Every request is signed with SigV4 from
an Access Key ID + Secret Access Key pair (see aws_sigv4.py for the full
algorithm) plus a target region baked into the signature's credential
scope -- region is not optional metadata here, it changes what the
signature itself computes to. An optional session_token is also stored
for temporary STS credentials (assumed-role scenarios). Same storage
shape as gitlab_connections: one JSON-array secret, one entry per
connection (ctx.secrets has no "one secret per id" primitive).

WHY `write_mode="both"`, SAME REASONING AS EVERY OTHER BYOK CONNECTOR.

Declaring `write_mode="user"` would leave a first-time user with no
in-app screen explaining what an AWS Access Key even is, or the strong
recommendation to scope it to a read-only IAM policy first (see
IDEAL_ONBOARDING.md #1) -- so the connect form lives inside this app,
same as GitLab/n8n/MuleSoft/Automation Anywhere/UiPath/Blue Prism.

WHY THIS CONNECTOR IS SCOPED TO EC2/S3/RDS/Lambda/IAM/CloudWatch/Cost
EXPLORER, NOT "ALL OF AWS".

AWS is not one API but several hundred independent service APIs. Per
CONNECTOR_DISCOVERY.md, this app covers the operational core (compute,
storage, database, serverless, identity, monitoring, cost) in depth;
container orchestration (EKS/ECS), DNS/CDN (Route53/CloudFront) and
managed AI services (SageMaker) are deliberate separate future apps, not
a silent gap here.
"""

from imperal_sdk import Extension, ChatExtension

ext = Extension(
    "aws-connector",
    version="0.1.0",
    display_name="AWS (Amazon Web Services)",
    description=(
        "Connect your own AWS account (BYOK Access Key, SigV4-signed requests) "
        "to see and manage EC2 (instances, security groups), S3 (buckets, objects), "
        "RDS (instances), Lambda (functions, invoke, logs), IAM (users, roles), "
        "CloudWatch (alarms, metrics) and Cost Explorer (cost and usage, forecasts) "
        "from Imperal. Your Access Key is verified against your own account "
        "(sts:GetCallerIdentity) before it's saved. Scoped to the operational core -- "
        "container orchestration, DNS/CDN and managed AI services are out of scope."
    ),
    icon="icon.svg",
    actions_explicit=True,
    capabilities=["aws:read", "aws:write"],
)

chat = ChatExtension(
    ext,
    tool_name="aws-connector",
    description="View and manage AWS -- EC2, S3, RDS, Lambda, IAM, CloudWatch, Cost Explorer",
)

ext.secret(
    "aws_connections",
    (
        "Your connected AWS accounts -- stored as a JSON array, one entry "
        "per account, each with its own Access Key ID, Secret Access Key, "
        "default region, optional session token, and a friendly label. "
        "Managed through connect_aws / disconnect_aws -- you should not "
        "need to edit this directly."
    ),
    required=True,
    write_mode="both",
    max_bytes=65536,
    rotation_hint_days=90,
)(lambda: None)


@ext.health_check
async def health_check(ctx) -> dict:
    """Fast configuration health; no third-party call -- just confirms at
    least one AWS account connection is stored, same shape as GitLab CI/CD
    Connector's / MuleSoft Connector's health_check."""
    import json as _json
    raw = await ctx.secrets.get("aws_connections")
    try:
        count = len(_json.loads(raw)) if raw else 0
    except Exception:
        count = 0
    return {
        "healthy": True,
        "detail": (
            f"{count} AWS account(s) connected." if count
            else "Not connected yet -- run connect_aws."
        ),
    }
