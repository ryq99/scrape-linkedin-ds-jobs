import json
import boto3
import sagemaker
from sagemaker import get_execution_role
from sagemaker.processing import ScriptProcessor

from sagemaker.workflow.steps import ProcessingStep
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.pipeline_context import PipelineSession


region = "us-west-2"
role = "arn:aws:iam::316018694217:role/service-role/AmazonSageMaker-ExecutionRole-20230309T110736"
img_uri = "316018694217.dkr.ecr.us-west-2.amazonaws.com/ds-scrape:latest"
pipeline_name = "DataScienceJobScrape"
processing_instance_count = 1
instance_type = "ml.t3.medium"

print(f"region: {region}")
print(f"role: {role}")

# Define processing env based on customized Docker container in ECR
script_processor = ScriptProcessor(
    command=["python3"],
    image_uri= img_uri,
    role=role,
    instance_count=1,
    instance_type= instance_type,
)

# Define Steps
step_scrape = ProcessingStep(
    name="ds-scrape",
    processor=script_processor,
    inputs=None,
    outputs=None,
    code="src/scrape.py",
)

# Define pipeline
pipeline = Pipeline(
    name=pipeline_name,
    parameters=[processing_instance_count],
    steps=[step_scrape],
)


if __name__ == "__main__":
    print(f"SageMaker Pipeline Definition: \n{json.loads(pipeline.definition())}")

    print("submitting sagemaker pipeline.")
    pipeline.upsert(role_arn=role)

    print("start sagemaker pipeline.")
    execution = pipeline.start()

    print(f"SageMaker Pipeline Description: {execution.describe()}")
    status = execution.describe()['PipelineExecutionStatus']
    if status == 'Succeeded':
        print('Pipeline execution completed successfully!')
    elif status == 'Failed':
        print('Pipeline execution failed.')
    else:
        print(f'Pipeline execution is still in progress. Status: {status}')