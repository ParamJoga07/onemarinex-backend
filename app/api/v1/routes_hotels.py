from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models.hotels import Hotel
from typing import List, Optional

router = APIRouter()

# Get all hotels
@router.get("/")
def get_hotels(
    max_dist: Optional[float] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Hotel)
    if max_dist is not None:
        query = query.filter(Hotel.distance_from_port <= max_dist)
    if min_price is not None:
        query = query.filter(Hotel.price_per_night >= min_price)
    if max_price is not None:
        query = query.filter(Hotel.price_per_night <= max_price)
    
    hotels = query.all()
    return hotels

# Get hotel by id
@router.get("/{id}")
def get_hotel(id: int, db: Session = Depends(get_db)):
    hotel = db.query(Hotel).filter(Hotel.id == id).first()
    if not hotel:
        raise HTTPException(status_code=404, detail="Hotel not found")
    return hotel
