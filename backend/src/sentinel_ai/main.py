from fastapi import FastAPI

from sentinel_ai.api import health

app = FastAPI(title="Sentinel AI", version="0.1.0")
app.include_router(health.router, prefix="/api/v1")
