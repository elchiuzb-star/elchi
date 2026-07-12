# Stage 3: Implement Auth API — Full Professional Prompt

Implement a secure Auth API for the Intercity Parcel Delivery Marketplace MVP.

This stage is responsible for:

* phone-based OTP authentication
* client and driver public registration
* admin/operator creation by super_admin only
* super_admin initial creation through database/manual seed only
* JWT access token and refresh token
* refresh token rotation/revocation
* role-based dependency helpers
* active/blocked user validation
* client/driver profile auto-creation
* auth tests

Important: this stage must follow the approved MVP logic exactly.

Do not implement:

```text
email/password login
social login
Google login
Apple login
online payment
OTP proof for delivery
QR proof
pickup proof
delivery proof
chat
driver capacity
driver departure time
cargo type
weight
size
```

This stage only implements:

```text
phone OTP auth
JWT auth
role permissions
admin/operator creation by super_admin
super_admin manual DB creation
```

---

# 1. Endpoints to implement

Public auth endpoints:

```http
POST /api/v1/auth/request-otp
POST /api/v1/auth/verify-otp
POST /api/v1/auth/refresh
```

Authenticated auth endpoints:

```http
POST /api/v1/auth/logout
GET /api/v1/auth/me
```

Super admin user management endpoint:

```http
POST /api/v1/admin/users
```

This endpoint is only for creating:

```text
operator
admin
```

Do not allow public creation of:

```text
operator
admin
super_admin
```

---

# 2. User roles

Supported roles:

```text
client
driver
operator
admin
super_admin
```

Public users can register only as:

```text
client
driver
```

Only `super_admin` can create:

```text
operator
admin
```

`super_admin` itself must not be created through public API.

Initial `super_admin` must be created manually through database insert or local seed command.

---

# 3. One phone = one role rule

A phone number can belong to only one user and one role.

This means:

```text
One phone cannot be both client and driver.
One phone cannot be both driver and admin.
One phone cannot be both client and operator.
```

If phone already exists with role `client` and user tries to verify/login as `driver`, return:

```json
{
  "success": false,
  "error": {
    "code": "ROLE_MISMATCH",
    "message": "This phone number is already registered with another role"
  }
}
```

If phone already exists as `driver` and user tries as `client`, same error.

Existing admin/operator/super_admin users can login through OTP only if their user record already exists.

But they cannot be created by public OTP registration.

---

# 4. Phone normalization

All phone numbers must be normalized before storing or querying.

Target format:

```text
+998XXXXXXXXX
```

Acceptable input examples:

```text
+998901234567
998901234567
90 123 45 67
90-123-45-67
(90) 123-45-67
```

Normalize them to:

```text
+998901234567
```

Validation rules:

```text
Uzbekistan phone only for MVP.
Phone must become +998XXXXXXXXX after normalization.
Phone must have exactly 12 characters including +.
users.phone must be unique after normalization.
Invalid phone returns VALIDATION_ERROR.
```

Invalid response:

```json
{
  "success": false,
  "error": {
    "code": "INVALID_PHONE",
    "message": "Invalid Uzbekistan phone number"
  }
}
```

---

# 5. OTP rules

OTP must be optimized for Uzbekistan phone auth.

OTP configuration:

```text
OTP length = 5 digits
OTP expires in 2 minutes
Max OTP send requests = 5
Max OTP verify attempts = 5 per OTP
Resend cooldown = 60 seconds
Only latest OTP for phone is valid
OTP must be marked as used after successful verification
Expired OTP cannot be used
Used OTP cannot be reused
```

OTP must contain only digits.

Example OTP:

```text
12345
```

Do not use 6-digit OTP.

Do not keep OTP valid longer than 2 minutes.

---

# 6. OTP send request limit

Apply send request limit per normalized phone.

Rule:

```text
Max 5 OTP send requests per phone per rolling 30 minutes.
```

If exceeded:

```json
{
  "success": false,
  "error": {
    "code": "OTP_SEND_LIMIT_EXCEEDED",
    "message": "Too many OTP requests. Please try again later"
  }
}
```

Also apply cooldown:

```text
User cannot request another OTP within 60 seconds for the same phone.
```

If cooldown active:

```json
{
  "success": false,
  "error": {
    "code": "OTP_RESEND_TOO_SOON",
    "message": "Please wait before requesting another OTP"
  }
}
```

For development, these limits should still exist but can be configurable through `.env`.

---

# 7. OTP storage

Use secure OTP storage.

Recommended:

```text
Create otp_codes table if not already available.
Store OTP hash, not plain OTP.
```

Recommended fields:

```text
id
phone
role
otp_hash
expires_at
used_at
attempt_count
send_count_window_start
created_at
updated_at
```

If current project already has OTP storage, adapt it.

Do not store plain OTP in production.

Development can optionally return OTP in response only if:

```text
APP_ENV=development
DEBUG=true
```

Never return OTP in production response.

---

# 8. Development mock OTP

For development only:

```text
Allow static mock OTP = 12345 only when APP_ENV=development.
```

Do not allow mock OTP in production.

If APP_ENV is not development:

```text
Static mock OTP must not work.
```

If no SMS provider exists yet, simulate OTP sending in development.

Production SMS integration can remain TODO.

---

# 9. POST /api/v1/auth/request-otp

## Request

```json
{
  "phone": "+998901234567",
  "role": "client"
}
```

Fields:

```text
phone: required
role: required
```

Allowed role values for public request:

```text
client
driver
operator
admin
super_admin
```

But public registration rules apply.

---

## Logic

Steps:

```text
1. Normalize phone.
2. Validate phone.
3. Validate role.
4. If role is client or driver:
   - allow OTP request for new or existing user.
   - if existing user has different role, return ROLE_MISMATCH.
5. If role is operator/admin/super_admin:
   - user must already exist with that role.
   - if user does not exist, return FORBIDDEN.
   - do not create operator/admin/super_admin publicly.
6. If existing user status is blocked/deleted/inactive, reject.
7. Enforce resend cooldown.
8. Enforce max send request limit = 5 per 30 minutes.
9. Generate 5-digit OTP.
10. Expire previous active OTPs for same phone/role.
11. Store OTP hash.
12. Return success.
```

---

## Success response

```json
{
  "success": true,
  "data": {
    "otp_sent": true,
    "phone": "+998901234567",
    "expires_in_seconds": 120,
    "resend_after_seconds": 60
  },
  "message": "OTP sent"
}
```

In development only, if DEBUG=true:

```json
{
  "success": true,
  "data": {
    "otp_sent": true,
    "phone": "+998901234567",
    "expires_in_seconds": 120,
    "resend_after_seconds": 60,
    "dev_otp": "12345"
  },
  "message": "OTP sent"
}
```

Never include `dev_otp` in production.

---

# 10. POST /api/v1/auth/verify-otp

## Request

```json
{
  "phone": "+998901234567",
  "role": "client",
  "otp": "12345"
}
```

Fields:

```text
phone: required
role: required
otp: required
```

OTP validation:

```text
OTP must be 5 digits.
OTP must not be expired.
OTP must not be used.
OTP attempt_count must be less than 5.
OTP must match stored hash or dev mock rule.
```

---

## Logic

Steps:

```text
1. Normalize phone.
2. Validate phone.
3. Validate role.
4. Validate OTP format: exactly 5 digits.
5. Find latest active OTP for phone + role.
6. Reject expired OTP.
7. Reject used OTP.
8. Reject if attempt_count >= 5.
9. If OTP mismatch:
   - increment attempt_count.
   - return OTP_INVALID.
10. If OTP valid:
   - mark OTP used.
11. Find user by normalized phone.
12. If user exists:
   - check role matches.
   - check status = active.
   - mark is_phone_verified = true.
13. If user does not exist:
   - allow creation only if role is client or driver.
   - create user with role.
   - status = active.
   - is_phone_verified = true.
14. If new user role is client:
   - create client_profiles row.
15. If new user role is driver:
   - create driver_profiles row:
     verification_status = new
     is_available = false
     rating = 0
     total_orders = 0
     completed_orders = 0
     cancelled_orders = 0
     dispute_count = 0
16. Generate JWT access token.
17. Generate refresh token.
18. Store refresh token session or jti.
19. Return tokens and user.
```

---

## Success response

```json
{
  "success": true,
  "data": {
    "access_token": "jwt_access_token",
    "refresh_token": "jwt_refresh_token",
    "token_type": "bearer",
    "expires_in": 3600,
    "user": {
      "id": "uuid",
      "phone": "+998901234567",
      "full_name": null,
      "role": "client",
      "status": "active",
      "is_phone_verified": true
    }
  },
  "message": "Login successful"
}
```

---

# 11. Admin/operator/super_admin auth behavior

Public OTP endpoints can authenticate existing admin/operator/super_admin users.

But they must not create them.

Rules:

```text
If role = admin/operator/super_admin and user exists with same phone and same role:
  allow OTP login.

If role = admin/operator/super_admin and user does not exist:
  return FORBIDDEN.

If role = admin/operator/super_admin and phone exists with different role:
  return ROLE_MISMATCH.
```

This allows admin token generation after super_admin creates admin/operator.

---

# 12. Initial super_admin creation

Do not create super_admin through API.

Initial super_admin must be added manually through database or local seed command.

Recommended local command or script:

```text
scripts/create_super_admin.py
```

If scripts folder does not exist, create it.

Script behavior:

```text
Read SUPER_ADMIN_PHONE from .env or ask via CLI.
Normalize phone.
Create user with:
  role = super_admin
  status = active
  is_phone_verified = true
If user already exists, do not duplicate.
```

Example `.env`:

```text
SUPER_ADMIN_PHONE=+998900000001
```

After super_admin exists, it can login via OTP and create admin/operator users.

---

# 13. POST /api/v1/admin/users

This endpoint lets super_admin create operator/admin users.

## Access

Only:

```text
super_admin
```

Operator/admin/client/driver cannot access.

---

## Request

```json
{
  "phone": "+998900000002",
  "role": "admin",
  "full_name": "Admin User"
}
```

Allowed roles to create:

```text
operator
admin
```

Do not allow creating:

```text
client
driver
super_admin
```

Client and driver use public registration.

Super admin is DB/seed only.

---

## Logic

```text
1. Require current user role = super_admin.
2. Normalize phone.
3. Validate phone.
4. Validate role is operator or admin.
5. Check phone does not already exist.
6. Create user:
   phone = normalized phone
   role = admin/operator
   full_name = request.full_name
   status = active
   is_phone_verified = true
7. Write audit_logs if audit service exists.
8. Return created user.
```

---

## Response

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "phone": "+998900000002",
    "full_name": "Admin User",
    "role": "admin",
    "status": "active",
    "is_phone_verified": true
  },
  "message": "User created"
}
```

---

# 14. JWT token rules

Use JWT access and refresh tokens.

Access token config:

```text
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

Refresh token config:

```text
REFRESH_TOKEN_EXPIRE_DAYS=30
```

JWT config:

```text
JWT_SECRET_KEY=change-me
JWT_ALGORITHM=HS256
```

Access token claims:

```text
sub = user.id
phone = user.phone
role = user.role
type = access
jti = unique token id
iat
exp
```

Refresh token claims:

```text
sub = user.id
type = refresh
jti = unique token id
iat
exp
```

Protected endpoints must reject refresh token if used as access token.

Refresh endpoint must reject access token if used as refresh token.

---

# 15. Refresh token storage and rotation

Implement refresh token session storage if not already present.

Recommended table:

```text
refresh_sessions
```

Fields:

```text
id
user_id
jti
token_hash
is_revoked
expires_at
created_at
revoked_at
user_agent
ip_address
```

If the project already has a token/session table, use it.

Rules:

```text
Refresh token must be stored as hash or jti.
POST /auth/refresh must rotate refresh token.
Old refresh token becomes revoked.
New access token and new refresh token are returned.
Blocked/inactive/deleted users cannot refresh.
Expired refresh token is rejected.
Revoked refresh token is rejected.
```

---

# 16. POST /api/v1/auth/refresh

## Request

```json
{
  "refresh_token": "jwt_refresh_token"
}
```

## Logic

```text
1. Decode token.
2. Validate type = refresh.
3. Validate token not expired.
4. Validate jti/session exists.
5. Validate session not revoked.
6. Validate user exists and status = active.
7. Revoke old refresh session.
8. Create new refresh session.
9. Return new access_token and new refresh_token.
```

## Response

```json
{
  "success": true,
  "data": {
    "access_token": "new_access_token",
    "refresh_token": "new_refresh_token",
    "token_type": "bearer",
    "expires_in": 3600
  },
  "message": "Token refreshed"
}
```

---

# 17. POST /api/v1/auth/logout

## Request

```json
{
  "refresh_token": "jwt_refresh_token"
}
```

or allow empty body and revoke current session if project tracks session from token.

Recommended MVP:

```text
Require refresh_token in body.
```

## Logic

```text
1. Require authentication with access token.
2. Decode provided refresh token.
3. Validate type = refresh.
4. Find session by jti.
5. Revoke refresh session.
6. Return success.
```

Access token may remain valid until expiry unless token blacklist exists.

This is acceptable for MVP if access token expiry is short.

## Response

```json
{
  "success": true,
  "message": "Logged out"
}
```

---

# 18. GET /api/v1/auth/me

## Access

Authenticated users only.

Rules:

```text
Access token required.
Token type must be access.
User must exist.
User status must be active.
```

Response:

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "phone": "+998901234567",
    "full_name": "Ali Valiyev",
    "role": "driver",
    "status": "active",
    "is_phone_verified": true
  }
}
```

Do not return:

```text
refresh token
password hash
OTP
secret
internal token jti
```

---

# 19. Role-based dependency helpers

Add reusable dependencies:

```text
get_current_user
get_current_active_user
require_roles(*roles)
require_client
require_driver
require_operator
require_operator_or_admin
require_admin
require_super_admin
require_admin_or_super_admin
```

Expected usage:

```text
client endpoints → require_client
driver endpoints → require_driver
admin orders → require_roles(operator, admin, super_admin)
driver approve/reject/block → require_admin_or_super_admin
audit logs → require_admin_or_super_admin
admin/operator creation → require_super_admin
```

All dependencies must reject:

```text
invalid token
expired token
wrong token type
missing user
blocked user
inactive user
deleted user
wrong role
```

---

# 20. Standard response format

Use project standard format.

Success:

```json
{
  "success": true,
  "data": {},
  "message": "OK"
}
```

Error:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input",
    "details": {}
  }
}
```

Do not return raw FastAPI errors if project already has response wrapper.

---

# 21. Error codes

Implement or use consistent error codes:

```text
INVALID_PHONE
OTP_INVALID
OTP_EXPIRED
OTP_USED
OTP_TOO_MANY_ATTEMPTS
OTP_SEND_LIMIT_EXCEEDED
OTP_RESEND_TOO_SOON
ROLE_NOT_ALLOWED
ROLE_MISMATCH
USER_BLOCKED
USER_INACTIVE
INVALID_TOKEN
TOKEN_EXPIRED
REFRESH_TOKEN_REVOKED
UNAUTHORIZED
FORBIDDEN
VALIDATION_ERROR
ALREADY_EXISTS
SERVER_ERROR
```

---

# 22. Security rules

Do:

```text
Normalize phone before DB lookup.
Do not store plain OTP in production.
Do not return OTP in production.
Use JWT_SECRET_KEY from env.
Use token type claim.
Use refresh token rotation.
Reject blocked/inactive/deleted users.
Reject role mismatch.
Create client/driver profiles on registration.
```

Do not:

```text
Allow public admin creation.
Allow public operator creation.
Allow public super_admin creation.
Allow one phone to have multiple roles.
Allow refresh token as access token.
Allow access token as refresh token.
Log OTP values in production.
Expose refresh token in /auth/me.
```

---

# 23. Environment variables

Add/update `.env.example`:

```text
JWT_SECRET_KEY=change-me
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=30

OTP_LENGTH=5
OTP_EXPIRE_SECONDS=120
OTP_MAX_SEND_REQUESTS=5
OTP_SEND_WINDOW_MINUTES=30
OTP_RESEND_COOLDOWN_SECONDS=60
OTP_MAX_VERIFY_ATTEMPTS=5
DEV_MOCK_OTP=12345

APP_ENV=development
DEBUG=true

SUPER_ADMIN_PHONE=+998900000001
```

---

# 24. Database / migration requirements

If missing, add migration for:

```text
otp_codes
refresh_sessions
```

If users table does not have these fields, add them:

```text
phone unique
role
status
is_phone_verified
last_login_at
created_at
updated_at
```

If profiles do not exist, ensure:

```text
client_profiles.user_id unique
driver_profiles.user_id unique
```

Do not add unrelated fields.

Do not add payment fields here.

Do not add OTP/QR delivery proof fields.

---

# 25. Tests required

Add automated tests for:

```text
request OTP with valid Uzbek phone
phone normalization works
invalid phone rejected
OTP length is 5 digits
OTP expires in 2 minutes
OTP send limit is 5 per 30 minutes
OTP resend cooldown works
verify OTP creates client user
verify OTP creates driver user
client profile auto-created
driver profile auto-created
driver profile verification_status = new
driver profile is_available = false
invalid OTP rejected
expired OTP rejected
used OTP rejected
too many verify attempts rejected
public client registration allowed
public driver registration allowed
public operator registration rejected
public admin registration rejected
public super_admin registration rejected
existing admin can request OTP if already created
existing operator can request OTP if already created
existing super_admin can request OTP if already created
same phone cannot register as both client and driver
role mismatch returns ROLE_MISMATCH
blocked user cannot login
inactive user cannot login
deleted user cannot login
verify OTP returns access token and refresh token
access token has type access
refresh token has type refresh
/auth/me works with access token
/auth/me rejects refresh token
refresh endpoint works with refresh token
refresh endpoint rejects access token
refresh token rotation revokes old token
revoked refresh token rejected
logout revokes refresh token
super_admin can create admin user
super_admin can create operator user
admin cannot create admin/operator user
operator cannot create admin/operator user
super_admin cannot create another super_admin through API
created admin can login through OTP
created operator can login through OTP
role dependency helpers enforce correct access
```

---

# 26. Manual API test examples

## 26.1 Create initial super_admin manually

If script exists:

```bash
python scripts/create_super_admin.py
```

Or manually insert super_admin into database.

Expected user:

```text
phone = +998900000001
role = super_admin
status = active
is_phone_verified = true
```

---

## 26.2 Super admin login

Request OTP:

```bash
curl -X POST "http://localhost:8000/api/v1/auth/request-otp" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+998900000001",
    "role": "super_admin"
  }'
```

Verify OTP:

```bash
curl -X POST "http://localhost:8000/api/v1/auth/verify-otp" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+998900000001",
    "role": "super_admin",
    "otp": "12345"
  }'
```

---

## 26.3 Super admin creates admin

```bash
curl -X POST "http://localhost:8000/api/v1/admin/users" \
  -H "Authorization: Bearer SUPER_ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+998900000002",
    "role": "admin",
    "full_name": "Admin User"
  }'
```

---

## 26.4 Admin login

```bash
curl -X POST "http://localhost:8000/api/v1/auth/request-otp" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+998900000002",
    "role": "admin"
  }'
```

```bash
curl -X POST "http://localhost:8000/api/v1/auth/verify-otp" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+998900000002",
    "role": "admin",
    "otp": "12345"
  }'
```

Admin access token from this response is the `admin_token` for Postman.

---

## 26.5 Client registration

```bash
curl -X POST "http://localhost:8000/api/v1/auth/request-otp" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+998901234567",
    "role": "client"
  }'
```

```bash
curl -X POST "http://localhost:8000/api/v1/auth/verify-otp" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+998901234567",
    "role": "client",
    "otp": "12345"
  }'
```

---

## 26.6 Same phone cannot become driver

If phone is already client:

```bash
curl -X POST "http://localhost:8000/api/v1/auth/request-otp" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+998901234567",
    "role": "driver"
  }'
```

Expected:

```json
{
  "success": false,
  "error": {
    "code": "ROLE_MISMATCH"
  }
}
```

---

# 27. Stop condition

After implementing Stage 3, stop.

Report:

```text
1. What was implemented
2. Files changed
3. Migrations created if any
4. How to run migrations
5. How to create initial super_admin
6. How super_admin creates admin/operator
7. How to get admin token
8. How to get client token
9. How to get driver token
10. How to run tests
11. Manual API test examples
12. Any assumptions
13. Any TODOs
```

Do not continue to Stage 4 until this stage is reviewed and tests pass.
