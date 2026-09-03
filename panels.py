"""Panel UI -- connections list/connect form for AWS Connector.

SIDEBAR CONTENT -- NO CARDS ANYWHERE, per ~/UI_INTERFACE_STANDARD.md's
"left sidebar, no decorated cards" rule (same convention as GitLab CI/CD
Connector's / MuleSoft Connector's panels.py).

Every section (connections, connect form) is a plain ui.Stack, content
stacked vertically and left-aligned, sections separated by ui.Divider() --
no Card border/background/shadow anywhere in this slot. Disconnect lives
only in the "App settings" screen (panels_settings.py). The one secondary
"App settings" button is always the LAST element at the bottom of the
sidebar.

WHY A FULL FORM (access key + secret key + region + optional session
token), NOT A SINGLE TOKEN, UNLIKE MOST OF THE PORTFOLIO.

AWS has no single bearer token -- every request is SigV4-signed from an
Access Key ID + Secret Access Key pair plus a target region (see
aws_sigv4.py). The form asks for all three explicitly, with region
defaulting to us-east-1 for the common case, plus an optional session
token field for temporary/assumed-role credentials.

Per Vlad's standing rule: every input carries its own label (not just a
placeholder), placeholders are contextually specific, and the form
container is stretched to the full width of the left sidebar with its
contents stretched to fill it. The sidebar carries NO instructions that
duplicate the "How do I set this up?" modal.
"""
from __future__ import annotations

from imperal_sdk import ui

from app import ext
import handlers as h


def _settings_button() -> ui.UINode:
    """The one required secondary entry point into the settings screen --
    always the last element at the bottom of the sidebar."""
    return ui.Button(
        "App settings", variant="secondary", size="sm", icon="settings", on_click=ui.Call("__panel__aws_settings"),
    )


def _connection_row(c: dict) -> ui.UINode:
    return ui.Stack(direction="v", gap=1, children=[
        ui.Text(c.get("title") or c.get("access_key_id", ""), variant="body"),
        ui.Text(c.get("arn", ""), variant="caption"),
    ])


def _connections_section(connections: list[dict]) -> ui.UINode:
    if not connections:
        return ui.Text("No AWS accounts connected yet.", variant="caption")
    children: list[ui.UINode] = []
    for i, c in enumerate(connections):
        if i > 0:
            children.append(ui.Divider())
        children.append(_connection_row(c))
    return ui.Stack(direction="v", gap=2, children=children)


def _connect_section() -> ui.UINode:
    """Plain content, no Card wrapper. Stretched full-width per
    UI_INTERFACE_STANDARD.md. No intro heading/description text here --
    the Access Key walkthrough and read-only-policy recommendation live
    ONLY in aws_connect_help's modal (button below opens it); repeating
    it here would duplicate that instruction."""
    return ui.Stack(direction="v", gap=3, align="stretch", children=[
        ui.Button("How do I set this up?", variant="ghost", size="sm",
                  icon="HelpCircle",
                  on_click=ui.Call("__panel__aws_connect_help")),
        ui.Form(
            action="connect_aws",
            submit_label="Verify and connect",
            children=[
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("Access Key ID", variant="caption"),
                    ui.Input(param_name="access_key_id",
                             placeholder="AKIAIOSFODNN7EXAMPLE"),
                ]),
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("Secret Access Key", variant="caption"),
                    ui.Password(param_name="secret_access_key",
                                 placeholder="Paste the secret key shown once by AWS"),
                ]),
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("Default region", variant="caption"),
                    ui.Input(param_name="region",
                             placeholder="e.g. us-east-1, eu-west-1",
                             value="us-east-1"),
                ]),
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("Session token (optional)", variant="caption"),
                    ui.Password(param_name="session_token",
                                 placeholder="Only for temporary/assumed-role credentials"),
                ]),
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("Label (optional)", variant="caption"),
                    ui.Input(param_name="label", placeholder="e.g. Production account"),
                ]),
            ],
        ),
    ])


@ext.panel("aws_connect", slot="left", title="AWS", icon="☁️",
           default_width=320, min_width=260, max_width=420)
async def aws_connect_panel(ctx, **kwargs) -> object:
    connections = await h._load_connections(ctx)
    connected = bool(connections)

    header = ui.Header(text="AWS", level=2,
                        subtitle="Manage your EC2, S3, RDS, Lambda, IAM, CloudWatch and Cost Explorer from Imperal")

    if not connected:
        return ui.Stack(direction="v", gap=4, align="stretch", children=[
            header,
            _connect_section(),
            ui.Divider(),
            _settings_button(),
        ])

    return ui.Stack(direction="v", gap=4, align="stretch", children=[
        header,
        ui.Text("Connected accounts", variant="subtitle"),
        _connections_section(connections),
        ui.Divider(),
        ui.Button("Open cloud overview", variant="primary", size="sm", icon="Cloud", on_click=ui.Call("__panel__aws_center")),
        ui.Divider(),
        _connect_section(),
        ui.Divider(),
        _settings_button(),
    ])


@ext.panel("aws_connect_help", slot="center",
           title="How to connect AWS", center_overlay=True)
async def aws_connect_help(ctx, **kwargs) -> object:
    content = ui.Stack(direction="v", gap=3, children=[
        ui.Text("1. Sign in to the AWS Console and open IAM > Users."),
        ui.Text("2. Create a new IAM user (or use an existing one) and attach the "
                "ReadOnlyAccess managed policy -- this is enough to start exploring "
                "your account safely."),
        ui.Text("3. Open that user's Security credentials tab and create a new Access Key "
                "(choose \"Application running outside AWS\" as the use case)."),
        ui.Text("4. Copy both the Access Key ID and Secret Access Key -- AWS shows the "
                "secret only once."),
        ui.Text("5. Paste both, plus your default region, into the form and Verify and connect."),
        ui.Divider(),
        ui.Alert(
            title="Scope your key before connecting",
            message=(
                "We strongly recommend creating a dedicated IAM user scoped to "
                "ReadOnlyAccess for your first connection. Broader keys work too, "
                "but a mis-scoped key can affect real infrastructure -- start "
                "read-only and widen permissions only when you need to act."
            ),
            type="warning",
        ),
        ui.Divider(),
        ui.Alert(
            title="Covers the operational core, not every AWS service",
            message=(
                "This connects EC2, S3, RDS, Lambda, IAM, CloudWatch and Cost "
                "Explorer. Container orchestration (EKS/ECS), DNS/CDN "
                "(Route53/CloudFront) and managed AI services (SageMaker) are out "
                "of scope here."
            ),
            type="info",
        ),
        ui.Divider(),
        ui.Link(
            label="Open AWS's official Access Keys guide",
            href="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html",
        ),
    ])
    return ui.Dialog(
        title="How to connect AWS",
        content=content,
        confirm_label="",
        cancel_label="Close",
    )


@ext.panel("aws_center", slot="center", title="AWS", icon="☁️", center_overlay=True)
async def aws_center_panel(ctx, connection_id: str = "", **kwargs) -> object:
    """Post-connect main screen: the cloud-health overview (Tier 3
    value-add) -- EC2/S3/RDS counts plus month-to-date cost, the same
    "actionable summary, not just a list" shape as GitLab CI/CD
    Connector's project dashboard."""
    connections = await h._load_connections(ctx)
    if not connections:
        return ui.Empty(
            message="Connect an AWS account from the sidebar to see your cloud overview here.",
            icon="☁️",
        )
    return await _cloud_overview(ctx, connection_id)


async def _cloud_overview(ctx, connection_id: str) -> ui.UINode:
    from schemas import GetCloudOverviewParams
    result = await h.get_cloud_overview(ctx, GetCloudOverviewParams(connection_id=connection_id))
    if not result.success or not result.data:
        return ui.Stack(direction="v", gap=3, align="stretch", children=[
            ui.Alert(title="Could not load your cloud overview",
                     message=result.error or "Check your connection and try again.",
                     type="error"),
        ])
    r = result.data
    return ui.Stack(direction="v", gap=3, align="stretch", children=[
        ui.Stats(children=[
            ui.Stat(label="EC2 running", value=str(r.ec2_running)),
            ui.Stat(label="EC2 stopped", value=str(r.ec2_stopped)),
            ui.Stat(label="S3 buckets", value=str(r.s3_bucket_count)),
            ui.Stat(label="RDS instances", value=str(r.rds_instance_count)),
        ]),
        ui.Divider(),
        ui.Stat(label="Month-to-date cost (USD)", value=f"${r.month_to_date_cost_usd:,.2f}"),
    ])
