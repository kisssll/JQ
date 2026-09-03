from app.api.v1.endpoints import favorites, sitemap
router.include_router(sitemap.router, prefix="", tags=["sitemap"])