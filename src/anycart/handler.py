"""AWS Lambda entry point: API Gateway (HTTP API) events -> the FastAPI app."""

from mangum import Mangum

from anycart.api import app

handler = Mangum(app, lifespan="off")
