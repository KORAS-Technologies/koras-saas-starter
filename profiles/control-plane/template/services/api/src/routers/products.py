from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from ..core.auth import PlatformAuthDep

router = APIRouter(tags=["products"])


class ProductRegistrationRequest(BaseModel):
    name: str
    slug: str
    github_repo: str
    supabase_projects: dict[str, str]
    vercel_projects: dict[str, str]
    fly_apps: dict[str, str]
    zitadel_project: str


class ProductRegistrationResponse(BaseModel):
    id: str
    slug: str
    status: str


@router.post(
    "/products",
    response_model=ProductRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_product(
    body: ProductRegistrationRequest,
    _claims: PlatformAuthDep,
) -> ProductRegistrationResponse:
    # Business logic implemented in the dedicated Control Plane master prompt
    return ProductRegistrationResponse(
        id="placeholder",
        slug=body.slug,
        status="registered",
    )


@router.get("/products")
async def list_products(_claims: PlatformAuthDep) -> list[dict]:
    return []
