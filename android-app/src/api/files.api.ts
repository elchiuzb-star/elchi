import { buildUrl, unwrapEnvelope } from "./http";
import { getAccessToken } from "../auth/tokenStorage";
import type { DriverDocumentType } from "../types/driver";

export type UploadFileType = "cargo_photo" | DriverDocumentType;

export type UploadedFile = {
  file_url: string;
  type?: string;
  mime_type?: string;
  size_bytes?: number;
};

// React Native file descriptor produced by expo-image-picker / expo-document-picker.
// RN's FormData + XMLHttpRequest serialise `{ uri, name, type }` into a multipart
// file part natively (it streams the file from disk).
export type RNFile = {
  uri: string;
  name: string;
  type: string;
  /** Optional byte size (expo-image-picker exposes this as `fileSize`). */
  size?: number;
};

/**
 * Upload a local file as multipart/form-data.
 *
 * NOTE: this deliberately uses XMLHttpRequest rather than `fetch`. Expo SDK 52+
 * installs a spec-compliant ("winter") global fetch whose FormData conversion
 * only accepts strings/Blobs — it explicitly does NOT support React Native's
 * `{ uri, name, type }` file part and throws
 * "Unsupported FormDataPart implementation" (see expo/src/winter/fetch/
 * convertFormData.ts). RN's XHR still handles the native file URI correctly,
 * so file uploads must go through it.
 */
export function uploadFile(file: RNFile, fileType: UploadFileType): Promise<UploadedFile> {
  const formData = new FormData();
  // `as any`: RN's FormData accepts the { uri, name, type } shape, which the
  // DOM FormData lib types don't model.
  formData.append("file", file as any);
  formData.append("type", fileType);
  return xhrPostForm<UploadedFile>("/files/upload", formData);
}

function xhrPostForm<T>(path: string, formData: FormData): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", buildUrl(path));

    const token = getAccessToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    // Content-Type is intentionally left unset: RN fills in the multipart
    // boundary itself.

    xhr.onload = () => {
      let parsed: unknown = null;
      try {
        parsed = JSON.parse(xhr.responseText);
      } catch {
        parsed = null;
      }
      try {
        resolve(unwrapEnvelope<T>(xhr.status, parsed));
      } catch (error) {
        reject(error);
      }
    };
    // Mirror fetch's failure shape so getUzbekErrorMessage reports a
    // connectivity problem rather than a generic error.
    xhr.onerror = () => reject(new TypeError("Network request failed"));
    xhr.ontimeout = () => reject(new TypeError("Network request failed"));

    xhr.send(formData);
  });
}
