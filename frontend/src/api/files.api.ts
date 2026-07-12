import { apiRequest } from "./http";
import type { DriverDocumentType } from "../types/driver";

export type UploadFileType = "cargo_photo" | DriverDocumentType;

export type UploadedFile = {
  file_url: string;
  type?: string;
  mime_type?: string;
  size_bytes?: number;
};

export function uploadFile(file: File, fileType: UploadFileType) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("type", fileType);
  return apiRequest<UploadedFile>("/files/upload", {
    method: "POST",
    body: formData,
  });
}
