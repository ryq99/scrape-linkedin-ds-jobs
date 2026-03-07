# LinkedIn Job Scraping
Job scraping for data science jobs on LinkedIn

## Deploy to AWS ECS Fargate (Scheduled)

### 1) Prerequisites
- Install AWS CLI v2 and Docker
- Configure AWS credentials: `aws configure`
- Create IAM roles first:
  - ECS task execution role (`ECS_TASK_EXEC_ROLE_ARN`)
  - ECS task role (`ECS_TASK_ROLE_ARN`) with `ssm:GetParameter`, `kms:Decrypt`, `s3:PutObject`
  - EventBridge Scheduler role (`SCHEDULER_ROLE_ARN`) with `ecs:RunTask` and `iam:PassRole`

### 2) Configure environment file
```bash
cp infra/aws.env.example infra/aws.env
# then edit infra/aws.env with your account/network/role values
```

### 3) Push Docker image to ECR
```bash
./scripts/push_to_ecr.sh infra/aws.env
```

### 4) Register ECS task + create/update daily schedule
```bash
./scripts/setup_ecs_schedule.sh infra/aws.env
```

### 5) Monitor
- ECS task logs: CloudWatch log group in `LOG_GROUP`
- Manual one-off run: `aws ecs run-task` using the registered task definition
