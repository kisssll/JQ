from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import xml.etree.ElementTree as ET
from datetime import datetime
import os

from app.db.session import get_db
from app.models.models import Salon, Master

router = APIRouter()

# Генерируем секретный путь (можно поменять на свой)
# Например: /sitemap-9f7e3a1c5b2d.xml
SECRET_PATH = os.getenv("SITEMAP_SECRET_PATH", "sitemap-9f7e3a1c5b2d")

@router.get(f"/{SECRET_PATH}.xml", response_class=Response)
async def get_sitemap(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Скрытая карта сайта. Доступна только по секретному URL.
    """
    # Проверяем, что запрос пришел с правильным путем
    # (это уже проверено роутером, но для дополнительной безопасности)
    
    # Генерируем sitemap
    sitemap_xml = await generate_sitemap(db)
    
    return Response(
        content=sitemap_xml,
        media_type="application/xml",
        headers={
            "Cache-Control": "public, max-age=3600"
        }
    )

async def generate_sitemap(db: AsyncSession) -> str:
    """Генерирует sitemap из базы данных."""
    
    # Статические URL
    static_urls = [
        {"url": "/", "priority": "1.0000"},
        {"url": "/login", "priority": "0.8000"},
        {"url": "/salons", "priority": "0.8000"},
        {"url": "/business", "priority": "0.8000"},
        {"url": "/model", "priority": "0.8000"},
        {"url": "/about", "priority": "0.8000"},
        {"url": "/tariffs", "priority": "0.8000"},
        {"url": "/terms", "priority": "0.8000"},
        {"url": "/privacy", "priority": "0.8000"},
        {"url": "/consent", "priority": "0.8000"},
        {"url": "/offer", "priority": "0.8000"},
        {"url": "/license", "priority": "0.8000"},
        {"url": "/cookies", "priority": "0.8000"},
        {"url": "/legal", "priority": "0.8000"},
        {"url": "/forgot-password", "priority": "0.6400"},
        {"url": "/login?redirect=/model/join", "priority": "0.5120"},
    ]
    
    # Получаем салоны из БД
    salons = (await db.execute(
        select(Salon).where(Salon.is_active == True)
    )).scalars().all()
    
    # Получаем мастеров из БД (если нужны)
    masters = (await db.execute(
        select(Master).where(Master.is_active == True)
    )).scalars().all()
    
    # Создаем XML
    urlset = ET.Element(
        "urlset",
        xmlns="http://www.sitemaps.org/schemas/sitemap/0.9",
        attrib={"xmlns:xhtml": "http://www.w3.org/1999/xhtml"}
    )
    
    now = datetime.now().isoformat() + "+00:00"
    
    # Добавляем статические URL
    for item in static_urls:
        url_elem = ET.SubElement(urlset, "url")
        loc = ET.SubElement(url_elem, "loc")
        loc.text = f"https://rrumi.ru{item['url']}"
        
        lastmod = ET.SubElement(url_elem, "lastmod")
        lastmod.text = now
        
        priority = ET.SubElement(url_elem, "priority")
        priority.text = item["priority"]
    
    # Добавляем салоны
    for salon in salons:
        url_elem = ET.SubElement(urlset, "url")
        loc = ET.SubElement(url_elem, "loc")
        loc.text = f"https://rrumi.ru/salons/{salon.id}"
        
        lastmod = ET.SubElement(url_elem, "lastmod")
        lastmod.text = now
        
        priority = ET.SubElement(url_elem, "priority")
        priority.text = "0.8000"
    
    # Добавляем мастеров (опционально)
    for master in masters:
        url_elem = ET.SubElement(urlset, "url")
        loc = ET.SubElement(url_elem, "loc")
        loc.text = f"https://rrumi.ru/masters/{master.id}"
        
        lastmod = ET.SubElement(url_elem, "lastmod")
        lastmod.text = now
        
        priority = ET.SubElement(url_elem, "priority")
        priority.text = "0.6000"
    
    # Форматируем XML
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += '<?xml-stylesheet type="text/css" href="https://www.xml-sitemaps.com/css/sitemap.css"?>\n'
    xml_str += ET.tostring(urlset, encoding="unicode", method="xml")
    
    return xml_str