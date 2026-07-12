Driver Profile Security & Lifecycle Update — Professional Codex Prompt
You are updating the existing backend implementation for the Intercity Parcel Delivery Marketplace MVP.
This update strengthens driver profile creation, document handling, verification, availability, blocking, and security rules.
Do not rewrite the whole project.
Do not change the approved MVP flow.
Do not add removed features.
This update affects mainly:
Stage 3 — Auth API
Stage 6 — Driver Profile, Documents, Availability, Routes
Stage 15 — Admin Driver Verification
Stage 18 — Security/Permission Hardening
Your task is to update only the missing or weak parts.

1. Important MVP restrictions
Do not implement:
driver departure time
trip departure time
driver capacity
free space
weight limit
cargo type
cargo weight
cargo size
pickup proof
delivery proof
delivery photo
receiver confirmation code
OTP for delivery
QR code
GPS tracking
map tracking
online payment
chat
This update only handles:
driver profile auto-create
driver profile security
driver document upload rules
driver verification status
driver availability rules
driver blocking behavior
driver route eligibility
admin/operator permissions
audit logs
tests

2. Driver profile creation rule
Driver profile must be created automatically when a new driver successfully verifies OTP.
Flow:
POST /api/v1/auth/verify-otp
↓
role = driver
↓
create users row
↓
create driver_profiles row
↓
return tokens
This must happen inside one database transaction.
Rules:
If user creation succeeds but driver_profile creation fails, rollback user creation.
If driver_profile already exists, do not create duplicate.
One driver user must have exactly one driver_profile.
Database rule:
driver_profiles.user_id must be UNIQUE.
If the unique constraint is missing, add Alembic migration.

3. Default driver profile values
When new driver profile is created, use safe default values:
verification_status = new
is_available = false
rating = 0
total_orders = 0
completed_orders = 0
cancelled_orders = 0
dispute_count = 0
Nullable profile fields initially:
full_name = null
car_model = null
car_color = null
plate_number = null
plate_number_normalized = null
Important rule:
New driver must not be able to see order feed.
New driver must not be able to bid.
New driver must not be able to set is_available=true.

4. Stage 3 Auth update
Update verify-otp logic.
When role is driver and user does not exist:
1. Normalize phone.
2. Validate OTP.
3. Create user:
   role = driver
   status = active
   is_phone_verified = true
4. Create driver_profiles row:
   verification_status = new
   is_available = false
5. Commit transaction.
6. Return access_token and refresh_token.
When role is client and user does not exist:
Create user.
Create client_profiles row.
Do not create driver_profile.
One phone = one role:
If phone already exists as client, it cannot become driver.
If phone already exists as driver, it cannot become client.
Return ROLE_MISMATCH.
Existing driver login:
If user exists as driver and driver_profile is missing because of old data, create missing driver_profile safely.
Do not create duplicate.
This fallback is only for repairing old inconsistent data.

5. Driver profile GET behavior
Endpoint:
GET /api/v1/driver/profile
Access:
driver only
Behavior:
Return current driver's profile.
If driver_profile is missing for current driver due to old data, create it safely with default values.
Do not create duplicate.
Response should include:
user_id
phone
full_name
car_model
car_color
plate_number
verification_status
is_available
rating
total_orders
completed_orders
cancelled_orders
dispute_count
created_at
updated_at
Do not expose:
internal audit data
other drivers' data
admin-only notes unless endpoint is admin endpoint

6. Driver profile update rules
Endpoint:
PATCH /api/v1/driver/profile
Access:
driver only
Driver may update only:
full_name
car_model
car_color
plate_number
Driver must not update:
verification_status
is_available
rating
total_orders
completed_orders
cancelled_orders
dispute_count
role
user status
is_phone_verified
is_available must be updated only through separate availability endpoint.
Recommended endpoint:
PATCH /api/v1/driver/availability

7. Plate number normalization
When driver updates plate_number, also create normalized value.
Examples:
01 A 123 AA → 01A123AA
01a123aa → 01A123AA
01-A-123-AA → 01A123AA
Rules:
Trim spaces.
Remove spaces and hyphens.
Uppercase letters.
Save original value in plate_number.
Save normalized value in plate_number_normalized.
Validation:
plate_number max length should be reasonable.
plate_number_normalized must not be empty if plate_number exists.
Recommended uniqueness rule:
plate_number_normalized must be unique among active/approved/non-blocked drivers if possible.
If project complexity is high, at least check duplicate plate number at service level.
Error:
PLATE_NUMBER_ALREADY_EXISTS

8. Driver availability endpoint
Endpoint:
PATCH /api/v1/driver/availability
Access:
driver only
Request:
{
  "is_available": true
}
Rules:
Driver can set is_available=false anytime.
Driver can set is_available=true only if verification_status=approved.
Blocked/rejected/new/pending driver cannot set is_available=true.
Inactive/deleted/blocked user cannot update availability.
If driver is not approved:
{
  "success": false,
  "error": {
    "code": "DRIVER_NOT_APPROVED",
    "message": "Driver must be approved before becoming available"
  }
}
When availability changes, write audit log if audit service exists:
driver_availability_changed

9. Driver verification status enum
Use this enum for driver profile verification:
new
pending
approved
rejected
blocked
Recommended flow:
new → pending
pending → approved
pending → rejected
approved → blocked
rejected → pending
blocked → approved only by admin/super_admin if business allows
Driver cannot directly set this status.
Only admin/super_admin can approve/reject/block.
Operator can view but cannot approve/reject/block.

10. Driver documents
Driver documents must be stored separately from driver_profiles.
Use or create:
driver_documents
Required document types:
passport
selfie
license
car_document
car_photo
Do not allow:
pickup_proof
delivery_proof
delivery_photo
receiver_confirmation_code
qr
Document fields:
id
driver_profile_id
document_type
file_url
status
rejection_reason
reviewed_by
reviewed_at
created_at
updated_at
Document status enum:
pending
approved
rejected
When driver uploads a required document:
Create or replace document record for that driver and document_type.
status = pending.
If driver verification_status is new or rejected, set it to pending.
Driver can upload only their own documents.
Driver cannot upload document for another driver.

11. Document file validation
Allowed MIME types:
image/jpeg
image/png
image/webp
application/pdf
Recommended size limit:
max 10MB
Invalid file type:
DRIVER_DOCUMENT_INVALID_TYPE
Too large:
DRIVER_DOCUMENT_TOO_LARGE
Use existing Files API if already implemented.
Do not create delivery proof or pickup proof document types.

12. Driver document completeness rule
Before admin/super_admin approves a driver, required documents must exist.
Required documents:
passport
selfie
license
car_document
car_photo
MVP decision:
Admin does not need to approve each document separately.
Admin can approve the driver profile if all required document records exist.
If required documents are missing, return:
DRIVER_DOCUMENTS_INCOMPLETE
Response example:
{
  "success": false,
  "error": {
    "code": "DRIVER_DOCUMENTS_INCOMPLETE",
    "message": "Required driver documents are missing",
    "details": {
      "missing": ["license", "car_photo"]
    }
  }
}

13. Admin driver verification permissions
Operator:
can list drivers
can view driver detail
can view driver documents
cannot approve driver
cannot reject driver
cannot block driver
cannot unblock driver
Admin:
can list drivers
can view driver detail
can approve driver
can reject driver
can block driver
can unblock driver if allowed
Super admin:
same as admin
Client/driver:
cannot access admin driver verification endpoints

14. Admin approve driver
Endpoint can follow existing project style, for example:
POST /api/v1/admin/drivers/{driver_id}/approve
or current existing endpoint.
Access:
admin
super_admin
Rules:
Driver must exist.
Driver user must be active.
Driver profile must exist.
Driver must not be blocked.
Required documents must exist.
Set verification_status = approved.
Keep is_available = false.
Driver must manually set is_available=true later.
Write audit log.
Create notification if notification service exists.
Important:
Approving driver must not automatically make driver available.
Audit action:
driver_approved

15. Admin reject driver
Endpoint:
POST /api/v1/admin/drivers/{driver_id}/reject
Request:
{
  "reason": "Documents are not clear"
}
Access:
admin
super_admin
Rules:
reason required.
Set verification_status = rejected.
Set is_available = false.
Do not delete documents.
Write audit log.
Create notification if notification service exists.
Audit action:
driver_rejected

16. Admin block driver
Endpoint:
POST /api/v1/admin/drivers/{driver_id}/block
Request:
{
  "reason": "Fraud suspicion"
}
Access:
admin
super_admin
Rules:
reason required.
Set verification_status = blocked.
Set driver_profiles.is_available = false.
Set user.status = blocked if the project uses user status blocking.
Set all active driver_routes.status = unavailable.
Revoke active refresh sessions if refresh_sessions table exists.
Driver must not be able to feed/bid/update order after block.
Write audit log.
Create notification if notification service exists.
Audit action:
driver_blocked
Important security rule:
Blocked driver must not continue using old refresh tokens.
Access token may expire naturally if no blacklist exists, but all protected dependencies must check current user status from DB.

17. Admin unblock / re-approve driver
If project supports unblock:
POST /api/v1/admin/drivers/{driver_id}/unblock
Access:
admin
super_admin
Rules:
reason required.
Set user.status = active.
Set verification_status = approved or pending according to business decision.
Recommended MVP: set verification_status = approved only if admin explicitly unblocks as approved.
Keep is_available = false.
Driver must manually set is_available=true.
Do not automatically reactivate routes unless project decides.
Write audit log.
Recommended simple MVP:
Do not add unblock endpoint if not already planned.
Instead, admin can approve blocked driver only with explicit reason.
If not implementing unblock now, document TODO.

18. Driver route eligibility
Driver can create/update route only if:
user.status = active
user.role = driver
driver_profile exists
verification_status = approved
Driver route can be created while is_available=false, but it must not match orders until driver is available.
Recommended rule:
Approved driver can create route.
Only approved + available driver with available route can be matched.
Do not add:
departure_time
capacity
free_space
Driver route fields remain:
from_city_id
to_city_id
status

19. Driver feed and bid eligibility
Driver can see feed only if:
user.status = active
role = driver
driver_profile.verification_status = approved
driver_profile.is_available = true
driver_route.status = available
route matches order from_city_id/to_city_id
Driver can bid only if:
driver can see that order in feed
driver is approved
driver is available
driver is not blocked
driver has matching active route
Do not allow:
new driver to see feed
pending driver to see feed
rejected driver to see feed
blocked driver to see feed
unavailable driver to see feed
wrong route driver to see feed

20. Driver contact visibility
Approved driver still must not see private client contact data until selected.
Before selected:
Driver can see limited order data only.
Do not expose sender_phone.
Do not expose receiver_phone.
Do not expose full pickup_address.
Do not expose full dropoff_address.
After selected:
Only assigned driver can see full pickup/dropoff addresses and phones.
Unselected drivers must not see private contact data.
This rule belongs to feed/order detail stage, but verify it is not broken by driver profile updates.

21. Blocking impact on active orders
If driver is blocked while having active assigned orders:
Do not silently delete orders.
Do not silently mark delivered/cancelled.
Set driver unavailable.
Set routes unavailable.
Admin/operator must manually resolve active orders.
Recommended:
If active assigned orders exist, return warning in admin block response.
Still allow block if admin/super_admin provides reason.
Response can include:
{
  "success": true,
  "data": {
    "driver_id": "uuid",
    "verification_status": "blocked",
    "active_orders_count": 2,
    "warning": "Driver has active orders. Admin must resolve them manually."
  }
}

22. Audit logs
Write audit logs for:
driver_profile_auto_created
driver_profile_updated
driver_document_uploaded
driver_submitted_for_review
driver_approved
driver_rejected
driver_blocked
driver_unblocked
driver_availability_changed
driver_route_created
driver_route_updated
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
If audit service is not implemented yet, use existing project pattern:
call audit service if available
or create TODO comment
or implement lightweight audit helper if Stage 17 already exists
Do not break the current flow because of missing audit service.

23. Error codes
Add or use these error codes:
DRIVER_PROFILE_NOT_FOUND
DRIVER_PROFILE_ALREADY_EXISTS
DRIVER_NOT_APPROVED
DRIVER_DOCUMENTS_INCOMPLETE
DRIVER_DOCUMENT_INVALID_TYPE
DRIVER_DOCUMENT_TOO_LARGE
DRIVER_ALREADY_APPROVED
DRIVER_ALREADY_BLOCKED
DRIVER_BLOCKED
PLATE_NUMBER_ALREADY_EXISTS
ROLE_MISMATCH
USER_BLOCKED
USER_INACTIVE
FORBIDDEN
UNAUTHORIZED
VALIDATION_ERROR
NOT_FOUND
SERVER_ERROR
Use standard project error format:
{
  "success": false,
  "error": {
    "code": "DRIVER_NOT_APPROVED",
    "message": "Driver must be approved before this action",
    "details": {}
  }
}

24. Tests to add or update
Add tests without removing existing tests.
Auth/profile creation tests:
driver verify-otp creates user and driver_profile in one transaction
driver_profiles.user_id is unique
new driver verification_status = new
new driver is_available = false
same phone cannot register as both client and driver
existing driver missing profile gets safe fallback profile
fallback does not create duplicate profile
Driver profile tests:
driver can get own profile
driver cannot get another driver's profile
driver can update full_name
driver can update car_model
driver can update car_color
driver can update plate_number
plate_number_normalized is generated
driver cannot update verification_status
driver cannot update rating
driver cannot update completed_orders
driver cannot update role
Availability tests:
new driver cannot set is_available=true
pending driver cannot set is_available=true
rejected driver cannot set is_available=true
blocked driver cannot set is_available=true
approved driver can set is_available=true
approved driver can set is_available=false
availability change writes audit log if audit exists
Document tests:
driver can upload passport
driver can upload selfie
driver can upload license
driver can upload car_document
driver can upload car_photo
driver cannot upload pickup_proof
driver cannot upload delivery_proof
invalid file type rejected
too large file rejected
uploading required document sets verification_status=pending if status was new/rejected
driver cannot upload document for another driver
Admin verification tests:
operator can view driver list
operator cannot approve driver
operator cannot reject driver
operator cannot block driver
admin cannot approve driver with missing documents
admin can approve driver with all required documents
approve sets verification_status=approved
approve keeps is_available=false
admin can reject driver with reason
reject sets verification_status=rejected and is_available=false
reject requires reason
admin can block driver with reason
block sets verification_status=blocked
block sets is_available=false
block sets routes unavailable
block revokes refresh sessions if implemented
block requires reason
Route/feed/bid security tests:
new driver cannot see feed
pending driver cannot see feed
rejected driver cannot see feed
blocked driver cannot see feed
approved but unavailable driver cannot see feed
approved available driver with matching route can see feed
wrong route driver cannot see feed
blocked driver cannot bid
unapproved driver cannot bid
unavailable driver cannot bid
Contact visibility tests:
approved driver before selected cannot see sender_phone
approved driver before selected cannot see receiver_phone
approved driver before selected cannot see full pickup_address
approved driver before selected cannot see full dropoff_address
assigned driver after selection can see full contact data
unselected driver after selection cannot see full contact data

25. Manual QA checklist
Run this manually after tests.
25.1 Driver registration
1. Register driver via OTP.
2. Verify user role = driver.
3. Check driver_profiles row exists.
4. Check verification_status = new.
5. Check is_available = false.
25.2 Driver profile
1. Login as driver.
2. GET /driver/profile.
3. PATCH /driver/profile with full_name, car_model, car_color, plate_number.
4. Confirm restricted fields cannot be changed.
25.3 Availability before approval
1. Try PATCH /driver/availability is_available=true.
2. Expect DRIVER_NOT_APPROVED.
25.4 Documents and approval
1. Upload passport.
2. Upload selfie.
3. Upload license.
4. Upload car_document.
5. Upload car_photo.
6. Login as admin.
7. Approve driver.
8. Check verification_status = approved.
9. Check is_available still false.
25.5 Availability after approval
1. Login as driver.
2. Set is_available=true.
3. Confirm success.
25.6 Blocking
1. Login as admin.
2. Block driver with reason.
3. Confirm verification_status=blocked.
4. Confirm is_available=false.
5. Confirm driver routes unavailable.
6. Confirm driver cannot see feed or bid.

26. Implementation notes
Keep code modular.
Recommended service functions:
ensure_driver_profile(user_id)
create_driver_profile_for_user(user)
normalize_plate_number(plate_number)
validate_driver_can_be_available(driver_profile)
validate_driver_can_access_feed(driver_profile)
validate_driver_can_bid(driver_profile, route)
validate_driver_documents_complete(driver_profile)
block_driver(driver_profile, reason, actor)
approve_driver(driver_profile, actor)
reject_driver(driver_profile, reason, actor)
Recommended dependencies:
require_driver
require_approved_driver
require_approved_available_driver
require_admin_or_super_admin
require_operator_admin_or_super_admin
Do not duplicate permission logic inside every endpoint if dependency helpers already exist.

27. Stop condition
After implementing this update, stop.
Report:
1. What was changed
2. Files changed
3. Migrations created if any
4. Whether driver_profiles.user_id unique exists
5. Whether driver profile auto-create is transaction-safe
6. Whether availability rules are enforced
7. Whether document completeness is enforced before approve
8. Whether block disables availability/routes/sessions
9. Tests added/updated
10. Test command and result
11. Manual QA steps
12. Any assumptions
13. Any TODOs
Do not continue to other stages until this update is reviewed and tests pass.