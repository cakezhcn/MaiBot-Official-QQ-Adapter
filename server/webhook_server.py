from fastapi import FastAPI, HTTPException


class WebhookServer:
    def __init__(self):
        self.app = FastAPI()

        @self.app.post("/webhook")
        async def handle_webhook(data: dict):
            # Process incoming data here
            if 'event' not in data:
                raise HTTPException(status_code=400, detail="Invalid data")
            return {"status": "success"}


webhook_server = WebhookServer()
