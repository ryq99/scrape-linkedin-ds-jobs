#!/usr/bin/env bash
set -euo pipefail

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not found. Install AWS CLI v2 first."
  exit 1
fi

ENV_FILE="${1:-infra/aws.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file not found: $ENV_FILE"
  echo "Create it from infra/aws.env.example"
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

: "${AWS_REGION:?Missing AWS_REGION}"
: "${ECR_REPOSITORY:?Missing ECR_REPOSITORY}"
: "${ECS_CLUSTER:?Missing ECS_CLUSTER}"
: "${ECS_TASK_FAMILY:?Missing ECS_TASK_FAMILY}"
: "${CONTAINER_NAME:?Missing CONTAINER_NAME}"
: "${LOG_GROUP:?Missing LOG_GROUP}"
: "${TASK_CPU:?Missing TASK_CPU}"
: "${TASK_MEMORY:?Missing TASK_MEMORY}"
: "${ECS_CPU_ARCHITECTURE:=X86_64}"
: "${ECS_TASK_EXEC_ROLE_ARN:?Missing ECS_TASK_EXEC_ROLE_ARN}"
: "${ECS_TASK_ROLE_ARN:?Missing ECS_TASK_ROLE_ARN}"
: "${SUBNET_IDS:?Missing SUBNET_IDS}"
: "${SECURITY_GROUP_IDS:?Missing SECURITY_GROUP_IDS}"
: "${ASSIGN_PUBLIC_IP:?Missing ASSIGN_PUBLIC_IP}"
: "${S3_PREFIX:?Missing S3_PREFIX}"
: "${LINKEDIN_USER_PARAM:?Missing LINKEDIN_USER_PARAM}"
: "${LINKEDIN_PWD_PARAM:?Missing LINKEDIN_PWD_PARAM}"
: "${SCHEDULE_NAME:?Missing SCHEDULE_NAME}"
: "${SCHEDULE_EXPRESSION:?Missing SCHEDULE_EXPRESSION}"
: "${SCHEDULE_TIMEZONE:?Missing SCHEDULE_TIMEZONE}"
: "${SCHEDULER_ROLE_ARN:?Missing SCHEDULER_ROLE_ARN}"

if [[ "${AWS_ACCOUNT_ID:-}" == "123456789012" ]] \
  || [[ "$ECS_TASK_EXEC_ROLE_ARN" == *"123456789012"* ]] \
  || [[ "$ECS_TASK_ROLE_ARN" == *"123456789012"* ]] \
  || [[ "$SCHEDULER_ROLE_ARN" == *"123456789012"* ]]; then
  echo "Detected placeholder account/role values in ${ENV_FILE}."
  echo "Replace 123456789012 and example role ARNs with real values from your AWS account."
  exit 1
fi

if [[ -z "${AWS_ACCOUNT_ID:-}" ]]; then
  AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "$AWS_REGION")"
fi

IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:${IMAGE_TAG}"

json_array_from_csv() {
  local csv="$1"
  IFS=',' read -r -a items <<< "$csv"
  local out="["
  local i
  for i in "${!items[@]}"; do
    local trimmed
    trimmed="$(echo "${items[$i]}" | xargs)"
    out+="\"${trimmed}\""
    if [[ "$i" -lt "$((${#items[@]} - 1))" ]]; then
      out+=","
    fi
  done
  out+="]"
  echo "$out"
}

SUBNET_JSON="$(json_array_from_csv "$SUBNET_IDS")"
SECGROUP_JSON="$(json_array_from_csv "$SECURITY_GROUP_IDS")"

echo "Ensuring ECS cluster exists: ${ECS_CLUSTER}"
aws ecs describe-clusters --clusters "$ECS_CLUSTER" --region "$AWS_REGION" --query 'clusters[0].clusterName' --output text 2>/dev/null | grep -q "$ECS_CLUSTER" \
  || aws ecs create-cluster --cluster-name "$ECS_CLUSTER" --region "$AWS_REGION" >/dev/null

echo "Ensuring CloudWatch log group exists: ${LOG_GROUP}"
aws logs create-log-group --log-group-name "$LOG_GROUP" --region "$AWS_REGION" >/dev/null 2>&1 || true

TASK_DEF_FILE="$(mktemp)"
cat > "$TASK_DEF_FILE" <<JSON
{
  "family": "${ECS_TASK_FAMILY}",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "${TASK_CPU}",
  "memory": "${TASK_MEMORY}",
  "runtimePlatform": {
    "cpuArchitecture": "${ECS_CPU_ARCHITECTURE}",
    "operatingSystemFamily": "LINUX"
  },
  "executionRoleArn": "${ECS_TASK_EXEC_ROLE_ARN}",
  "taskRoleArn": "${ECS_TASK_ROLE_ARN}",
  "containerDefinitions": [
    {
      "name": "${CONTAINER_NAME}",
      "image": "${IMAGE_URI}",
      "essential": true,
      "environment": [
        {"name": "AWS_REGION", "value": "${AWS_REGION}"},
        {"name": "S3_PREFIX", "value": "${S3_PREFIX}"},
        {"name": "LINKEDIN_USER_PARAM", "value": "${LINKEDIN_USER_PARAM}"},
        {"name": "LINKEDIN_PWD_PARAM", "value": "${LINKEDIN_PWD_PARAM}"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "${LOG_GROUP}",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
JSON

echo "Registering task definition"
TASK_DEF_ARN="$(aws ecs register-task-definition \
  --cli-input-json "file://${TASK_DEF_FILE}" \
  --region "$AWS_REGION" \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)"

TARGET_FILE="$(mktemp)"
cat > "$TARGET_FILE" <<JSON
{
  "RoleArn": "${SCHEDULER_ROLE_ARN}",
  "Arn": "arn:aws:ecs:${AWS_REGION}:${AWS_ACCOUNT_ID}:cluster/${ECS_CLUSTER}",
  "EcsParameters": {
    "LaunchType": "FARGATE",
    "TaskDefinitionArn": "${TASK_DEF_ARN}",
    "NetworkConfiguration": {
      "awsvpcConfiguration": {
        "Subnets": ${SUBNET_JSON},
        "SecurityGroups": ${SECGROUP_JSON},
        "AssignPublicIp": "${ASSIGN_PUBLIC_IP}"
      }
    }
  }
}
JSON

echo "Creating/updating EventBridge Scheduler schedule: ${SCHEDULE_NAME}"
if aws scheduler get-schedule --name "$SCHEDULE_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
  aws scheduler update-schedule \
    --name "$SCHEDULE_NAME" \
    --schedule-expression "$SCHEDULE_EXPRESSION" \
    --schedule-expression-timezone "$SCHEDULE_TIMEZONE" \
    --flexible-time-window '{"Mode":"OFF"}' \
    --target "file://${TARGET_FILE}" \
    --region "$AWS_REGION" >/dev/null
else
  aws scheduler create-schedule \
    --name "$SCHEDULE_NAME" \
    --schedule-expression "$SCHEDULE_EXPRESSION" \
    --schedule-expression-timezone "$SCHEDULE_TIMEZONE" \
    --flexible-time-window '{"Mode":"OFF"}' \
    --target "file://${TARGET_FILE}" \
    --region "$AWS_REGION" >/dev/null
fi

rm -f "$TASK_DEF_FILE" "$TARGET_FILE"

echo
echo "Done."
echo "Task definition ARN: ${TASK_DEF_ARN}"
echo "Schedule name: ${SCHEDULE_NAME}"
