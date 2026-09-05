from fastapi import APIRouter

from app.api.v1.endpoints import sitemap

router = APIRouter()
router.include_router(sitemap.router, prefix="", tags=["sitemap"])
