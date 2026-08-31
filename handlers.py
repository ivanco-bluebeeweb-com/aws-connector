"""Chat functions for AWS Connector: connection management, EC2, S3, RDS,
Lambda, IAM, CloudWatch, Cost Explorer, and a cloud overview (Tier 3
value-add). Built on aws_client.py / aws_sigv4.py / schemas.py, following
the same shape as GitLab CI/CD Connector's / n8n Connector's handlers.py.
"""
from __future__ import annotations

import json
import uuid
import xml.etree.ElementTree as ET
from decimal import Decimal

from imperal_sdk import ActionResult

import aws_client as ac
from app import ext, chat
from schemas import (
    NoParams,
    ConnectAwsParams, ProviderConnection, ProviderConnectionList,
    DisconnectAwsParams, DeleteResult,
    ListEc2InstancesParams, Ec2Instance, Ec2InstanceList,
    GetEc2InstanceParams, Ec2InstanceDetail,
    Ec2ActionParams, Ec2ActionResult,
    ListS3BucketsParams, S3Bucket, S3BucketList,
    ListS3ObjectsParams, S3Object, S3ObjectList,
    ListRdsInstancesParams, RdsInstance, RdsInstanceList,
    ListRdsSnapshotsParams, RdsSnapshot, RdsSnapshotList,
    ListLambdaFunctionsParams, LambdaFunction, LambdaFunctionList,
    InvokeLambdaParams, LambdaInvokeResult,
    ListIamUsersParams, IamUser, IamUserList,
    ListIamRolesParams, IamRole, IamRoleList,
    ListAlarmsParams, CloudWatchAlarm, CloudWatchAlarmList,
    GetMetricStatisticsParams, MetricDatapoint, MetricStatisticsResult,
    GetCostAndUsageParams, CostByService, CostAndUsageResult,
    GetCostForecastParams, CostForecastResult,
    GetCloudOverviewParams, CloudOverview,
)

_SECRET_NAME = "aws_connections"


# ──────────────────────────────────────────────────────────────────────────
# Connection storage helpers -- one secret holding a JSON array of
# connection records, same precedent as GitLab CI/CD Connector / MuleSoft
# Connector / n8n Connector (ctx.secrets has no "one secret per id"
# primitive).
# ──────────────────────────────────────────────────────────────────────────

async def _load_connections(ctx) -> list[dict]:
    raw = await ctx.secrets.get(_SECRET_NAME)
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


async def _save_connections(ctx, connections: list[dict]) -> None:
    await ctx.secrets.set(_SECRET_NAME, json.dumps(connections))


async def _find_connection(ctx, connection_id: str) -> dict | None:
    connections = await _load_connections(ctx)
    if not connection_id and len(connections) == 1:
        return connections[0]
    for c in connections:
        if c.get("id") == connection_id:
            return c
    return None


async def _resolve(ctx, connection_id: str) -> dict | None:
    return await _find_connection(ctx, connection_id)


def _creds(conn: dict, region: str | None = None) -> dict:
    return {
        "access_key_id": conn["access_key_id"],
        "secret_access_key": conn["secret_access_key"],
        "session_token": conn.get("session_token") or None,
    }


def _region_for(conn: dict, override: str) -> str:
    return override or conn.get("region") or "us-east-1"


def _xml_root(text: str) -> ET.Element:
    return ET.fromstring(text)


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _xml_items(root: ET.Element, item_tag: str) -> list[ET.Element]:
    return [el for el in root.iter() if _strip_ns(el.tag) == item_tag]


def _xml_text(el: ET.Element, child_tag: str) -> str:
    for c in el:
        if _strip_ns(c.tag) == child_tag:
            return (c.text or "").strip()
    return ""


def _xml_name_tag(el: ET.Element) -> str:
    for tagset in el:
        if _strip_ns(tagset.tag) != "tagSet":
            continue
        for item in tagset:
            if _strip_ns(item.tag) != "item":
                continue
            if _xml_text(item, "key") == "Name":
                return _xml_text(item, "value")
    return ""


def _err(prefix: str, e: "ac.ProviderError") -> ActionResult:
    return ActionResult.error(f"{prefix}: {e.detail}", code=f"AWS_HTTP_{e.status_code}")


def _no_connection() -> ActionResult:
    return ActionResult.error(
        "No AWS connection found. Connect an AWS account first.",
        code="AWS_NO_CONNECTION",
    )


# ──────────────────────────────────────────────────────────────────────────
# Connection management
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "connect_aws",
    "Connect your own AWS account by saving an Access Key ID + Secret "
    "Access Key pair, after checking they actually work via "
    "sts:GetCallerIdentity. A read-only IAM policy is strongly "
    "recommended for the key you create.",
    action_type="write",
    chain_callable=True,
    data_model=ProviderConnection,
    event="aws-connector.connect_aws",
    effects=["aws.provider.connected"],
)
async def connect_aws(ctx, params: ConnectAwsParams) -> ActionResult:
    """Connect your own AWS account by saving an Access Key ID + Secret Access Key pair, after checking they actually work via sts:GetCallerIdentity."""
    if not params.access_key_id or not params.secret_access_key:
        return ActionResult.error(
            "Access Key ID and Secret Access Key are both required.",
            code="AWS_MISSING_CREDENTIALS",
        )
    region = params.region or "us-east-1"
    try:
        identity = await ac.check_connection(
            ctx, params.access_key_id, params.secret_access_key, region,
            params.session_token or None,
        )
    except ac.ProviderError as e:
        return _err("Couldn't verify these AWS credentials", e)

    connection_id = str(uuid.uuid4())
    record = {
        "id": connection_id,
        "title": params.label or identity.get("arn", params.access_key_id),
        "access_key_id": params.access_key_id,
        "secret_access_key": params.secret_access_key,
        "region": region,
        "session_token": params.session_token or "",
        "arn": identity.get("arn", ""),
    }
    connections = await _load_connections(ctx)
    connections.append(record)
    await _save_connections(ctx, connections)
    return ActionResult.success(
        ProviderConnection(
            id=connection_id, title=record["title"], connected=True,
            detail=identity.get("arn", ""), region=record["region"],
            arn=identity.get("arn", ""),
        ),
        summary=f"AWS account connected -- {identity.get('arn', params.access_key_id)}.",
        refresh_panels=["aws_connect", "aws_settings"],
    )


@chat.function(
    "disconnect_aws",
    "Disconnect an AWS account: deletes the saved Access Key ID/Secret "
    "Access Key pair. Nothing in AWS itself is changed; the key remains "
    "valid there until you deactivate or delete it yourself in IAM.",
    action_type="write",
    chain_callable=True,
    data_model=DeleteResult,
    event="aws-connector.disconnect_aws",
    effects=["aws.provider.disconnected"],
)
async def disconnect_aws(ctx, params: DisconnectAwsParams) -> ActionResult:
    """Disconnect an AWS account: deletes the saved Access Key ID/Secret Access Key pair."""
    connections = await _load_connections(ctx)
    remaining = [c for c in connections if c.get("id") != params.connection_id]
    if len(remaining) == len(connections) and connections:
        return ActionResult.error("Connection not found.", code="AWS_CONN_NOT_FOUND")
    await _save_connections(ctx, remaining)
    return ActionResult.success(
        DeleteResult(deleted=True, id=params.connection_id),
        summary="AWS account disconnected.",
        refresh_panels=["aws_connect", "aws_settings"],
    )


@chat.function(
    "list_connections",
    "List the connected AWS accounts.",
    action_type="read",
    chain_callable=True,
    data_model=ProviderConnectionList,
)
async def list_connections(ctx, params: NoParams) -> ActionResult:
    """List the connected AWS accounts."""
    connections = await _load_connections(ctx)
    items = [
        ProviderConnection(
            id=c.get("id", ""), title=c.get("title", ""), connected=True,
            detail=c.get("arn", ""), region=c.get("region", ""),
            arn=c.get("arn", ""),
        )
        for c in connections
    ]
    return ActionResult.success(ProviderConnectionList(connections=items), summary="Connections listed.")


# ──────────────────────────────────────────────────────────────────────────
# EC2
# ──────────────────────────────────────────────────────────────────────────


def _ec2_instance_from_xml(item: ET.Element, region: str) -> Ec2Instance:
    instance_id = _xml_text(item, "instanceId")
    instance_type = _xml_text(item, "instanceType")
    state_el = None
    for c in item:
        if _strip_ns(c.tag) == "instanceState":
            state_el = c
    state = _xml_text(state_el, "name") if state_el is not None else ""
    return Ec2Instance(
        instance_id=instance_id, instance_type=instance_type, state=state,
        region=region, launch_time=_xml_text(item, "launchTime"),
        public_ip=_xml_text(item, "ipAddress"), private_ip=_xml_text(item, "privateIpAddress"),
        vpc_id=_xml_text(item, "vpcId"), subnet_id=_xml_text(item, "subnetId"),
        name_tag=_xml_name_tag(item),
    )


@chat.function(
    "list_ec2_instances",
    "List EC2 instances in the connected AWS account, optionally filtered by region and/or state.",
    action_type="read",
    chain_callable=True,
    data_model=Ec2InstanceList,
)
async def list_ec2_instances(ctx, params: ListEc2InstancesParams) -> ActionResult:
    """List EC2 instances in the connected AWS account, optionally filtered by region and/or state."""
    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    region = _region_for(conn, params.region)
    try:
        xml_text = await ac.list_ec2_instances(ctx, _creds(conn), region, params.state or None)
    except ac.ProviderError as e:
        return _err("Couldn't list EC2 instances", e)
    root = _xml_root(xml_text)
    instances = [_ec2_instance_from_xml(item, region) for item in _xml_items(root, "item") if _xml_text(item, "instanceId")]
    return ActionResult.success(Ec2InstanceList(instances=instances), summary="Ec2 instances listed.")


@chat.function(
    "get_ec2_instance",
    "Read one EC2 instance in full: type, state, network details, and its Name tag.",
    action_type="read",
    chain_callable=True,
    data_model=Ec2InstanceDetail,
)
async def get_ec2_instance(ctx, params: GetEc2InstanceParams) -> ActionResult:
    """Read one EC2 instance in full: type, state, network details, and its Name tag."""
    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    region = _region_for(conn, params.region)
    try:
        xml_text = await ac.list_ec2_instances(ctx, _creds(conn), region)
    except ac.ProviderError as e:
        return _err("Couldn't read this EC2 instance", e)
    root = _xml_root(xml_text)
    for item in _xml_items(root, "item"):
        if _xml_text(item, "instanceId") != params.instance_id:
            continue
        state_el = next((c for c in item if _strip_ns(c.tag) == "instanceState"), None)
        groups = []
        for c in item:
            if _strip_ns(c.tag) == "groupSet":
                for g in c:
                    if _strip_ns(g.tag) == "item":
                        groups.append(_xml_text(g, "groupName"))
        return ActionResult.success(Ec2InstanceDetail(
            instance_id=params.instance_id, instance_type=_xml_text(item, "instanceType"),
            state=_xml_text(state_el, "name") if state_el is not None else "",
            region=region, launch_time=_xml_text(item, "launchTime"),
            public_ip=_xml_text(item, "ipAddress"), private_ip=_xml_text(item, "privateIpAddress"),
            vpc_id=_xml_text(item, "vpcId"), subnet_id=_xml_text(item, "subnetId"),
            ami_id=_xml_text(item, "imageId"), key_name=_xml_text(item, "keyName"),
            security_groups=groups, name_tag=_xml_name_tag(item),
        ), summary="Ec2 instance retrieved.")
    return ActionResult.error("EC2 instance not found.", code="AWS_EC2_NOT_FOUND")


@chat.function(
    "start_ec2_instance",
    "Start a stopped EC2 instance.",
    action_type="write",
    chain_callable=True,
    data_model=Ec2ActionResult,
    event="aws-connector.start_ec2_instance",
    effects=["aws.ec2.instance.started"],
)
async def start_ec2_instance(ctx, params: Ec2ActionParams) -> ActionResult:
    """Start a stopped EC2 instance."""
    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    region = _region_for(conn, params.region)
    try:
        xml_text = await ac.start_ec2_instance(ctx, _creds(conn), region, params.instance_id)
    except ac.ProviderError as e:
        return _err("Couldn't start this EC2 instance", e)
    root = _xml_root(xml_text)
    item = next(iter(_xml_items(root, "item")), None)
    prev = cur = ""
    if item is not None:
        for c in item:
            if _strip_ns(c.tag) == "previousState":
                prev = _xml_text(c, "name")
            if _strip_ns(c.tag) == "currentState":
                cur = _xml_text(c, "name")
    return ActionResult.success(
        Ec2ActionResult(instance_id=params.instance_id, previous_state=prev, current_state=cur),
        summary=f"EC2 instance {params.instance_id} is now {cur or 'starting'}.",
    )


@chat.function(
    "stop_ec2_instance",
    "Stop a running EC2 instance.",
    action_type="write",
    chain_callable=True,
    data_model=Ec2ActionResult,
    event="aws-connector.stop_ec2_instance",
    effects=["aws.ec2.instance.stopped"],
)
async def stop_ec2_instance(ctx, params: Ec2ActionParams) -> ActionResult:
    """Stop a running EC2 instance."""
    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    region = _region_for(conn, params.region)
    try:
        xml_text = await ac.stop_ec2_instance(ctx, _creds(conn), region, params.instance_id)
    except ac.ProviderError as e:
        return _err("Couldn't stop this EC2 instance", e)
    root = _xml_root(xml_text)
    item = next(iter(_xml_items(root, "item")), None)
    prev = cur = ""
    if item is not None:
        for c in item:
            if _strip_ns(c.tag) == "previousState":
                prev = _xml_text(c, "name")
            if _strip_ns(c.tag) == "currentState":
                cur = _xml_text(c, "name")
    return ActionResult.success(
        Ec2ActionResult(instance_id=params.instance_id, previous_state=prev, current_state=cur),
        summary=f"EC2 instance {params.instance_id} is now {cur or 'stopping'}.",
    )


# ──────────────────────────────────────────────────────────────────────────
# S3
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_s3_buckets",
    "List S3 buckets in the connected AWS account.",
    action_type="read",
    chain_callable=True,
    data_model=S3BucketList,
)
async def list_s3_buckets(ctx, params: ListS3BucketsParams) -> ActionResult:
    """List S3 buckets in the connected AWS account."""
    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    try:
        xml_text = await ac.list_s3_buckets(ctx, _creds(conn), _region_for(conn, ""))
    except ac.ProviderError as e:
        return _err("Couldn't list S3 buckets", e)
    root = _xml_root(xml_text)
    buckets = [
        S3Bucket(bucket_name=_xml_text(b, "Name"), creation_date=_xml_text(b, "CreationDate"), region=conn.get("region", ""))
        for b in _xml_items(root, "Bucket")
    ]
    return ActionResult.success(S3BucketList(buckets=buckets), summary="S3 buckets listed.")


@chat.function(
    "list_s3_objects",
    "List objects inside one S3 bucket, optionally filtered by key prefix.",
    action_type="read",
    chain_callable=True,
    data_model=S3ObjectList,
)
async def list_s3_objects(ctx, params: ListS3ObjectsParams) -> ActionResult:
    """List objects inside one S3 bucket, optionally filtered by key prefix."""
    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    region = _region_for(conn, params.region)
    try:
        xml_text = await ac.list_s3_objects(ctx, _creds(conn), region, params.bucket_name, params.prefix)
    except ac.ProviderError as e:
        return _err(f"Couldn't list objects in bucket {params.bucket_name}", e)
    root = _xml_root(xml_text)
    objects = [
        S3Object(
            key=_xml_text(c, "Key"),
            size_bytes=int(_xml_text(c, "Size") or 0),
            last_modified=_xml_text(c, "LastModified"),
            storage_class=_xml_text(c, "StorageClass"),
        )
        for c in _xml_items(root, "Contents")
    ]
    return ActionResult.success(S3ObjectList(objects=objects, bucket_name=params.bucket_name, prefix=params.prefix), summary="S3 objects listed.")


# ──────────────────────────────────────────────────────────────────────────
# RDS
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_rds_instances",
    "List RDS database instances in the connected AWS account.",
    action_type="read",
    chain_callable=True,
    data_model=RdsInstanceList,
)
async def list_rds_instances(ctx, params: ListRdsInstancesParams) -> ActionResult:
    """List RDS database instances in the connected AWS account."""
    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    region = _region_for(conn, params.region)
    try:
        xml_text = await ac.list_rds_instances(ctx, _creds(conn), region)
    except ac.ProviderError as e:
        return _err("Couldn't list RDS instances", e)
    root = _xml_root(xml_text)
    instances = []
    for item in _xml_items(root, "DBInstance"):
        endpoint_el = next((c for c in item if _strip_ns(c.tag) == "Endpoint"), None)
        instances.append(RdsInstance(
            db_instance_identifier=_xml_text(item, "DBInstanceIdentifier"),
            engine=_xml_text(item, "Engine"), engine_version=_xml_text(item, "EngineVersion"),
            status=_xml_text(item, "DBInstanceStatus"), instance_class=_xml_text(item, "DBInstanceClass"),
            allocated_storage_gb=int(_xml_text(item, "AllocatedStorage") or 0),
            multi_az=(_xml_text(item, "MultiAZ").lower() == "true"),
            endpoint=_xml_text(endpoint_el, "Address") if endpoint_el is not None else "",
        ))
    return ActionResult.success(RdsInstanceList(instances=instances), summary="Rds instances listed.")


@chat.function(
    "list_rds_snapshots",
    "List RDS snapshots, optionally filtered to one DB instance.",
    action_type="read",
    chain_callable=True,
    data_model=RdsSnapshotList,
)
async def list_rds_snapshots(ctx, params: ListRdsSnapshotsParams) -> ActionResult:
    """List RDS snapshots, optionally filtered to one DB instance."""
    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    region = _region_for(conn, params.region)
    try:
        xml_text = await ac.list_rds_snapshots(ctx, _creds(conn), region)
    except ac.ProviderError as e:
        return _err("Couldn't list RDS snapshots", e)
    root = _xml_root(xml_text)
    snapshots = []
    for item in _xml_items(root, "DBSnapshot"):
        db_id = _xml_text(item, "DBInstanceIdentifier")
        if params.db_instance_identifier and db_id != params.db_instance_identifier:
            continue
        snapshots.append(RdsSnapshot(
            snapshot_id=_xml_text(item, "DBSnapshotIdentifier"), db_instance_identifier=db_id,
            status=_xml_text(item, "Status"), created_at=_xml_text(item, "SnapshotCreateTime"),
            engine=_xml_text(item, "Engine"),
        ))
    return ActionResult.success(RdsSnapshotList(snapshots=snapshots), summary="Rds snapshots listed.")


# ──────────────────────────────────────────────────────────────────────────
# Lambda
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_lambda_functions",
    "List Lambda functions in the connected AWS account.",
    action_type="read",
    chain_callable=True,
    data_model=LambdaFunctionList,
)
async def list_lambda_functions(ctx, params: ListLambdaFunctionsParams) -> ActionResult:
    """List Lambda functions in the connected AWS account."""
    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    region = _region_for(conn, params.region)
    try:
        body = await ac.list_lambda_functions(ctx, _creds(conn), region)
    except ac.ProviderError as e:
        return _err("Couldn't list Lambda functions", e)
    functions = [
        LambdaFunction(
            function_name=f.get("FunctionName", ""), runtime=f.get("Runtime", ""),
            handler=f.get("Handler", ""), memory_mb=f.get("MemorySize", 0),
            timeout_seconds=f.get("Timeout", 0), last_modified=f.get("LastModified", ""),
        )
        for f in (body.get("Functions") or [])
    ]
    return ActionResult.success(LambdaFunctionList(functions=functions), summary="Lambda functions listed.")


@chat.function(
    "invoke_lambda",
    "Invoke a Lambda function synchronously with a JSON event payload.",
    action_type="write",
    chain_callable=True,
    data_model=LambdaInvokeResult,
    event="aws-connector.invoke_lambda",
    effects=["aws.lambda.function.invoked"],
)
async def invoke_lambda(ctx, params: InvokeLambdaParams) -> ActionResult:
    """Invoke a Lambda function synchronously with a JSON event payload."""
    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    region = _region_for(conn, params.region)
    try:
        payload = json.loads(params.payload_json or "{}")
    except Exception:
        return ActionResult.error("payload_json must be valid JSON.", code="AWS_INVALID_PAYLOAD")
    try:
        body = await ac.invoke_lambda_function(ctx, _creds(conn), region, params.function_name, payload)
    except ac.ProviderError as e:
        return _err(f"Couldn't invoke {params.function_name}", e)
    error = body.get("FunctionError", "") if isinstance(body, dict) else ""
    return ActionResult.success(
        LambdaInvokeResult(
            function_name=params.function_name, status_code=200 if not error else 400,
            response_json=json.dumps(body), error=error,
        ),
        summary=f"Invoked {params.function_name}." + (f" Function reported an error: {error}." if error else ""),
    )


# ──────────────────────────────────────────────────────────────────────────
# IAM
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_iam_users",
    "List IAM users in the connected AWS account.",
    action_type="read",
    chain_callable=True,
    data_model=IamUserList,
)
async def list_iam_users(ctx, params: ListIamUsersParams) -> ActionResult:
    """List IAM users in the connected AWS account."""
    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    try:
        xml_text = await ac.list_iam_users(ctx, _creds(conn))
    except ac.ProviderError as e:
        return _err("Couldn't list IAM users", e)
    root = _xml_root(xml_text)
    users = [
        IamUser(
            user_name=_xml_text(u, "UserName"), user_id=_xml_text(u, "UserId"),
            arn=_xml_text(u, "Arn"), created_at=_xml_text(u, "CreateDate"),
        )
        for u in _xml_items(root, "member") if _xml_text(u, "UserName")
    ]
    return ActionResult.success(IamUserList(users=users), summary="Iam users listed.")


@chat.function(
    "list_iam_roles",
    "List IAM roles in the connected AWS account.",
    action_type="read",
    chain_callable=True,
    data_model=IamRoleList,
)
async def list_iam_roles(ctx, params: ListIamRolesParams) -> ActionResult:
    """List IAM roles in the connected AWS account."""
    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    try:
        xml_text = await ac.list_iam_roles(ctx, _creds(conn))
    except ac.ProviderError as e:
        return _err("Couldn't list IAM roles", e)
    root = _xml_root(xml_text)
    roles = [
        IamRole(
            role_name=_xml_text(r, "RoleName"), role_id=_xml_text(r, "RoleId"),
            arn=_xml_text(r, "Arn"), created_at=_xml_text(r, "CreateDate"),
        )
        for r in _xml_items(root, "member") if _xml_text(r, "RoleName")
    ]
    return ActionResult.success(IamRoleList(roles=roles), summary="Iam roles listed.")


# ──────────────────────────────────────────────────────────────────────────
# CloudWatch
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_cloudwatch_alarms",
    "List CloudWatch alarms, optionally filtered by state.",
    action_type="read",
    chain_callable=True,
    data_model=CloudWatchAlarmList,
)
async def list_cloudwatch_alarms(ctx, params: ListAlarmsParams) -> ActionResult:
    """List CloudWatch alarms, optionally filtered by state."""
    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    region = _region_for(conn, params.region)
    try:
        xml_text = await ac.list_cloudwatch_alarms(ctx, _creds(conn), region)
    except ac.ProviderError as e:
        return _err("Couldn't list CloudWatch alarms", e)
    root = _xml_root(xml_text)
    alarms = []
    for item in _xml_items(root, "member"):
        name = _xml_text(item, "AlarmName")
        if not name:
            continue
        state = _xml_text(item, "StateValue")
        if params.state and state != params.state:
            continue
        alarms.append(CloudWatchAlarm(
            alarm_name=name, state=state, metric_name=_xml_text(item, "MetricName"),
            namespace=_xml_text(item, "Namespace"), comparison_operator=_xml_text(item, "ComparisonOperator"),
            threshold=float(_xml_text(item, "Threshold") or 0),
        ))
    return ActionResult.success(CloudWatchAlarmList(alarms=alarms), summary="Cloudwatch alarms listed.")


@chat.function(
    "get_metric_statistics",
    "Read CloudWatch metric datapoints for a namespace/metric over a time window.",
    action_type="read",
    chain_callable=True,
    data_model=MetricStatisticsResult,
)
async def get_metric_statistics(ctx, params: GetMetricStatisticsParams) -> ActionResult:
    """Read CloudWatch metric datapoints for a namespace/metric over a time window."""
    import datetime as _dt

    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    region = _region_for(conn, params.region)
    end = _dt.datetime.utcnow()
    start = end - _dt.timedelta(hours=params.hours_back)
    kw = {
        "StartTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "EndTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Period": params.period_seconds,
        "Statistics.member.1": params.statistic,
    }
    if params.dimension_name:
        kw["Dimensions.member.1.Name"] = params.dimension_name
        kw["Dimensions.member.1.Value"] = params.dimension_value
    try:
        xml_text = await ac.get_cloudwatch_metric_statistics(ctx, _creds(conn), region, params.namespace, params.metric_name, **kw)
    except ac.ProviderError as e:
        return _err("Couldn't read CloudWatch metric statistics", e)
    root = _xml_root(xml_text)
    points = []
    for dp in _xml_items(root, "member"):
        ts = _xml_text(dp, "Timestamp")
        if not ts:
            continue
        val_tag = next((t for t in (params.statistic,) if _xml_text(dp, t)), params.statistic)
        points.append(MetricDatapoint(
            timestamp=ts, value=float(_xml_text(dp, val_tag) or 0), unit=_xml_text(dp, "Unit"),
        ))
    return ActionResult.success(MetricStatisticsResult(metric_name=params.metric_name, namespace=params.namespace, datapoints=points), summary="Metric statistics retrieved.")


# ──────────────────────────────────────────────────────────────────────────
# Cost Explorer
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "get_cost_and_usage",
    "Read AWS cost and usage for the connected account over a time window, broken down by service.",
    action_type="read",
    chain_callable=True,
    data_model=CostAndUsageResult,
)
async def get_cost_and_usage(ctx, params: GetCostAndUsageParams) -> ActionResult:
    """Read AWS cost and usage for the connected account over a time window, broken down by service."""
    import datetime as _dt

    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    end = _dt.date.today()
    start = end - _dt.timedelta(days=params.days_back)
    try:
        body = await ac.get_cost_and_usage(
            ctx, _creds(conn), start.isoformat(), end.isoformat(),
            params.granularity, params.group_by_service,
        )
    except ac.ProviderError as e:
        return _err("Couldn't read Cost Explorer data", e)
    by_service: list[CostByService] = []
    total = Decimal("0")
    for period in body.get("ResultsByTime", []):
        if params.group_by_service:
            for g in period.get("Groups", []):
                amount = Decimal(str(g.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", 0) or 0))
                by_service.append(CostByService(service=", ".join(g.get("Keys", [])), amount_usd=float(amount)))
                total += amount
        else:
            amount = Decimal(str(period.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0) or 0))
            total += amount
    return ActionResult.success(CostAndUsageResult(
        total_amount_usd=float(total.quantize(Decimal("0.01"))),
        period_start=start.isoformat(), period_end=end.isoformat(),
        by_service=by_service,
    ), summary="Cost and usage retrieved.")


@chat.function(
    "get_cost_forecast",
    "Read AWS's own forecast of upcoming spend for the connected account.",
    action_type="read",
    chain_callable=True,
    data_model=CostForecastResult,
)
async def get_cost_forecast(ctx, params: GetCostForecastParams) -> ActionResult:
    """Read AWS's own forecast of upcoming spend for the connected account."""
    import datetime as _dt

    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    start = _dt.date.today()
    end = start + _dt.timedelta(days=params.days_forward)
    try:
        body = await ac.get_cost_forecast(ctx, _creds(conn), start.isoformat(), end.isoformat())
    except ac.ProviderError as e:
        return _err("Couldn't read the AWS cost forecast", e)
    total = Decimal(str(body.get("Total", {}).get("Amount", 0) or 0)) if isinstance(body, dict) else Decimal("0")
    return ActionResult.success(CostForecastResult(
        total_forecast_usd=float(total.quantize(Decimal("0.01"))),
        period_start=start.isoformat(), period_end=end.isoformat(),
    ), summary="Cost forecast retrieved.")


# ──────────────────────────────────────────────────────────────────────────
# Overview (Tier 3 value-add)
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "get_cloud_overview",
    "Value-add report: one-glance AWS account health snapshot -- EC2 instance counts by state, S3 bucket count, RDS instance count, and this month's cost so far.",
    action_type="read",
    chain_callable=True,
    data_model=CloudOverview,
)
async def get_cloud_overview(ctx, params: GetCloudOverviewParams) -> ActionResult:
    """Value-add report: one-glance AWS account health snapshot -- EC2 instance counts by state, S3 bucket count, RDS instance count, and this month's cost so far."""
    import datetime as _dt

    conn = await _resolve(ctx, params.connection_id)
    if not conn:
        return _no_connection()
    region = _region_for(conn, "")
    ec2_running = ec2_stopped = s3_count = rds_count = 0
    month_cost = Decimal("0")
    try:
        xml_text = await ac.list_ec2_instances(ctx, _creds(conn), region)
        root = _xml_root(xml_text)
        for item in _xml_items(root, "item"):
            state_el = next((c for c in item if _strip_ns(c.tag) == "instanceState"), None)
            state = _xml_text(state_el, "name") if state_el is not None else ""
            if state == "running":
                ec2_running += 1
            elif state == "stopped":
                ec2_stopped += 1
    except ac.ProviderError:
        pass
    try:
        xml_text = await ac.list_s3_buckets(ctx, _creds(conn), region)
        s3_count = len(_xml_items(_xml_root(xml_text), "Bucket"))
    except ac.ProviderError:
        pass
    try:
        xml_text = await ac.list_rds_instances(ctx, _creds(conn), region)
        rds_count = len(_xml_items(_xml_root(xml_text), "DBInstance"))
    except ac.ProviderError:
        pass
    try:
        today = _dt.date.today()
        start = today.replace(day=1)
        body = await ac.get_cost_and_usage(ctx, _creds(conn), start.isoformat(), today.isoformat(), "MONTHLY", False)
        for period in body.get("ResultsByTime", []):
            month_cost += Decimal(str(period.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0) or 0))
    except ac.ProviderError:
        pass
    return ActionResult.success(CloudOverview(
        ec2_running=ec2_running, ec2_stopped=ec2_stopped, s3_bucket_count=s3_count,
        rds_instance_count=rds_count, month_to_date_cost_usd=float(month_cost.quantize(Decimal("0.01"))),
    ), summary="Cloud overview retrieved.")

