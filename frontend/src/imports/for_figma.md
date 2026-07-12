# Elchi UI Specification for Figma

This document describes the complete Elchi product UI in English so a designer can recreate the mobile apps and admin panel in Figma. It covers product scope, roles, flows, screens, components, states, micro-interactions, and data requirements.

## 1. Product Summary

Elchi is an intercity parcel delivery marketplace for Uzbekistan.

The platform has three main user surfaces:

1. Client mobile app: customers create parcel delivery orders, choose route and exact pickup/dropoff map points, receive driver bids, select a driver, confirm delivery, rate the driver, manage notifications, and edit their profile.
2. Driver mobile app: drivers complete profile and documents, wait for admin approval, add service routes, see matched orders, send bids, manage active deliveries, view order history, and track net income after platform commission.
3. Admin web panel: operators/admins/super admins monitor orders, drivers, clients, regions, tariffs, disputes, staff users, notifications, audit logs, profile, and system commission settings.

Core business flow:

1. Client creates an order.
2. Client publishes the order.
3. Approved and available drivers with matching routes see the order.
4. Drivers send price bids.
5. Client selects one bid.
6. Order becomes accepted.
7. Assigned driver updates status: accepted -> picked up -> in transit -> delivered.
8. Client confirms delivery.
9. Client can rate the driver.
10. Admin/operator can intervene where allowed.

Payment model:

- MVP is cash only.
- The platform commission is configured in admin settings.
- Driver income must show net earnings after platform commission.
- Existing completed orders keep their original commission values when the commission setting changes.

Geography model:

- Orders are city/region to city/region.
- Uzbekistan regions and districts are selectable.
- When a district is selected, the map should automatically focus that district.
- Exact pickup/dropoff addresses are selected on the map and must be visible to the assigned driver.

## 2. Roles and Permissions

### Client

Can:

- Register/login with phone number and OTP.
- Create, edit, publish, and cancel own orders where status allows.
- Choose from/to city or region.
- Choose from/to district where required.
- Mark exact pickup/dropoff location on map.
- Upload cargo photo.
- View own order list and details.
- View bids for own orders.
- Select a driver bid.
- Confirm delivered order.
- Rate driver after confirmation.
- Open disputes.
- Read notifications.
- Update client profile.

Cannot:

- See other clients' orders.
- See driver private data before selecting a bid.
- Access admin or driver-only functionality.

### Driver

Can:

- Register/login with phone number and OTP.
- Fill profile: full name, car model, car color, plate number.
- Upload required documents.
- Add, edit, or delete routes.
- Set availability only after approval.
- See matched orders only after approval and route match.
- Send bids for matched orders.
- Reject matched orders.
- View own active/completed/offered order history.
- View exact map address after being assigned.
- Update delivery status.
- View profile, rating, completed orders, total orders, disputes, car info.
- View net income, daily/monthly chart, recent earning orders.

Cannot:

- Become both client and driver with the same phone number.
- See private contact/address details before being assigned.
- Accept orders when not approved.
- Use availability toggle when not approved.

### Operator

Can:

- Access admin panel.
- View orders, drivers, clients, cities, tariffs, disputes, notifications, and basic operational data.
- Update order status or assign drivers where backend permits.
- Review disputes.

Cannot:

- Approve/reject/block drivers unless role permits.
- Change system commission.
- Manage staff users beyond allowed permissions.

### Admin

Can:

- Everything an operator can do.
- Approve/reject/block drivers.
- Manage regions, districts, tariffs.
- Block/unblock clients.
- Create/edit operator/admin staff users where allowed.
- View audit logs.
- Change driver platform commission.

### Super Admin

Can:

- Everything admin can do.
- Full staff management.
- Highest-level account role.

## 3. Global Design Direction

### Mobile App

Design personality:

- Practical, calm, service-oriented.
- High clarity over decorative visuals.
- Feels similar to a transport/order app, with strong map-first patterns.

Recommended mobile frame:

- Primary: 390 x 844 or iPhone 14/15.
- Also check: 360 x 800 and 430 x 932.

Layout rules:

- Use a full-height app shell.
- Primary content uses vertical scroll.
- Bottom navigation exists on main client and driver sections.
- Detail flows use a top bar with back button.
- Map screens should use a full-bleed map background with bottom sheet controls.
- Avoid landing-page hero layouts inside the app.

Visual style:

- Background: light neutral gray (`#F7F8FA`) for main screens.
- Cards: white, 14-18px radius on mobile.
- Primary action: blue (`#1B4FD8` or close).
- Success: green.
- Warning: amber.
- Danger: red.
- Text: near-black for primary (`#111827`), gray for secondary (`#6B7280`).
- Icons: use simple line icons similar to Lucide.

### Admin Panel

Design personality:

- Operational, dense, scan-friendly.
- Dashboard and tables must be easy to compare and filter.
- Avoid oversized marketing sections.

Recommended desktop frame:

- 1440 x 900.
- Also check: 1280 x 800 and 1920 x 1080.

Layout rules:

- Left sidebar navigation.
- Sidebar can collapse.
- Top header includes page title, role, refresh, logout.
- Main content area uses tables, filters, metric cards, detail drawers, and modals.
- All tables must horizontally scroll if needed and must not overflow the page.
- Cards should be individual data cards, not nested inside other cards.

Admin visual style:

- Sidebar: very dark navy/black.
- Active nav item: white background or highlighted row.
- Main background: light gray.
- Surfaces: white, 8px radius.
- Tables: compact row height, uppercase small header labels.
- Buttons: icon + label for clear commands; icon-only for small table actions with tooltip/title.

## 4. Global UI Components

### Buttons

Primary button:

- Filled blue background.
- White text.
- Used for final/positive actions: publish order, save, submit bid, confirm, approve, assign.

Secondary button:

- White or light gray background.
- Border.
- Used for navigation or non-destructive actions.

Danger button:

- Red border or red background depending on priority.
- Used for cancel order, block user, reject driver, logout.

Icon button:

- Compact square or circular button.
- Must include tooltip/title in web admin.
- Used for edit, delete, view, close, refresh, search, upload, locate.

Disabled state:

- Lower opacity or gray background.
- Cursor disabled in web.
- Must clearly indicate missing requirements.

### Form Fields

Mobile:

- Label above input.
- 44-48px input height.
- Rounded 10-14px.
- Clear placeholder examples.

Admin:

- 36-40px input height.
- Compact labels.
- Search fields should include Search icon.
- Select fields for status, role, region, tariff, phone verification, limit.

### Cards

Mobile:

- Use cards for grouped data: order summary, driver profile, route, income, status, vehicle.
- Radius 14-18px.
- Border `#E5E7EB`.
- Padding 14-20px.

Admin:

- Metric cards: label, large value, icon, note.
- Tables and filters in white bordered surfaces.
- Detail drawers on right side.

### Badges

Status badges must use consistent colors:

- Draft/new/inactive: slate/gray.
- Published/bidding/active informational: blue.
- Accepted/picked up/in transit/warning: amber or blue depending on stage.
- Delivered/confirmed/approved/success: green.
- Cancelled/rejected/blocked/error: red.
- Disputed/open issue: rose/amber.

### Empty States

Use an icon, title, optional subtitle, and optional action.

Examples:

- "No orders yet"
- "No matching orders yet"
- "No bids yet"
- "No notifications yet"
- "No routes added yet"
- "No clients found"
- "No tariffs found"

### Loading States

Mobile:

- Full-screen or inline empty state with spinner for initial load.
- Buttons should show disabled state while busy.

Admin:

- Skeleton rows in tables.
- Metric cards may show zero while loading only if there is no data yet.
- Error banners for fetch failures.

### Error States

Use red/rose bordered alert banners.

Common copy style:

- Short, actionable, non-technical.
- Example: "Orders data could not be loaded."
- Example: "Map point does not match the selected region/district."

## 5. Authentication Flow

### Splash Screen

Purpose:

- Short branded start screen.

Elements:

- Elchi logo/name.
- Loading indicator or calm static state.

### Onboarding Screen

Purpose:

- Introduce the service.

Elements:

- Short value proposition.
- Primary CTA to continue.
- Light illustration or service-related visual.

### Role Selection

Purpose:

- User selects account type before OTP.

Cards:

- "I am a client" / parcel sending.
- "I am a driver" / accept delivery orders.

Important rule:

- One phone number can belong to only one public role: client or driver.
- If phone already exists, login should continue with that existing role, not create a duplicate.
- If phone exists under another role, prevent dual-role registration.

### Phone Login

Elements:

- Top bar with back.
- Phone input.
- Role context.
- Primary button: request OTP.
- Error state for invalid phone or blocked account.

### OTP Verification

Elements:

- Top bar with back.
- OTP input.
- Resend logic.
- Verify button.
- After login, route user by actual backend role:
  - client -> client home.
  - driver -> driver home.
  - admin/operator/super_admin -> admin panel if in web admin context.

## 6. Client Mobile App

### Client Bottom Navigation

Tabs:

1. Home
2. Orders
3. Notifications
4. Profile

Behavior:

- Visible on main client screens.
- Active tab highlighted in blue.
- Hidden or replaced by top-bar flows during deep forms where needed.

### Client Home: Map Order Start

Purpose:

- Start creating a parcel delivery order using city/district and map address selection.

Layout:

- Full-bleed map background.
- Current location button floating on map.
- Bottom sheet over the map.

Bottom sheet elements:

- Drag handle.
- Title: send parcel.
- Subtitle: choose city and exact address, receive driver bids.
- Pickup row:
  - icon/navigation marker.
  - selected address title.
  - selected city/region.
  - change button.
- Dropoff row:
  - pin icon.
  - selected address title.
  - selected city/region.
  - change button.
- Stats row:
  - active orders.
  - bids.
  - completed.
- Primary button:
  - "View route" or continue.
  - Disabled until both city/address selections are valid.
- Validation error text:
  - If city not selected.
  - If address is missing.

Map behavior:

- If user selects a district, map automatically centers on that district.
- If Google Maps key/map ID is missing or fails, show clear fallback UI.
- Map should allow exact marker placement.
- Selected pickup/dropoff coordinates must be saved with the order.

### Client Location Selector

Purpose:

- Choose pickup or dropoff city/region.

Elements:

- Top bar with back.
- Search field.
- List of regions/cities.
- If city requires districts, proceed to district selector.
- If not, proceed to map picker.

### Client District Selector

Purpose:

- Choose a district inside selected region.

Elements:

- Top bar.
- Search field.
- District list.
- Empty state when no districts match.

Behavior:

- On district select, open map picker centered on district.

### Client Google Map Picker

Purpose:

- Choose exact pickup/dropoff point.

Elements:

- Full-screen Google map.
- Top bar/back button.
- Search box for address/place.
- Marker for selected location.
- Locate/current position button where supported.
- Bottom confirmation panel:
  - selected address.
  - warning if point does not match selected region/district.
  - manual address input when needed.
  - confirm button.

Behavior:

- Geocode selected district/city when opened.
- Tap map to set marker.
- Reverse geocode marker to address.
- Validate marker against selected region/district.
- Allow confirmation only when point is valid enough for MVP.

### Client Route Summary

Purpose:

- Review selected from/to route before address/contact details.

Elements:

- Top bar: route or edit order title.
- Route rows:
  - From city/district.
  - To city/district.
  - Pickup exact address.
  - Dropoff exact address.
- Suggested price if tariff exists.
- Primary button to continue.
- Cancel edit button when editing an existing order.

### Client Route Selection Fallback

Purpose:

- City-only route selection if map-first flow needs a fallback.

Elements:

- From city selector.
- To city selector.
- Suggested route price.

### Client Contact and Address Details

Purpose:

- Enter sender/receiver contact data.

Fields:

- Sender phone.
- Receiver phone.
- Pickup address.
- Dropoff address.
- Optional comment.

Validation:

- Sender and receiver phone required.
- Pickup/dropoff address required.
- City IDs required.

### Client Cargo Photo

Purpose:

- Upload parcel image.

Elements:

- Upload card with Camera/Upload icon.
- Preview after upload.
- File upload progress/busy state.
- Primary continue button.

File rules:

- Cargo photo allowed.
- Max around 5 MB.

### Client Order Review

Purpose:

- Final check before publishing or saving edits.

Elements:

- Top bar: "Review order" or "Review changes".
- Summary cards:
  - route.
  - pickup address.
  - dropoff address.
  - sender phone.
  - receiver phone.
  - suggested price.
  - cargo photo.
  - comment.
- Primary button:
  - create/publish order.
  - save changes when editing.
- Secondary edit button.

### Client Success

Purpose:

- Confirm order was published.

Elements:

- Success icon.
- Message.
- CTA to view order or return home.

### Client Orders List

Purpose:

- Show client's orders.

Elements:

- Top title.
- Order cards.
- Filters/tabs may include active/completed/cancelled.
- Empty state.
- Bottom nav visible.

Order card content:

- Route: from -> to.
- Status badge.
- Suggested/final price.
- Date.
- Short pickup/dropoff info.

### Client Order Detail

Purpose:

- Main detail page for one order.

Elements:

- Top bar.
- Order card.
- Timeline/status progress.
- Pickup/dropoff detail.
- Map preview/markers if coordinates exist.
- Assigned driver card after selection.
- Bid summary or empty bids state.
- Action buttons depending on status.

Actions by status:

- draft/published/bidding: edit order.
- published/bidding: view bids.
- delivered: confirm delivery.
- eligible statuses: cancel order.
- any issue state: open dispute.

### Client Bids Screen

Purpose:

- Compare driver offers.

Elements:

- Top bar.
- List of bid cards.
- Each bid card:
  - driver name.
  - driver rating.
  - vehicle info if available.
  - bid price.
  - bid status.
  - select driver button.
- Empty state while no bids exist.

Selection confirmation:

- Bottom sheet/modal confirming selected bid.
- Primary confirm button.
- Secondary cancel.

### Client Confirm Delivery

Purpose:

- Confirm cash delivery completion.

Elements:

- Top bar.
- Order summary.
- Payment note: cash/manual.
- Confirm button.

### Client Rating

Purpose:

- Rate assigned driver after confirmed order.

Elements:

- Star rating 1-5.
- Optional comment.
- Submit button.

### Client Dispute

Purpose:

- Report a problem with an order.

Fields:

- Reason.
- Comment.

States:

- Submit loading.
- Success message.
- Validation error.

### Client Notifications

Purpose:

- Show order and bid updates.

Elements:

- Top bar.
- Notification list.
- Unread visual state.
- Each item:
  - title.
  - message.
  - date.
  - related order route/order number where available.
- Tap notification:
  - mark as read.
  - open related order if entity type is order.

Notification examples:

- New bid received.
- Driver selected.
- Order status changed.
- Delivery completed.
- Dispute update.

### Client Profile

Purpose:

- Manage customer account and quick actions.

Elements:

- Profile header:
  - avatar/icon.
  - full name.
  - phone.
- Personal data card:
  - full name input.
  - save button.
- Quick actions:
  - My orders.
  - Notifications.
  - Home.
  - Logout.
- Bottom nav visible.

## 7. Driver Mobile App

### Driver Bottom Navigation

Tabs:

1. Home
2. Routes
3. Orders
4. Profile

Behavior:

- Visible on main driver screens.
- Active tab highlighted.

### Driver Home

Purpose:

- Main operational dashboard for the driver.

Top area:

- Title:
  - Approved: "Home".
  - Not approved: profile completion prompt.
- Small top-right "Net income" chip:
  - Label: net income.
  - Amount.
  - Chevron.
  - Opens income screen.

Important:

- Do not show a large "Income report" card on the home screen.
- Keep the compact net income chip.

Main cards:

- Verification status card:
  - current status.
  - approved copy: route-matched orders will appear when available.
  - not approved copy: fill profile and upload documents.
- Availability card:
  - label.
  - helper text.
  - toggle.
  - toggle disabled until approved.

Buttons:

- If driver is approved:
  - hide "Complete profile".
  - hide "Upload documents".
  - show "View matching orders".
- If driver is not approved:
  - show "Complete profile".
  - show "Upload documents".
  - do not allow availability.

### Driver Profile Form

Purpose:

- Collect driver and vehicle info.

Fields:

- Full name.
- Car model.
- Car color.
- Plate number.

Elements:

- Top bar with back.
- Save button.

Behavior:

- Save updates driver profile.
- Return to driver home after success.

### Driver Documents

Purpose:

- Upload verification documents.

Required document types:

- Passport.
- Selfie.
- Driver license.
- Car document.
- Car photo.

Each document row/card:

- Document label.
- Current status if available:
  - missing.
  - pending.
  - approved.
  - rejected.
- Upload button.
- Uploaded file preview where possible.

Behavior:

- Upload file.
- Submit document payload.
- Refresh profile.
- Driver status likely moves to pending when all required documents/profile data are submitted.

### Driver Routes

Purpose:

- Manage where the driver works.

Elements:

- Top bar.
- List of route cards.
- Empty state with "Add route".
- Bottom nav visible.

Route card:

- From city/district.
- To city/district.
- Status badge.
- Compact top-corner icon buttons:
  - edit (pencil icon).
  - delete/remove (trash icon).

Behavior:

- Edit opens route form with existing values.
- Delete disables/removes route.

### Driver Add/Edit Route

Purpose:

- Add or update route.

Fields:

- From city.
- From district optional/required depending region.
- To city.
- To district optional/required depending region.

Elements:

- Top bar title:
  - Add route.
  - Edit route.
- Save button.
- Cancel/back.

Validation:

- From and to city required.
- Same route should be prevented by backend or UI.

### Driver Feed: Matching Orders

Purpose:

- Show orders matched to approved/available driver's routes.

Elements:

- Title.
- Order cards.
- Empty state.
- Bottom nav visible.

Order card:

- Route.
- Status.
- Pickup/dropoff area only before assignment.
- Suggested price.
- Cargo photo if available.
- Driver's own bid if already submitted.

Actions:

- Send bid.
- Reject/not suitable.
- If own bid exists, show bid status and price.

Privacy:

- Before assignment, do not show full addresses or phone numbers.

### Driver Bid Screen

Purpose:

- Send price offer for an order.

Elements:

- Top bar.
- Order summary.
- Price input.
- Suggested price reference.
- Submit bid button.

Validation:

- Price required.
- Price must be greater than zero.

### Driver Orders History

Purpose:

- Show active, completed, and bid-related orders.

Elements:

- Title: order history.
- Order list.
- Own bid card when applicable.
- Income mini-cells for earning orders:
  - Gross.
  - Platform commission.
  - Net.
- Empty state if no orders.
- Bottom nav visible.

### Driver Order Detail

Purpose:

- Show assigned or visible order detail.

Elements:

- Top bar.
- Order card.
- Address/contact details:
  - pickup address.
  - dropoff address.
  - sender phone.
  - receiver phone.
  - comment.
- Income report block for earning orders:
  - gross.
  - system fee.
  - net.
- Map points block if coordinates exist:
  - button "View on map".
- Next status action button depending current state.

Status actions:

- accepted -> picked up.
- picked_up -> in transit.
- in_transit -> delivered.

Map behavior:

- Assigned driver must see exact pickup/dropoff map locations selected by the client.

### Driver Income Screen

Purpose:

- Show net earnings and chart.

Elements:

- Top bar: Income.
- Summary card:
  - net income.
  - helper text: after platform commission.
  - gross amount.
  - system commission amount.
- Chart card:
  - daily/monthly segmented control.
  - mini bar chart.
  - daily view: last 7 days.
  - monthly view: last 6 months.
- Recent earnings list:
  - route.
  - date.
  - net amount.
- Empty state if no earnings.

Important:

- Chart and displayed order earnings must use net income after platform commission.
- If backend provides exact `driver_income`, use it; otherwise fallback to commission calculation.

### Driver Profile

Purpose:

- Display driver account and quick actions.

Elements:

- Top bar with back.
- Profile header card:
  - avatar/truck icon.
  - full name.
  - phone.
  - verification badge.
  - availability badge.
- Stats row:
  - rating.
  - completed orders.
  - total orders.
- Availability card:
  - toggle.
  - disabled if not approved.
- Vehicle card:
  - car model/color/plate.
  - verification state.
  - route count.
  - dispute count.
- Quick actions:
  - edit profile.
  - documents.
  - routes.
  - orders.
  - home.
  - logout.
- Bottom nav visible.

## 8. Admin Web Panel

### Admin Shell

Layout:

- Fixed left sidebar.
- Main content area.
- Top header.

Sidebar:

- Brand: Elchi Admin.
- User role under brand.
- Collapse/expand button.
- Navigation items:
  1. Dashboard/Home
  2. Orders
  3. Drivers
  4. Clients
  5. Regions
  6. Tariffs
  7. Disputes
  8. Staff users
  9. Notifications
  10. Audit log
  11. Profile / Account

Top header:

- Current page title.
- Current role.
- Refresh button.
- Logout button.

Responsive:

- Tables must scroll horizontally.
- Sidebar collapsed state should show icons only.

### Admin Dashboard / Home

Purpose:

- Operational and financial snapshot.

Financial report cards:

- Total order amount.
- Platform profit/system income.
- Driver earnings.
- Average order value.
- Completed orders.
- Profit from completed orders.
- Active delivery amount.
- Today's platform profit.

Operations cards:

- Total orders.
- Published/bidding.
- Active deliveries.
- Delivered today.
- Confirmed.
- Pending drivers.
- Approved drivers.
- Open disputes.
- Active cities/regions.
- District issues.
- Active tariffs.
- Missing tariffs.

Panels:

- Pending actions.
- Recent orders.
- Driver verification queue.
- Disputes queue.
- Regions and tariffs health.
- Recent activity.
- Quick actions.

Interactions:

- Cards navigate to the relevant panel.
- Refresh reloads dashboard data.

### Admin Orders

Purpose:

- Full operational order management.

Tabs:

- All.
- Published.
- Bids.
- Accepted.
- Delivery in progress.
- Delivered.
- Confirmed.
- Cancelled.
- Disputed.

Filters:

- Search by code, phone, or driver.
- Status.
- Assigned driver search.
- Date range.
- Page size.

Summary cards:

- Total orders.
- Published/bidding.
- Accepted/active deliveries.
- Other operational counters.

Table columns:

- Order number/code.
- Status.
- From route.
- To route.
- Client/sender.
- Driver.
- Suggested/final price.
- Payment status.
- Created/updated.
- Actions.

Order detail drawer:

- Header:
  - order number.
  - status badge.
  - created/updated time.
- Tabs:
  - overview.
  - bids.
  - status history.
  - audit.
- Overview details:
  - from city/district.
  - to city/district.
  - suggested price.
  - final price.
  - payment method/status.
  - pickup address.
  - pickup coordinates.
  - dropoff address.
  - dropoff coordinates.
  - sender phone.
  - receiver phone.
  - cargo photo link/preview.
  - comment.
- Actions:
  - change status.
  - assign driver.
  - cancel order.
  - refresh.

Assign driver modal:

- One combined search/select field for approved eligible drivers.
- Search by name, phone, or plate number.
- Driver list dropdown.
- Selected driver indicator.
- Final price input.
- Required reason input.
- Assign button.

Change status modal:

- Status select.
- Reason input.
- Submit.

Cancel modal:

- Reason input.
- Confirm cancel.

### Admin Drivers

Purpose:

- Review and manage driver verification.

Tabs:

- All.
- New.
- Pending review.
- Approved.
- Rejected.
- Blocked.

Filters:

- Search by name, phone, plate.
- Verification status.
- Availability.
- Phone verification.
- Date range.

Summary cards:

- Total drivers.
- New.
- Pending.
- Approved.
- Rejected.
- Blocked.
- Available approved drivers.

Table columns:

- Driver.
- Phone.
- Vehicle.
- Verification status.
- Availability.
- Documents count.
- Routes count.
- Created.
- Actions.

Actions:

- View details.
- Approve.
- Reject.
- Block.

Driver detail drawer:

- Driver header:
  - name.
  - phone.
  - verification badge.
  - availability.
- Profile fields:
  - car model.
  - color.
  - plate number.
  - rating.
  - total/completed/cancelled orders.
  - disputes.
- Required documents section:
  - passport.
  - selfie.
  - driver license.
  - car document.
  - car photo.
- Each document card:
  - status.
  - file metadata.
  - view/open file button.
  - click uploaded file to preview in modal.
- Routes section:
  - from/to city/district.
  - status.
- Orders section when available.

Document preview modal:

- If image: show image.
- If PDF or browser-supported file: iframe.
- If unsupported: open file link.

Approval modal:

- Optional comment.
- Approve button.

Reject/block modal:

- Required reason.
- Suggested reasons.
- Warning copy.

### Admin Clients

Purpose:

- View and manage client accounts.

Summary cards:

- Loaded clients.
- Active.
- Blocked.
- Phone verified.
- With orders.
- Active orders.

Filters:

- Search by phone or name.
- Status.
- Phone verification.

Table columns:

- Client.
- Phone.
- Status.
- Verified.
- Orders count.
- Active orders.
- Last order.
- Created.
- Actions.

Actions:

- View details.
- Block client.
- Unblock client.

Client detail drawer:

- Name.
- Phone.
- Status.
- Phone verified.
- Total orders.
- Active orders.
- Completed orders.
- Cancelled orders.
- Last login.
- Last order.
- Created.
- Block/unblock action.

### Admin Regions / Cities

Purpose:

- Manage Uzbekistan regions/cities and districts.

Summary cards:

- Total regions.
- Active regions.
- Inactive regions.
- Requires district.
- Total districts.
- Regions missing districts.

Filters:

- Search by name, region, or type.
- Type.
- Active status.
- Requires district.
- Has districts.
- Limit/page size.

Table columns:

- ID.
- Uzbek name.
- Russian name.
- Region.
- Type.
- Requires district.
- District count.
- Active.
- Created.
- Actions.

Actions:

- View.
- Edit.
- Activate/deactivate.

City detail drawer:

- Basic city/region fields.
- Active status.
- District list.
- Add/edit district.
- District coordinates.

City modal:

- Name Uzbek.
- Name Russian.
- Region.
- Type: city, region, republic.
- Requires district checkbox.
- Display order.
- Active checkbox.

District modal:

- District name Uzbek.
- Name Russian.
- Active checkbox.
- Display order.
- Center latitude.
- Center longitude.

Important:

- All Uzbekistan regions and districts should be represented.
- District coordinates support map auto-centering in the client flow.

### Admin Tariffs

Purpose:

- Manage route pricing between cities/regions.

Summary cards:

- Total tariffs.
- Active tariffs.
- Inactive tariffs.
- Routes missing reverse tariff.
- Average suggested price.
- Highest suggested price.

Filters:

- Search by route, city, ID.
- From city.
- To city.
- Active status.
- Price from.
- Price to.
- Has reverse direction.
- Limit/page size.

Table columns:

- ID.
- Route.
- From city.
- To city.
- Suggested price.
- Min price.
- Max price.
- Currency.
- Active.
- Created.
- Updated.
- Actions.

Actions:

- View.
- Edit.
- Activate/deactivate.

Tariff detail drawer:

- Route summary.
- Suggested price.
- Min/max price.
- Currency.
- Active status.
- Reverse tariff status.
- Created/updated.

Tariff modal:

- From city.
- To city.
- Suggested price.
- Min price.
- Max price.
- Active checkbox.

Validation:

- From and to city cannot be same.
- Suggested/min/max must be non-negative.
- Min <= suggested <= max when values exist.
- Duplicate active tariff for same direction should be rejected.

### Admin Disputes

Purpose:

- Review and resolve reported order issues.

Table columns:

- ID.
- Order number.
- Reason.
- Status.
- Opened by.
- Created.

Detail:

- Order information.
- Reason/comment.
- Opened by user.
- Status update.
- Resolution text.

Statuses:

- open.
- in review.
- resolved.
- rejected/closed where backend supports.

### Admin Staff Users

Purpose:

- Manage operator/admin users.

Summary cards:

- Total.
- Operators.
- Administrators.
- Super administrators.
- Active.
- Blocked.

Filters:

- Search by phone or name.
- Role.
- Status.
- Phone verification.
- Date range.

Table columns:

- User.
- Phone.
- Role.
- Status.
- Phone verified.
- Created.
- Last login.
- Actions.

Actions:

- View.
- Create staff user.
- Edit staff user.
- Block/unblock.

Create/edit modal fields:

- Phone.
- Full name.
- Role: operator/admin.
- Status: active/blocked/inactive.

Rules:

- Super admin users should not be editable as normal staff where backend forbids.
- Public registration cannot create staff roles.

### Admin Notifications

Purpose:

- Admin-facing overview of notifications.

Expected UI:

- List/table of notifications.
- Filters by read/unread, type, channel, date.
- Columns:
  - recipient.
  - type.
  - title.
  - message.
  - entity.
  - channel.
  - read state.
  - sent/created date.

### Admin Audit Log

Purpose:

- Read-only operational audit trail.

Table columns:

- ID.
- Actor.
- Action.
- Entity type.
- Entity ID.
- Created.

Filters:

- Actor role.
- Action.
- Entity type.
- Entity ID.
- Date range.

Rules:

- Read-only.
- No create/edit/delete actions.
- Sensitive data should be redacted.

### Admin Profile / Account

Purpose:

- Current staff user account and settings.

Profile card:

- Avatar/icon.
- Full name.
- Phone.
- Status badge.
- Full name input.
- Save profile button.
- Role.
- Phone verified.
- Security note.
- Refresh profile.
- Logout.

System commission card:

- Driver platform commission percentage input.
- Save button.
- Only admin/super admin can edit.
- Helper copy:
  - Changes apply only to future accepted orders.
  - Existing order prices and fee calculations do not change.

## 9. Maps and Location UX

Map surfaces:

1. Client home map.
2. Client pickup picker.
3. Client dropoff picker.
4. Client route preview.
5. Driver/admin read-only order map.

Markers:

- Pickup marker: label A or navigation icon.
- Dropoff marker: label B or pin icon.
- Use clear contrast.

Location validation:

- If marker does not match selected district/region, show warning.
- Do not silently accept obviously mismatched points.

Fallback:

- If Google Maps API key is missing:
  - Show a friendly fallback panel.
  - Allow manual address/coordinate copy where reasonable.

Map deep links:

- Provide "Open in Google Maps" where useful for assigned driver/order details.

## 10. Data Objects Shown in UI

### Order

Fields commonly displayed:

- ID.
- Order number.
- Status.
- From city.
- To city.
- From district.
- To district.
- Pickup area/address.
- Dropoff area/address.
- Pickup coordinates.
- Dropoff coordinates.
- Sender phone.
- Receiver phone.
- Cargo photo.
- Suggested price.
- Final price.
- Payment method.
- Payment status.
- Assigned driver.
- Accepted bid.
- Comment.
- Created/updated timestamps.

### Bid

Fields:

- ID.
- Driver name.
- Driver ID.
- Price.
- Status.
- Created/updated timestamps.

### Driver Profile

Fields:

- ID.
- User phone.
- Full name.
- Car model.
- Car color.
- Plate number.
- Verification status.
- Availability.
- Rating.
- Total orders.
- Completed orders.
- Cancelled orders.
- Dispute count.
- Documents.
- Routes.

### Client Profile

Fields:

- User ID.
- Phone.
- Full name.
- Status.
- Phone verified.
- Orders count.
- Active orders.
- Completed/cancelled orders.
- Last login/order timestamps.

### Region / City

Fields:

- ID.
- Name Uzbek.
- Name Russian.
- Region.
- Type.
- Requires district.
- Display order.
- Active status.
- District counts.

### District

Fields:

- ID.
- City ID.
- Name Uzbek.
- Name Russian.
- Active status.
- Display order.
- Center latitude.
- Center longitude.

### Tariff

Fields:

- ID.
- From city.
- To city.
- Suggested price.
- Minimum price.
- Maximum price.
- Currency.
- Active status.
- Created/updated timestamps.

## 11. Status Vocabulary

### Order Statuses

- draft: created but not published.
- published: visible for matching.
- bidding: at least one bid exists.
- accepted: client selected driver.
- picked_up: driver picked parcel up.
- in_transit: parcel is on the way.
- delivered: driver marked as delivered.
- confirmed: client confirmed delivery.
- cancelled: cancelled by allowed party.
- disputed: dispute opened.

### Driver Verification Statuses

- new: profile not complete yet.
- pending: waiting for admin review.
- approved: can work.
- rejected: rejected by admin.
- blocked: blocked by admin.

### User Statuses

- active.
- inactive.
- blocked.
- deleted where backend uses it.

### Bid Statuses

- active.
- accepted.
- closed.
- rejected where applicable.

## 12. Important Edge Cases to Design

Authentication:

- Phone already registered.
- Phone registered under another role.
- OTP invalid.
- OTP expired.
- User blocked.

Client order:

- No cities loaded.
- District required but not selected.
- Map API not loaded.
- Address selected but city missing.
- No tariff found.
- No bids yet.
- Driver bids disappear or selected bid invalid.
- Order cannot be edited because status changed.

Driver:

- Profile incomplete.
- Documents incomplete.
- Waiting for admin approval.
- Approved but no routes.
- Approved but availability off.
- No matching orders.
- Bid already submitted.
- Route edit/delete confirmation.
- No earnings yet.

Admin:

- Authentication required.
- Data failed to load.
- Empty tables.
- Permission denied for operator.
- Driver missing documents.
- Uploaded file preview unsupported.
- Assign driver list empty.
- Tariff duplicate conflict.
- District missing coordinates.

## 13. Accessibility and Usability Notes

Mobile:

- Touch targets at least 44px.
- Important actions should be thumb-friendly near bottom.
- Text must not overlap at Uzbek/Russian names with long words.
- Avoid tiny text in buttons.
- Use clear disabled states.

Admin:

- All icon-only actions need tooltip/title.
- Keyboard focus states should be visible.
- Tables need horizontal scroll.
- Modals and drawers need clear close buttons.
- Error messages should be near the area that failed.

## 14. Suggested Figma Page Structure

Create these Figma pages:

1. Cover / Product Map.
2. Design System.
3. Mobile Auth.
4. Client App.
5. Driver App.
6. Admin Dashboard.
7. Admin Orders.
8. Admin Drivers.
9. Admin Clients.
10. Admin Regions and Tariffs.
11. Admin Staff / Settings / Audit.
12. Components and States.

## 15. Component Inventory for Figma

Mobile components:

- App shell.
- Top bar with back.
- Bottom navigation.
- Primary button.
- Secondary button.
- Danger button.
- Icon button.
- Text field.
- Select row.
- Search field.
- Status badge.
- Order card.
- Bid card.
- Route summary row.
- Location row.
- Upload card.
- Empty state.
- Confirmation sheet.
- Map picker sheet.
- Profile action row.
- Income metric card.
- Mini bar chart.
- Timeline/status stepper.

Admin components:

- Sidebar expanded/collapsed.
- Top header.
- Metric card.
- Filter bar.
- Search input.
- Select input.
- Date input.
- Data table.
- Table action icon button.
- Badge/pill.
- Detail drawer.
- Modal shell.
- Confirmation modal.
- Document preview modal.
- Tabs.
- Pagination footer.
- Alert banner.
- Skeleton table row.

## 16. Copy Tone

The implemented app uses Uzbek UI text. For Figma, create English-labelled design specs if desired, but production labels should remain Uzbek unless product direction changes.

Tone:

- Direct.
- Helpful.
- Operational.
- Avoid marketing-heavy language.

Example English design-copy equivalents:

- "Send parcel"
- "Choose route"
- "Pickup location"
- "Dropoff location"
- "Driver offers"
- "Net income"
- "Upload documents"
- "Verification status"
- "Assign driver"
- "System commission"
- "Audit log"

## 17. Final Design Acceptance Checklist

Mobile client:

- Client can start order from map.
- Client can select city, district, exact pickup/dropoff points.
- Client can review, publish, edit, and cancel allowed orders.
- Client can view bids and select driver.
- Client can confirm, rate, dispute, and read notifications.

Mobile driver:

- Driver sees profile/document onboarding if not approved.
- Approved driver does not see onboarding CTA on home.
- Driver can manage routes.
- Driver can see matched orders and bid.
- Driver can view order history.
- Driver can view assigned order exact map points.
- Driver can view compact net income on home and detailed income chart screen.

Admin:

- Sidebar is collapsible.
- Dashboard includes operational and financial metrics.
- Orders support detail, status update, driver assignment, cancellation.
- Drivers support verification and document preview.
- Clients support block/unblock.
- Regions include districts and coordinates.
- Tariffs support view/edit/activate/deactivate.
- Staff users support full name.
- Profile supports full name and driver commission setting.
- Tables do not overflow the viewport.

