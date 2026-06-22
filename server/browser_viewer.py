from fastapi import WebSocket, Request, APIRouter
from fastapi.templating import Jinja2Templates
from typing import List

import base64

templates = Jinja2Templates(directory="templates")
router = APIRouter()

class BrowserManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message:str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(connection)


manager = BrowserManager()

@router.get("/")
async def get_page(request: Request):
    return templates.TemplateResponse("message.html", {"request": request, "message": "Waiting..."})


@router.websocket("/ws-browser")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        manager.disconnect(websocket)
