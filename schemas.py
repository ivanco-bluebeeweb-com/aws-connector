"""Pydantic params models + SDL entity contracts for AWS Connector.

All params models are module-scope (V17 federal invariant, same rule as
GitLab CI/CD Connector's / n8n Connector's schemas.py).
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from imperal_sdk import sdl


class NoParams(BaseModel):
    """Explicit empty params model -- V17 disallows untyped handlers."""
    pass


# ──────────────────────────────────────────────────────────────────────────
# Connection
# ──────────────────────────────────────────────────────────────────────────


class ConnectAwsParams(BaseModel):
    access_key_id: str = Field(
        "", description="Your AWS Access Key ID, e.g. AKIAIOSFODNN7EXAMPLE."
    )
    secret_access_key: str = Field(
        "", description="Your AWS Secret Access Key -- shown only once by AWS when the key is created."
    )
    region: str = Field(
        "us-east-1", description="Default AWS region for this connection, e.g. us-east-1, eu-west-1."
    )
    session_token: str = Field(
        "", description="Optional STS session token, only needed for temporary/assumed-role credentials."
    )
    label: str = Field("", description="Optional friendly name for this AWS account connection.")


class ProviderConnection(sdl.Entity):
    id: str = ""
    title: str = ""
    connected: bool = False
    detail: str = ""
    region: str = ""
    arn: str = ""


class ProviderConnectionList(sdl.Entity):
    connections: list[ProviderConnection] = []


class DisconnectAwsParams(BaseModel):
    connection_id: str = Field("", description="ID of the connection to disconnect.")


class DeleteResult(sdl.Entity):
    deleted: bool = False
    id: str = ""


# ──────────────────────────────────────────────────────────────────────────
# EC2
# ──────────────────────────────────────────────────────────────────────────


class ListEc2InstancesParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    region: str = Field("", description="Region to list instances in. Leave empty to use the connection's default region.")
    state: str = Field("", description="Filter by instance state: pending, running, stopping, stopped, shutting-down, terminated. Leave empty for all.")


class Ec2Instance(sdl.Entity):
    instance_id: str = ""
    instance_type: str = ""
    state: str = ""
    region: str = ""
    launch_time: str = ""
    public_ip: str = ""
    private_ip: str = ""
    vpc_id: str = ""
    subnet_id: str = ""
    name_tag: str = ""


class Ec2InstanceList(sdl.Entity):
    instances: list[Ec2Instance] = []


class GetEc2InstanceParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    region: str = Field("", description="Region the instance lives in.")
    instance_id: str = Field(..., description="EC2 instance ID, e.g. i-0123456789abcdef0.")


class Ec2InstanceDetail(sdl.Entity):
    instance_id: str = ""
    instance_type: str = ""
    state: str = ""
    region: str = ""
    launch_time: str = ""
    public_ip: str = ""
    private_ip: str = ""
    vpc_id: str = ""
    subnet_id: str = ""
    ami_id: str = ""
    key_name: str = ""
    security_groups: list[str] = []
    tags: str = ""


class Ec2ActionParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    region: str = Field("", description="Region the instance lives in.")
    instance_id: str = Field(..., description="EC2 instance ID to act on.")


class Ec2ActionResult(sdl.Entity):
    instance_id: str = ""
    previous_state: str = ""
    current_state: str = ""


class ListSecurityGroupsParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    region: str = Field("", description="Region to list security groups in.")


class SecurityGroup(sdl.Entity):
    group_id: str = ""
    group_name: str = ""
    description: str = ""
    vpc_id: str = ""


class SecurityGroupList(sdl.Entity):
    groups: list[SecurityGroup] = []


class ListEbsVolumesParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    region: str = Field("", description="Region to list volumes in.")


class EbsVolume(sdl.Entity):
    volume_id: str = ""
    size_gb: int = 0
    volume_type: str = ""
    state: str = ""
    attached_instance_id: str = ""


class EbsVolumeList(sdl.Entity):
    volumes: list[EbsVolume] = []


# ──────────────────────────────────────────────────────────────────────────
# S3
# ──────────────────────────────────────────────────────────────────────────


class ListS3BucketsParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")


class S3Bucket(sdl.Entity):
    bucket_name: str = ""
    creation_date: str = ""
    region: str = ""


class S3BucketList(sdl.Entity):
    buckets: list[S3Bucket] = []


class ListS3ObjectsParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    bucket_name: str = Field(..., description="Name of the S3 bucket to list objects from.")
    prefix: str = Field("", description="Only return objects whose key starts with this prefix, e.g. 'logs/2026/'.")
    region: str = Field("", description="Region the bucket lives in. Leave empty to use the connection's default region.")


class S3Object(sdl.Entity):
    key: str = ""
    size_bytes: int = 0
    last_modified: str = ""
    storage_class: str = ""


class S3ObjectList(sdl.Entity):
    objects: list[S3Object] = []
    bucket_name: str = ""
    prefix: str = ""


class CreateS3BucketParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    bucket_name: str = Field(..., description="Globally unique name for the new S3 bucket.")
    region: str = Field("", description="Region to create the bucket in. Leave empty to use the connection's default region.")


class DeleteS3BucketParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    bucket_name: str = Field(..., description="Name of the S3 bucket to permanently delete. The bucket must be empty.")
    region: str = Field("", description="Region the bucket lives in.")


# ──────────────────────────────────────────────────────────────────────────
# RDS
# ──────────────────────────────────────────────────────────────────────────


class ListRdsInstancesParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    region: str = Field("", description="Region to list RDS instances in.")


class RdsInstance(sdl.Entity):
    db_instance_identifier: str = ""
    engine: str = ""
    engine_version: str = ""
    status: str = ""
    instance_class: str = ""
    allocated_storage_gb: int = 0
    multi_az: bool = False
    endpoint: str = ""


class RdsInstanceList(sdl.Entity):
    instances: list[RdsInstance] = []


class ListRdsSnapshotsParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    region: str = Field("", description="Region to list snapshots in.")
    db_instance_identifier: str = Field("", description="Filter to snapshots of one DB instance. Leave empty for all.")


class RdsSnapshot(sdl.Entity):
    snapshot_id: str = ""
    db_instance_identifier: str = ""
    status: str = ""
    created_at: str = ""
    engine: str = ""


class RdsSnapshotList(sdl.Entity):
    snapshots: list[RdsSnapshot] = []


# ──────────────────────────────────────────────────────────────────────────
# Lambda
# ──────────────────────────────────────────────────────────────────────────


class ListLambdaFunctionsParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    region: str = Field("", description="Region to list functions in.")


class LambdaFunction(sdl.Entity):
    function_name: str = ""
    runtime: str = ""
    handler: str = ""
    memory_mb: int = 0
    timeout_seconds: int = 0
    last_modified: str = ""


class LambdaFunctionList(sdl.Entity):
    functions: list[LambdaFunction] = []


class InvokeLambdaParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    region: str = Field("", description="Region the function lives in.")
    function_name: str = Field(..., description="Name or ARN of the Lambda function to invoke.")
    payload_json: str = Field("{}", description="JSON payload to pass as the function's event input.")


class LambdaInvokeResult(sdl.Entity):
    function_name: str = ""
    status_code: int = 0
    response_json: str = ""
    error: str = ""


# ──────────────────────────────────────────────────────────────────────────
# IAM
# ──────────────────────────────────────────────────────────────────────────


class ListIamUsersParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")


class IamUser(sdl.Entity):
    user_name: str = ""
    user_id: str = ""
    arn: str = ""
    created_at: str = ""


class IamUserList(sdl.Entity):
    users: list[IamUser] = []


class ListIamRolesParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")


class IamRole(sdl.Entity):
    role_name: str = ""
    role_id: str = ""
    arn: str = ""
    created_at: str = ""


class IamRoleList(sdl.Entity):
    roles: list[IamRole] = []


class GetCallerIdentityParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")


class CallerIdentity(sdl.Entity):
    account_id: str = ""
    arn: str = ""
    user_id: str = ""


# ──────────────────────────────────────────────────────────────────────────
# CloudWatch
# ──────────────────────────────────────────────────────────────────────────


class ListAlarmsParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    region: str = Field("", description="Region to list alarms in.")
    state: str = Field("", description="Filter by alarm state: OK, ALARM, INSUFFICIENT_DATA. Leave empty for all.")


class CloudWatchAlarm(sdl.Entity):
    alarm_name: str = ""
    state: str = ""
    metric_name: str = ""
    namespace: str = ""
    comparison_operator: str = ""
    threshold: float = 0.0


class CloudWatchAlarmList(sdl.Entity):
    alarms: list[CloudWatchAlarm] = []


class GetMetricStatisticsParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    region: str = Field("", description="Region the metric lives in.")
    namespace: str = Field(..., description="CloudWatch namespace, e.g. AWS/EC2, AWS/Lambda, AWS/RDS.")
    metric_name: str = Field(..., description="Metric name, e.g. CPUUtilization, Invocations, Errors.")
    dimension_name: str = Field("", description="Dimension to filter by, e.g. InstanceId.")
    dimension_value: str = Field("", description="Value of the dimension, e.g. i-0123456789abcdef0.")
    period_seconds: int = Field(300, description="Granularity of the returned datapoints, in seconds.")
    hours_back: int = Field(24, description="How many hours of history to fetch.")
    statistic: str = Field("Average", description="Statistic to compute: Average, Sum, Minimum, Maximum, SampleCount.")


class MetricDatapoint(sdl.Entity):
    timestamp: str = ""
    value: float = 0.0
    unit: str = ""


class MetricStatisticsResult(sdl.Entity):
    metric_name: str = ""
    namespace: str = ""
    datapoints: list[MetricDatapoint] = []


# ──────────────────────────────────────────────────────────────────────────
# Cost Explorer
# ──────────────────────────────────────────────────────────────────────────


class GetCostAndUsageParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    days_back: int = Field(30, description="How many days of cost history to fetch.")
    granularity: str = Field("DAILY", description="DAILY or MONTHLY.")
    group_by_service: bool = Field(True, description="Break the totals down by AWS service.")


class CostByService(sdl.Entity):
    service: str = ""
    amount_usd: float = 0.0


class CostAndUsageResult(sdl.Entity):
    total_amount_usd: float = 0.0
    period_start: str = ""
    period_end: str = ""
    by_service: list[CostByService] = []


class GetCostForecastParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    days_forward: int = Field(30, description="How many days ahead to forecast.")


class CostForecastResult(sdl.Entity):
    total_forecast_usd: float = 0.0
    period_start: str = ""
    period_end: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Overview / dashboard (Tier 3 value-add)
# ──────────────────────────────────────────────────────────────────────────


class GetCloudOverviewParams(BaseModel):
    connection_id: str = Field("", description="ID of the AWS connection to use.")
    region: str = Field("", description="Region to summarize. Leave empty to use the connection's default region.")


class CloudOverview(sdl.Entity):
    ec2_running: int = 0
    ec2_stopped: int = 0
    s3_bucket_count: int = 0
    rds_instance_count: int = 0
    lambda_function_count: int = 0
    alarms_in_alarm_state: int = 0
    month_to_date_cost_usd: float = 0.0
