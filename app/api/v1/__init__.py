from fastapi import APIRouter

from app.api.v1.admin_audit_logs import router as admin_audit_logs_router
from app.api.v1.admin_cities import router as admin_cities_router
from app.api.v1.admin_clients import router as admin_clients_router
from app.api.v1.admin_districts import router as admin_districts_router
from app.api.v1.admin_drivers import router as admin_drivers_router
from app.api.v1.admin_orders import router as admin_orders_router
from app.api.v1.admin_route_tariffs import router as admin_route_tariffs_router
from app.api.v1.admin_settings import router as admin_settings_router
from app.api.v1.auth import admin_router as admin_users_router
from app.api.v1.auth import router as auth_router
from app.api.v1.cities import router as cities_router
from app.api.v1.client_profile import router as client_profile_router
from app.api.v1.client_orders import router as client_orders_router
from app.api.v1.driver import router as driver_router
from app.api.v1.disputes import router as disputes_router
from app.api.v1.files import router as files_router
from app.api.v1.geo import router as geo_router
from app.api.v1.health import router as health_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.route_tariffs import router as route_tariffs_router

api_router = APIRouter()
api_router.include_router(auth_router, tags=["Auth"])
api_router.include_router(files_router, tags=["Files"])
api_router.include_router(geo_router, tags=["Geo"])
api_router.include_router(cities_router, tags=["Cities"])
api_router.include_router(client_profile_router, tags=["Client Profile"])
api_router.include_router(client_orders_router, tags=["Client Orders"])
api_router.include_router(driver_router, tags=["Driver Profile", "Driver Orders", "Driver Bids", "Order Status"])
api_router.include_router(disputes_router, tags=["Disputes", "Admin Disputes"])
api_router.include_router(route_tariffs_router, tags=["Route Tariffs"])
api_router.include_router(notifications_router, tags=["Notifications"])
api_router.include_router(admin_orders_router, tags=["Admin Orders"])
api_router.include_router(admin_drivers_router, tags=["Admin Drivers"])
api_router.include_router(admin_clients_router, tags=["Admin Clients"])
api_router.include_router(admin_audit_logs_router, tags=["Audit Logs"])
api_router.include_router(admin_users_router, tags=["Admin Users"])
api_router.include_router(admin_cities_router, tags=["Cities"])
api_router.include_router(admin_districts_router, tags=["Districts"])
api_router.include_router(admin_route_tariffs_router, tags=["Route Tariffs"])
api_router.include_router(admin_settings_router, tags=["Admin Settings"])
api_router.include_router(health_router, tags=["Health"])
