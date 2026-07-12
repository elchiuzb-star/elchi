Stage 5 Update: Strengthen Cities and Route Tariffs API — Professional Codex Prompt
You are updating the existing Stage 5 implementation/prompt for the Intercity Parcel Delivery Marketplace MVP.
Current Stage 5 already includes:
Cities API
Route Tariffs API
public city list
suggested price lookup
admin city management
admin route tariff management
audit logs
tests
seed data
Do not rewrite the whole business logic from scratch unless necessary.
Your task is to strengthen Stage 5 by adding the missing professional details listed below.
Important: keep the approved MVP logic unchanged.
Do not implement:
maps
coordinates
distance calculation
AI pricing
dynamic pricing
time-based pricing
weight-based pricing
size-based pricing
driver departure time
capacity logic
cargo type
cargo weight
cargo size
GPS tracking
online payment
Stage 5 must only handle:
cities
route tariffs
suggested price from database
admin management
operator read-only access
audit logs
seed data
tests

1. Keep existing endpoints
Do not change endpoint names unless the current codebase already uses different naming.
Public/authenticated endpoints:
GET /api/v1/cities
GET /api/v1/route-tariffs/suggested-price
Admin endpoints:
POST /api/v1/admin/cities
GET /api/v1/admin/cities
PATCH /api/v1/admin/cities/{city_id}

POST /api/v1/admin/route-tariffs
GET /api/v1/admin/route-tariffs
PATCH /api/v1/admin/route-tariffs/{tariff_id}
Do not add delete endpoints.
Cities and tariffs must be soft-disabled with is_active=false.

2. City model improvements
City should support MVP order and driver route forms.
Required fields:
id
name_uz
name_ru
region
is_active
created_at
updated_at
Recommended optional fields if easy and safe:
display_order
code
If these optional fields are not currently in the project, do not force them unless migration is simple and does not break existing code.
Rules:
name_uz is required.
name_uz must be unique case-insensitively.
name_ru is optional.
region is optional.
is_active defaults to true.
Hard delete is not allowed.
Existing orders and driver routes must not break if a city becomes inactive later.
Duplicate city examples that should be rejected:
Toshkent
toshkent
 TOSHKENT
Normalize city names before duplicate check:
trim spaces
case-insensitive compare
avoid duplicate whitespace

3. City search rules
GET /api/v1/cities must support search by:
name_uz
name_ru
region
Search rules:
case-insensitive
trimmed query
partial match
supports Uzbek and Russian names
Example:
search=tosh
search=Таш
search=samar
Public city list must return only active cities by default.
Admin city list may return both active and inactive cities.

4. Pagination response format
If page and limit are supported, response must use a consistent pagination object.
Do not return raw array when pagination is requested.
Recommended response:
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "uuid",
        "name_uz": "Toshkent",
        "name_ru": "Ташкент",
        "region": "Toshkent",
        "is_active": true
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 20,
      "total": 1,
      "total_pages": 1
    }
  }
}
Default values:
page = 1
limit = 20
max limit = 100
Validation:
page must be >= 1
limit must be between 1 and 100
Use the same pagination format for:
GET /api/v1/cities
GET /api/v1/admin/cities
GET /api/v1/admin/route-tariffs

5. Route tariff direction rule
Route tariffs are direction-based.
This means:
Toshkent → Samarqand
and
Samarqand → Toshkent
are two different tariffs.
Do not automatically create reverse route tariffs.
If admin wants reverse price, admin must create another tariff manually.
Example:
from_city_id = Toshkent
to_city_id = Samarqand
must not be used for:
from_city_id = Samarqand
to_city_id = Toshkent
unless a separate active tariff exists.

6. Price and currency rules
All prices must be stored as integer UZS.
Do not use float for prices.
Rules:
suggested_price is integer
min_price is integer or null
max_price is integer or null
currency is UZS
60000 means 60 000 so'm
negative prices are not allowed
Validation:
suggested_price must be >= 0
min_price must be >= 0 if provided
max_price must be >= 0 if provided
min_price <= suggested_price if min_price is provided
suggested_price <= max_price if max_price is provided
Reject invalid price ranges with:
INVALID_PRICE_RANGE
Do not calculate price from distance.
Do not calculate price from weight.
Do not calculate price from size.
Do not implement dynamic pricing.

7. Suggested price behavior
GET /api/v1/route-tariffs/suggested-price must only read active tariff from database.
Query params:
from_city_id: required UUID
to_city_id: required UUID
Validation:
from_city_id is required
to_city_id is required
from_city_id must be valid UUID
to_city_id must be valid UUID
from_city_id != to_city_id
both cities must exist
both cities must be active
If active tariff exists, return:
{
  "success": true,
  "data": {
    "from_city_id": "uuid",
    "to_city_id": "uuid",
    "from_city": {
      "id": "uuid",
      "name_uz": "Toshkent",
      "name_ru": "Ташкент"
    },
    "to_city": {
      "id": "uuid",
      "name_uz": "Samarqand",
      "name_ru": "Самарканд"
    },
    "suggested_price": 60000,
    "min_price": 50000,
    "max_price": 80000,
    "currency": "UZS",
    "is_active": true
  },
  "message": "OK"
}
If no active tariff exists, do not return 404.
Return success with null prices:
{
  "success": true,
  "data": {
    "from_city_id": "uuid",
    "to_city_id": "uuid",
    "from_city": {
      "id": "uuid",
      "name_uz": "Toshkent",
      "name_ru": "Ташкент"
    },
    "to_city": {
      "id": "uuid",
      "name_uz": "Samarqand",
      "name_ru": "Самарканд"
    },
    "suggested_price": null,
    "min_price": null,
    "max_price": null,
    "currency": "UZS",
    "is_active": false
  },
  "message": "No active tariff found for this route"
}
Reason:
Client order creation may still be allowed later even if suggested price is null.
The app can show "price will be agreed with driver" or similar frontend message.

8. Tariff and old orders rule
Route tariff is only a suggestion source.
Important rule:
When a client creates an order in later stages, backend should copy the active route_tariffs.suggested_price into orders.suggested_price at that moment.
Later tariff changes must not change old orders.
Example:
Today tariff Toshkent → Samarqand = 60000
Client creates order, orders.suggested_price = 60000
Tomorrow admin changes tariff to 70000
Old order must stay 60000
New orders may use 70000
Stage 5 does not need to implement order creation, but it must document this rule for Stage 7 integration.

9. Duplicate active route tariff constraint
Only one active tariff may exist for the same direction:
from_city_id + to_city_id + is_active=true
This should be protected at service level and database level if possible.
Recommended PostgreSQL partial unique index:
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_route_tariff
ON route_tariffs (from_city_id, to_city_id)
WHERE is_active = true;
If the project migration style uses Alembic, add this through Alembic migration.
Rules:
Creating duplicate active tariff must return ROUTE_TARIFF_ALREADY_EXISTS.
Activating inactive tariff must fail if another active tariff for same direction already exists.
Inactive duplicate tariff records may exist for history/admin purposes if needed.
Do not create duplicate active tariffs due to race conditions.

10. Inactive city rules
If a city is inactive:
Public behavior:
Inactive city must not appear in GET /api/v1/cities by default.
Inactive city must not be accepted in suggested-price lookup.
Admin behavior:
Admin can see inactive cities.
Admin can reactivate inactive cities.
Admin can update inactive cities.
Business validation for later stages:
New route tariff cannot be created with inactive city.
New driver route cannot be created with inactive city.
New client order cannot be created with inactive city.
Existing orders must not break if their city later becomes inactive.
Existing driver routes must not break immediately, but new matching should not use inactive city if project policy requires.
In Stage 5, implement only the city/tariff parts, and document the driver route/order behavior for later stages.

11. Admin and operator permissions
Follow the approved Auth rules.
Roles:
operator
admin
super_admin
Permissions:
operator:
  can view admin city list
  can view admin route tariffs
  cannot create city
  cannot update city
  cannot create route tariff
  cannot update route tariff

admin:
  can create/update city
  can create/update route tariff

super_admin:
  can create/update city
  can create/update route tariff
Blocked/inactive/deleted users cannot access admin endpoints.
Public users cannot access admin endpoints.
Client and driver cannot access admin endpoints.

12. Admin city create/update
Create city
Endpoint:
POST /api/v1/admin/cities
Access:
admin
super_admin
Request:
{
  "name_uz": "Toshkent",
  "name_ru": "Ташкент",
  "region": "Toshkent"
}
Validation:
name_uz required
name_uz unique case-insensitively
name_uz max length 120
name_ru max length 120 if provided
region max length 120 if provided
Behavior:
Create city with is_active=true.
Write audit_logs if audit service/table exists.
Return created city.
Update city
Endpoint:
PATCH /api/v1/admin/cities/{city_id}
Access:
admin
super_admin
Request:
{
  "name_uz": "Toshkent",
  "name_ru": "Ташкент",
  "region": "Toshkent",
  "is_active": true
}
Rules:
Partial update allowed.
Hard delete is not allowed.
If name_uz changes, duplicate check must still apply.
If is_active=false, existing orders must not break.
Write audit_logs with old_value and new_value if audit exists.

13. Admin route tariff create/update
Create tariff
Endpoint:
POST /api/v1/admin/route-tariffs
Access:
admin
super_admin
Request:
{
  "from_city_id": "uuid",
  "to_city_id": "uuid",
  "suggested_price": 60000,
  "min_price": 50000,
  "max_price": 80000
}
Validation:
from_city_id required
to_city_id required
from_city_id valid UUID
to_city_id valid UUID
from_city_id != to_city_id
both cities must exist
both cities must be active
suggested_price integer >= 0
min_price integer >= 0 if provided
max_price integer >= 0 if provided
min_price <= suggested_price if min_price provided
suggested_price <= max_price if max_price provided
no duplicate active tariff for same direction
Behavior:
Create active route tariff.
currency = UZS if field exists.
Write audit_logs if audit exists.
Do not create reverse tariff automatically.
Update tariff
Endpoint:
PATCH /api/v1/admin/route-tariffs/{tariff_id}
Access:
admin
super_admin
Request:
{
  "suggested_price": 65000,
  "min_price": 55000,
  "max_price": 85000,
  "is_active": true
}
Rules:
Partial update allowed.
Validate final price range using old + new values together.
If activating tariff, ensure no other active tariff exists for same direction.
Write audit_logs with old_value and new_value if audit exists.
Hard delete is not allowed.
Do not allow changing from_city_id and to_city_id through PATCH unless the current project already supports it safely.
Recommended MVP:
from_city_id and to_city_id are immutable after creation.
If route direction is wrong, admin should deactivate old tariff and create new tariff.

14. Error codes
Use consistent error codes.
Required error codes for Stage 5:
VALIDATION_ERROR
UNAUTHORIZED
FORBIDDEN
NOT_FOUND
CITY_NOT_FOUND
CITY_ALREADY_EXISTS
CITY_INACTIVE
SAME_CITY_ROUTE
ROUTE_TARIFF_NOT_FOUND
ROUTE_TARIFF_ALREADY_EXISTS
INVALID_PRICE_RANGE
INVALID_UUID
SERVER_ERROR
Examples:
Duplicate city:
{
  "success": false,
  "error": {
    "code": "CITY_ALREADY_EXISTS",
    "message": "City already exists"
  }
}
Same city route:
{
  "success": false,
  "error": {
    "code": "SAME_CITY_ROUTE",
    "message": "from_city_id and to_city_id cannot be the same"
  }
}
Invalid price range:
{
  "success": false,
  "error": {
    "code": "INVALID_PRICE_RANGE",
    "message": "Invalid route tariff price range"
  }
}
Inactive city:
{
  "success": false,
  "error": {
    "code": "CITY_INACTIVE",
    "message": "City is inactive"
  }
}

15. Audit logs
Write audit logs for admin/super_admin write actions if audit service exists.
Actions:
city_created
city_updated
route_tariff_created
route_tariff_updated
Audit fields:
actor_id
actor_role
entity_type
entity_id
action
old_value
new_value
reason
created_at
For create:
old_value = null
new_value = created object
For update:
old_value = previous values
new_value = updated values
If audit_logs module is not implemented yet, create a small placeholder service or TODO comment according to current project style, but do not break Stage 5.

16. Seed data
Add seed script if project already has scripts.
If scripts folder does not exist, create:
scripts/
Recommended file:
scripts/seed_cities.py
Seed must be idempotent.
Running seed twice must not create duplicates.
Initial cities:
Toshkent
Samarqand
Buxoro
Andijon
Namangan
Farg‘ona
Qo‘qon
Qarshi
Navoiy
Jizzax
Termiz
Urganch
Nukus
Guliston
Recommended Russian names:
Ташкент
Самарканд
Бухара
Андижан
Наманган
Фергана
Коканд
Карши
Навои
Джизак
Термез
Ургенч
Нукус
Гулистан
Use region consistently.
Optional tariff seed:
Toshkent → Samarqand
Toshkent → Buxoro
Toshkent → Farg‘ona
Toshkent → Andijon
Toshkent → Namangan
Do not hardcode tariffs in service logic.
Tariffs must come from database.
Seed should skip existing records by normalized city name or exact route direction.

17. Tests to add or update
Keep existing Stage 5 tests, but add stronger regression tests.
Cities tests:
GET /cities returns only active cities by default
GET /cities supports pagination response object
GET /cities supports search by name_uz
GET /cities supports search by name_ru
GET /cities search is case-insensitive
GET /cities trims search spaces
admin can create city
super_admin can create city
operator cannot create city
client cannot create city
driver cannot create city
blocked admin cannot create city
duplicate city rejected case-insensitively
admin can update city
operator cannot update city
inactive city does not appear in public list by default
admin list can include inactive cities
Route tariff tests:
admin can create route tariff
super_admin can create route tariff
operator cannot create route tariff
client cannot create route tariff
driver cannot create route tariff
from_city_id = to_city_id is rejected
invalid UUID is rejected
missing from_city_id is rejected
missing to_city_id is rejected
inactive from_city rejected
inactive to_city rejected
negative suggested_price rejected
negative min_price rejected
negative max_price rejected
min_price > suggested_price rejected
suggested_price > max_price rejected
price must be integer UZS
duplicate active tariff rejected
reverse route is not automatically created
activating duplicate inactive tariff is rejected
admin can update tariff prices
operator cannot update tariff
tariff update validates final price range
tariff update writes audit old_value and new_value if audit exists
Suggested price tests:
authenticated user can get suggested price
anonymous user cannot get suggested price if endpoint is protected
suggested price returns integer UZS
no active tariff returns success=true and suggested_price=null
inactive tariff returns suggested_price=null
inactive city returns CITY_INACTIVE
reverse route without tariff returns suggested_price=null
Seed tests if project supports them:
seed_cities.py is idempotent
running seed twice creates no duplicates
seed creates expected cities
Database constraint tests if possible:
partial unique index prevents duplicate active tariff

18. Integration notes for later stages
Document these rules in code comments or docs:
Stage 6 driver_routes must only allow active cities.
Stage 7 client_orders must only allow active cities.
Stage 7 client_orders should copy current route_tariff suggested_price into order at creation time.
Stage 8 matching must use exact from_city_id and to_city_id.
Tariff does not affect matching.
Tariff does not calculate final price.
Final price comes from selected driver bid.
Important:
Route tariff suggested_price is not final price.
Driver bid decides final_price after client selects driver.

19. Manual API test examples
Create city:
curl -X POST "http://localhost:8000/api/v1/admin/cities" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name_uz": "Toshkent",
    "name_ru": "Ташкент",
    "region": "Toshkent"
  }'
Get cities:
curl "http://localhost:8000/api/v1/cities?page=1&limit=20&search=tosh"
Create route tariff:
curl -X POST "http://localhost:8000/api/v1/admin/route-tariffs" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "from_city_id": "FROM_CITY_UUID",
    "to_city_id": "TO_CITY_UUID",
    "suggested_price": 60000,
    "min_price": 50000,
    "max_price": 80000
  }'
Get suggested price:
curl "http://localhost:8000/api/v1/route-tariffs/suggested-price?from_city_id=FROM_CITY_UUID&to_city_id=TO_CITY_UUID" \
  -H "Authorization: Bearer ACCESS_TOKEN"
Reverse route test:
curl "http://localhost:8000/api/v1/route-tariffs/suggested-price?from_city_id=SAMARQAND_UUID&to_city_id=TOSHKENT_UUID" \
  -H "Authorization: Bearer ACCESS_TOKEN"
Expected if reverse tariff does not exist:
{
  "success": true,
  "data": {
    "suggested_price": null,
    "min_price": null,
    "max_price": null,
    "currency": "UZS",
    "is_active": false
  },
  "message": "No active tariff found for this route"
}

20. Stop condition
After updating Stage 5, stop.
Report:
1. What was changed
2. Files changed
3. Migrations created if any
4. Partial unique index added or not
5. Seed script added or updated
6. Pagination format implemented
7. Direction-based route tariff behavior confirmed
8. Suggested price null behavior confirmed
9. Tests added/updated
10. How to run tests
11. Manual API test examples
12. Any assumptions
13. Any TODOs
Do not continue to Stage 6 until Stage 5 is reviewed and tests pass.