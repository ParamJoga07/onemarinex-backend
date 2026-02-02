from fastapi import APIRouter

router = APIRouter()

@router.post("/")
def contact(name: str, email: str, message: str):
    return {"message": f"Thanks {name}, we received your message."}
