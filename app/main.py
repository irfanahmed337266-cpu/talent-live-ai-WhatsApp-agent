from fastapi import FastAPI

app = FastAPI(
    title="Talent Live AI WhatsApp Agent",
    version="1.0.0",
    description="AI-powered WhatsApp talent screening agent",
)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "talent-live-agent",
    }