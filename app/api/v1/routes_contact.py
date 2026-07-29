from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models.contact_message import ContactMessage
from app.services.email import send_contact_message, send_email

router = APIRouter()

from pydantic import BaseModel

class ContactIn(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: str
    message: str

@router.post("/")
def contact(body: ContactIn, background: BackgroundTasks, db: Session = Depends(get_db)):
    db_msg = ContactMessage(
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        phone=body.phone,
        message=body.message
    )
    db.add(db_msg)
    db.commit()
    db.refresh(db_msg)

    # Forward to the support inbox and acknowledge the sender (after the
    # response — mail latency shouldn't slow the form down).
    background.add_task(
        send_contact_message,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        phone=body.phone,
        message=body.message,
    )
    background.add_task(
        send_email,
        body.email,
        "We received your message — HeyPorts",
        (
            f"Hi {body.first_name},\n\n"
            "Thanks for reaching out to HeyPorts. We've received your message "
            "and our team will get back to you soon.\n\n"
            f"Your message:\n{body.message}\n\n"
            "— HeyPorts Support"
        ),
    )
    return {"message": f"Thanks {body.first_name}, we received your message."}
