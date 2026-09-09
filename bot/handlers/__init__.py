"""Routers, registered in this order by `bot.main`."""

from bot.handlers.admin import router as admin_router
from bot.handlers.group import router as group_router
from bot.handlers.review import router as review_router

routers = [admin_router, review_router, group_router]

__all__ = ["admin_router", "group_router", "review_router", "routers"]
