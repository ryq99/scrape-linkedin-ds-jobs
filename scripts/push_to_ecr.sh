#!/usr/bin/env bash
set -euo pipefail

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not found. Install AWS CLI v2 first."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found. Install/start Docker first."
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

if [[ -z "${AWS_ACCOUNT_ID:-}" ]]; then
  AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "$AWS_REGION")"
fi

IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_PLATFORM="${IMAGE_PLATFORM:-linux/amd64}"
IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:${IMAGE_TAG}"

echo "Ensuring ECR repo exists: ${ECR_REPOSITORY}"
aws ecr describe-repositories --repository-names "$ECR_REPOSITORY" --region "$AWS_REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$ECR_REPOSITORY" --region "$AWS_REGION" >/dev/null

echo "Logging in to ECR"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "Building image: ${IMAGE_URI} (platform=${IMAGE_PLATFORM})"
docker build --platform "${IMAGE_PLATFORM}" -t "${ECR_REPOSITORY}:${IMAGE_TAG}" .
docker tag "${ECR_REPOSITORY}:${IMAGE_TAG}" "$IMAGE_URI"

echo "Pushing image: ${IMAGE_URI}"
docker push "$IMAGE_URI"

echo
echo "Done. IMAGE_URI=${IMAGE_URI}"
