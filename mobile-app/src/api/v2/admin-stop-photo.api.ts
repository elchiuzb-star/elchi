/**
 * Q27 stop evidence photo (DESIGN-ADMIN-DIFF 13b.4): the image goes through the v1 private upload route with the
 * dedicated `stop_photo` type (staff with `ops.corridor_manage` only, app/api/v1/files.py), and the returned signed
 * `file_url` is what the stop command takes as `meeting_photo_file_id` — the server resolves it to the stored key
 * and checks that the same staff member uploaded it (geo/service.py `_resolve_meeting_photo`).
 */
import { adminApiRequest } from "../admin.api";

export type UploadedStopPhoto = { file_url: string; original_filename?: string | null };

export function uploadStopPhoto(file: File) {
  const form = new FormData();
  form.append("file", file);
  form.append("type", "stop_photo");
  return adminApiRequest<UploadedStopPhoto>("/files/upload", { method: "POST", body: form });
}
