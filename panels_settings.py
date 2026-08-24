"""The single "App settings" screen (center slot) -- connection management
(disconnect per AWS account) for AWS Connector. Split out of panels.py per
the same convention as GitLab CI/CD Connector's / MuleSoft Connector's
panels_settings.py.

Per ~/UI_INTERFACE_STANDARD.md: the left sidebar never wraps the connect
form in a Card, and disconnect (never exposed in the sidebar itself) lives
here, one row per connected AWS account. The one secondary "App settings"
button sits LAST at the bottom of the sidebar.
"""
from __future__ import annotations

from imperal_sdk import ui

from app import ext
import handlers as h


def _connection_row(c: dict) -> ui.UINode:
    label = c.get("title") or c.get("arn", "")
    return ui.Stack(direction="v", gap=1, align="start", children=[
        ui.Text(label, variant="body"),
        ui.Text(f"Region: {c.get('region', '')}", variant="caption"),
        ui.Text(c.get("arn", ""), variant="caption"),
        ui.Button(
            "Disconnect", variant="danger", size="sm",
            on_click=ui.Call("disconnect_aws", {"connection_id": c.get("id")}),
        ),
    ])


def _connections_section(connections: list[dict]) -> ui.UINode:
    if not connections:
        return ui.Stack(direction="v", gap=1, children=[
            ui.Text("Connections", variant="heading"),
            ui.Text("No AWS accounts connected yet.", variant="caption"),
        ])
    children: list[ui.UINode] = [ui.Text("Connections", variant="heading")]
    for i, c in enumerate(connections):
        if i:
            children.append(ui.Divider())
        children.append(_connection_row(c))
    return ui.Stack(direction="v", gap=2, children=children)


@ext.panel("aws_settings", slot="center", title="AWS -- App settings", center_overlay=True)
async def aws_settings_panel(ctx, **kwargs) -> object:
    connections = await h._load_connections(ctx)
    return ui.Stack(direction="v", gap=4, children=[
        ui.Header(text="App settings", level=2, subtitle="AWS (Amazon Web Services)"),
        _connections_section(connections),
        ui.Divider(),
        ui.Text(
            "Disconnecting removes the saved Access Key ID/Secret Access Key "
            "pair from Imperal only. Nothing is changed in your AWS account -- "
            "deactivate or delete the key yourself in IAM if you no longer want "
            "it to work at all.",
            variant="caption",
        ),
    ])
