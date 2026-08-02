from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Set
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.chat import ChatMessage
from app.db.models.port import Port
from app.db.models.chat_moderation_event import ChatModerationEvent
from app.services.chat_moderation import moderate_message
from app.api.v1.routes_auth import get_current_user
# If get_current_user requires Bearer we'll need to parse token for WS manually or use query params.

router = APIRouter()

# --- Connection Manager for WebSockets ---
class ConnectionManager:
    def __init__(self):
        # Maps port_id -> set of active WebSockets
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        # We can also keep track of users per port if needed: maps port_id -> set of user_ids
        self.active_users: Dict[int, Set[int]] = {}

    async def connect(self, websocket: WebSocket, port_id: int, user_id: int):
        await websocket.accept()
        if port_id not in self.active_connections:
            self.active_connections[port_id] = set()
            self.active_users[port_id] = set()
            
        self.active_connections[port_id].add(websocket)
        self.active_users[port_id].add(user_id)
        
        # Broadcast that the count changed
        await self.broadcast_system_message(port_id, "user_joined", {"online_count": self.get_online_count(port_id)})

    def disconnect(self, websocket: WebSocket, port_id: int, user_id: int):
        if port_id in self.active_connections:
            if websocket in self.active_connections[port_id]:
                self.active_connections[port_id].remove(websocket)
            # Remove user_id logic: ideally reference counted or loop through all sockets to see if user is still connected.
            # For simplicity, if one socket disconnects, let's just assume one user session.
            if user_id in self.active_users[port_id]:
                self.active_users[port_id].discard(user_id)
                
            if len(self.active_connections[port_id]) == 0:
                del self.active_connections[port_id]
                del self.active_users[port_id]
                
    def get_online_count(self, port_id: int) -> int:
        users = self.active_users.get(port_id)
        return len(users) if users is not None else 0

    async def broadcast(self, port_id: int, message: str, sender: User):
        print(f"[WS] Broadcasting to port {port_id}: {message} from {sender.email}")
        if port_id in self.active_connections:
            payload = {
                "type": "chat_message",
                "data": {
                    "user_id": sender.id,
                    "name": sender.name or sender.email,
                    "role": sender.role,
                    "message": message,
                    "created_at": datetime.utcnow().isoformat()
                }
            }
            json_payload = json.dumps(payload)
            # Send to all connected sockets for this port
            for connection in self.active_connections[port_id]:
                try:
                    await connection.send_text(json_payload)
                except Exception:
                    pass
                    
    async def broadcast_system_message(self, port_id: int, event_type: str, data: dict):
        if port_id in self.active_connections:
            payload = {
                "type": "system",
                "event": event_type,
                "data": data
            }
            json_payload = json.dumps(payload)
            for connection in self.active_connections[port_id]:
                try:
                    await connection.send_text(json_payload)
                except Exception:
                    pass

manager = ConnectionManager()

# --- HTTP Endpoints ---

@router.get("/channels")
def get_channels(db: Session = Depends(get_db)):
    """Fetch all ports that acts as chat channels."""
    ports = db.query(Port).filter(Port.is_active == True).all()
    result = []
    for port in ports:
        result.append({
            "id": port.id,
            "name": port.name,
            "code": port.code,
            "online_count": manager.get_online_count(port.id)
        })
    return result

@router.get("/{port_id}/messages")
def get_chat_history(port_id: int, limit: int = 50, db: Session = Depends(get_db)):
    """Fetch past messages for a channel."""
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.port_id == port_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    # Reverse so oldest is first or frontend can handle sorting
    for m in messages[::-1]:
        sender = db.query(User).filter(User.id == m.user_id).first()
        result.append({
            "id": m.id,
            "user_id": m.user_id,
            "name": sender.name or sender.email if sender else "Unknown User",
            "role": sender.role if sender else "user",
            "message": m.message,
            "created_at": m.created_at.isoformat() if m.created_at else None
        })
    return result


@router.get("/moderation-config")
def get_moderation_config(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get moderation config for frontend (authenticated crew only).

    Only crew members can access community chat moderation config.
    """
    if current_user.role != "crew":
        raise HTTPException(status_code=403, detail="Crew access required for community chat")

    from app.db.models.chat_moderation_setting import ChatModerationSetting
    settings = db.query(ChatModerationSetting).filter(ChatModerationSetting.id == 1).first()
    if not settings:
        settings = ChatModerationSetting(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return {
        "max_message_length": settings.max_message_length,
    }


# --- WebSocket Endpoint ---
from jose import jwt
from app.core.config import settings

def get_user_from_token(token: str, db: Session) -> User:
    try:
        logger.info(f"🔴 get_user_from_token called with token: {token[:20]}...")
        # The token sub contains the email, not the ID
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub")
        logger.info(f"🔴 Decoded email from token: {email}")
        if email is None:
            logger.error("🔴 Email is None from token")
            return None
        user = db.query(User).filter(User.email == email).first()
        logger.info(f"🔴 User from DB: {user.email if user else 'NOT FOUND'}")
        return user
    except Exception as e:
        logger.error(f"🔴 Token decode error: {e}")
        return None

@router.websocket("/ws/{port_id}")
async def websocket_endpoint(websocket: WebSocket, port_id: int, token: str = Query(...), db: Session = Depends(get_db)):
    logger.info("🔴 ENTERED websocket_endpoint")
    user = get_user_from_token(token, db)
    if not user:
        logger.error("🔴 NO USER FROM TOKEN")
        await websocket.close(code=1008)  # Policy Violation
        return

    # Check if port exists
    port = db.query(Port).filter(Port.id == port_id, Port.is_active == True).first()
    if not port:
        logger.error(f"🔴 PORT {port_id} NOT FOUND")
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, port_id, user.id)
    logger.info(f"🔴 User {user.id} ({user.email}) connected to port {port_id}")
    try:
        while True:
            # Receive message
            data = await websocket.receive_text()
            logger.info(f"🔴 Received data from user {user.id} on port {port_id}: {data}")
            try:
                msg_data = json.loads(data)
                text = msg_data.get("message", "").strip()

                if text:
                    logger.info(f"🔴 ABOUT TO CALL moderate_message for: {text}")
                    result = await moderate_message(db, user.id, port_id, text)
                    logger.info(f"🔴 MODERATION RESULT: rejected={result.rejected}, code={result.code}, matched_term={result.matched_term}")

                    if result.rejected:
                        error_messages = {
                            "empty": "Message cannot be empty.",
                            "too_long": "Message exceeds maximum length.",
                            "rate_limited": "You are sending messages too quickly. Please slow down.",
                            "duplicate": "This message was just sent. Please send something different.",
                            "contact_info": "Messages cannot contain contact information.",
                            "payment_info": "Messages cannot contain payment information.",
                            "external_link": "Messages cannot contain external links.",
                            "spam": "Message looks like spam.",
                            "restricted_word": "Message contains restricted words.",
                            "charset": "Message looks like keyboard-smash.",
                            "language_violation": "Messages must be in English.",
                            "guidelines_violation": "Message violates community guidelines.",
                            "ai_unavailable": "Message couldn't be checked right now — please try again.",
                        }
                        error_msg = error_messages.get(result.code, "Message was rejected.")

                        await websocket.send_json({
                            "type": "error",
                            "data": {
                                "code": result.code,
                                "message": error_msg,
                            },
                        })

                        event = ChatModerationEvent(
                            port_id=port_id,
                            user_id=user.id,
                            raw_message=text,
                            normalized_message=text.lower(),
                            decision="rejected",
                            rejected_by=result.rejected_by,
                            reason_code=result.reason_code,
                            matched_term=result.matched_term,
                            ai_route=result.ai_route,
                            ai_model=result.ai_model,
                            ai_latency_ms=result.ai_latency_ms,
                        )
                        db.add(event)
                        try:
                            db.commit()
                        except Exception:
                            db.rollback()
                        continue

                    new_msg = ChatMessage(port_id=port_id, user_id=user.id, message=text)
                    db.add(new_msg)
                    db.commit()

                    event = ChatModerationEvent(
                        port_id=port_id,
                        user_id=user.id,
                        chat_message_id=new_msg.id,
                        raw_message=text,
                        normalized_message=text.lower(),
                        decision="allowed",
                        rejected_by="backend",
                    )
                    db.add(event)
                    try:
                        db.commit()
                    except Exception:
                        db.rollback()

                    await manager.broadcast(port_id, text, user)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket, port_id, user.id)
        print(f"[WS] User {user.id} disconnected from port {port_id}")
        # Broadcast updated count
        await manager.broadcast_system_message(port_id, "user_left", {"online_count": manager.get_online_count(port_id)})
