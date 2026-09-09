"""Routers, registered in this order by `bot.main`."""

from bot.handlers.admin import router as admin_router
from bot.handlers.group import router as group_router
from bot.handlers.review import router as review_router
from bot.handlers.testing import router as testing_router

# The group router ends with a catch-all message handler, so it goes last.
routers = [admin_router, review_router, testing_router, group_router]

__all__ = ["admin_router", "group_router", "review_router", "routers", "testing_router"]
