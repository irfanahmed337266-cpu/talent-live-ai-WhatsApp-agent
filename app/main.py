from fastapi import FastAPI

from app.api.telegram import router as telegram_router
from app.api.dashboard import router as dashboard_router

app = FastAPI(
    title="Talent Live AI Telegram Talent Agent",
    version="1.0.0",
    description="AI-powered Telegram talent screening agent",
)

app.include_router(telegram_router)
app.include_router(dashboard_router)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "talent-live-agent",
    }