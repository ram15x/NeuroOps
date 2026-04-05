from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from backend.models.database import get_db, Service
from backend.api.auth import get_current_user

router = APIRouter()


class ServiceCreate(BaseModel):
    service_name: str
    business_impact: int = 10
    sla_minutes: int = 5
    on_call_group: str = "default"


class ServiceUpdate(BaseModel):
    business_impact: Optional[int] = None
    sla_minutes: Optional[int] = None
    on_call_group: Optional[str] = None


class ServiceResponse(BaseModel):
    id: int
    service_name: str
    business_impact: int
    sla_minutes: int
    on_call_group: str
    created_at: str
    updated_at: str


@router.get("/services", response_model=List[ServiceResponse])
def list_services(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List all services with their business impact configuration"""
    services = db.query(Service).order_by(Service.business_impact.desc()).all()
    return [
        {
            "id": s.id,
            "service_name": s.service_name,
            "business_impact": s.business_impact,
            "sla_minutes": s.sla_minutes,
            "on_call_group": s.on_call_group,
            "created_at": s.created_at.isoformat() if s.created_at else "",
            "updated_at": s.updated_at.isoformat() if s.updated_at else ""
        }
        for s in services
    ]


@router.post("/services")
def create_service(
    data: ServiceCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Create a new service with business impact configuration"""
    existing = db.query(Service).filter(Service.service_name == data.service_name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Service already exists")
    
    service = Service(
        service_name=data.service_name,
        business_impact=data.business_impact,
        sla_minutes=data.sla_minutes,
        on_call_group=data.on_call_group
    )
    db.add(service)
    db.commit()
    db.refresh(service)
    
    return {
        "id": service.id,
        "service_name": service.service_name,
        "business_impact": service.business_impact,
        "sla_minutes": service.sla_minutes,
        "on_call_group": service.on_call_group,
        "message": "Service created successfully"
    }


@router.put("/services/{service_id}")
def update_service(
    service_id: int,
    data: ServiceUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Update business impact for a service"""
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    if data.business_impact is not None:
        service.business_impact = data.business_impact
    if data.sla_minutes is not None:
        service.sla_minutes = data.sla_minutes
    if data.on_call_group is not None:
        service.on_call_group = data.on_call_group
    
    db.commit()
    db.refresh(service)
    
    return {
        "id": service.id,
        "service_name": service.service_name,
        "business_impact": service.business_impact,
        "sla_minutes": service.sla_minutes,
        "on_call_group": service.on_call_group,
        "message": "Service updated successfully"
    }


@router.delete("/services/{service_id}")
def delete_service(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete a service configuration"""
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    db.delete(service)
    db.commit()
    
    return {"message": "Service deleted successfully"}


@router.get("/services/impact/{service_name}")
def get_service_impact(
    service_name: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get business impact for a specific service"""
    service = db.query(Service).filter(Service.service_name == service_name).first()
    if not service:
        # Return default if not configured
        return {"service_name": service_name, "business_impact": 10, "configured": False}
    
    return {
        "service_name": service.service_name,
        "business_impact": service.business_impact,
        "sla_minutes": service.sla_minutes,
        "on_call_group": service.on_call_group,
        "configured": True
    }