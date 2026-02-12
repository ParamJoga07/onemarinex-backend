from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.db.session import get_db
from app.db.models.restaurant import Restaurant

router = APIRouter()

@router.get("/")
def get_restaurants(
    max_dist: Optional[float] = None,
    max_price: Optional[float] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Restaurant)
    if max_dist is not None:
        query = query.filter(Restaurant.distance_from_port <= max_dist)
    if max_price is not None:
        query = query.filter(Restaurant.price_per_person <= max_price)
    
    return query.all()

@router.get("/{id}")
def get_restaurant(id: int, db: Session = Depends(get_db)):
    restaurant = db.query(Restaurant).filter(Restaurant.id == id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return restaurant
