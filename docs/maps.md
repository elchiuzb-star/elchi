Project: Elchi city-to-city taxi/cargo app

Task: Improve pickup/delivery location UX and validation.

Current context:

* We have regions/cities/districts in DB.
* User selects From and To locations.
* User can also choose coordinates on map.
* We need district-based default coordinates and consistency validation between selected region/district and map marker.

Implement the following:

1. Database changes

Add center coordinates to districts table:

* center_lat: float / numeric, nullable for now
* center_lng: float / numeric, nullable for now

If there are existing seed files for Uzbekistan regions/districts, update them with approximate district center coordinates.

Important:

* Exact house-level accuracy is not required.
* These coordinates are default map center / default marker position only.
* User can still move the marker manually.

2. Frontend behavior: district selected → auto marker

For both pickup and destination:

When user selects:

* region
* district/city

Then:

* get selected district `center_lat` and `center_lng`
* move map camera to this coordinate
* place marker automatically
* save these coordinates into the form state:

  * pickup_lat
  * pickup_lng
  * delivery_lat
  * delivery_lng

If the user later drags/clicks marker manually, update coordinates from marker.

3. UX logic

Location form should work like this:

From:

* Select region
* Select district/city
* Marker automatically appears at district center
* User may optionally adjust marker

To:

* Select region
* Select district/city
* Marker automatically appears at district center
* User may optionally adjust marker

Do not force the user to select map marker manually after district selection.

4. Validation problem to solve

Example issue:
User selects:

* Region: Samarqand
* District: Samarqand city

But then moves marker to another region, for example Toshkent or Andijon.

This must not silently pass.

5. Backend validation

On order create/update, validate coordinates against selected region/district.

Use reverse geocoding or boundary-based check depending on what already exists in the project.

Preferred logic:

A) If we already have district polygons/boundaries:

* Check if pickup_lat/lng is inside selected pickup district boundary.
* Check if delivery_lat/lng is inside selected delivery district boundary.

B) If polygon boundaries do not exist yet:

* Use reverse geocoding to detect actual region/district from coordinates.
* Compare actual detected region/district with selected region/district.

Validation rules:

* If coordinate belongs to a different region:

  * reject request with clear error.
* If coordinate belongs to same region but different district:

  * reject or return warning depending on existing UX.
  * For MVP, reject with clear error.

Example error messages:

* "Tanlangan pickup koordinata Samarqand viloyatiga tegishli emas."
* "Pickup marker tanlangan tumandan tashqarida. Iltimos, tumanni o‘zgartiring yoki marker joyini to‘g‘rilang."
* "Delivery marker tanlangan tumandan tashqarida. Iltimos, tumanni o‘zgartiring yoki marker joyini to‘g‘rilang."

6. Frontend validation / warning

When user moves marker:

* call reverse geocoding/check-location endpoint
* detect actual region/district
* compare with selected region/district

If mismatch:

* show warning immediately under map:

  * "Marker tanlangan viloyat/tumanga mos emas"
* disable order submit button until fixed

User can fix by:

* moving marker back
* or changing selected region/district to match marker

7. Add API endpoint if missing

Create endpoint:

POST /api/v1/geo/validate-location

Request:
{
"lat": 40.123,
"lng": 69.123,
"region_id": "...",
"district_id": "..."
}

Response if valid:
{
"valid": true,
"detected_region_id": "...",
"detected_district_id": "...",
"message": "OK"
}

Response if invalid:
{
"valid": false,
"detected_region_id": "...",
"detected_district_id": "...",
"message": "Marker tanlangan viloyat/tumanga mos emas"
}

Use the same validation service in backend order creation too. Frontend validation is only for UX, backend validation is required for safety.

8. Important edge cases

* If district center coordinates are missing:

  * do not crash
  * keep map unchanged
  * show message: "Bu tuman uchun default koordinata topilmadi"
* If reverse geocoding fails:

  * frontend should show soft warning
  * backend should not accept invalid/unverified coordinates unless project already has fallback logic
* If user selects new district after manually moving marker:

  * reset marker to new district center
* If user changes only region:

  * clear selected district and coordinates

9. Files to update

Find and update relevant files yourself:

* DB models
* Alembic migrations
* seed data
* Pydantic schemas
* geo/reverse geocoding service
* order create/update validation
* frontend location selector component
* map picker component
* order form state and submit validation

10. Acceptance criteria

* Selecting Andijon → Shahrixon automatically places marker around Shahrixon center.
* Selecting Samarqand → Samarqand city, then moving marker to another region shows warning.
* Backend rejects order if selected district/region does not match marker coordinate.
* User can submit order without manually clicking map if district has center coordinates.
* Pickup and delivery both work the same way.
* Existing flows must not break.
* Add/update tests where possible.
