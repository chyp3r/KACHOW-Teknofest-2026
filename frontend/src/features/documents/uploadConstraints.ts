export const MAX_UPLOAD_SIZE = 50 * 1024 * 1024;
export const ALLOWED_UPLOAD_EXTENSIONS = [
  "pdf",
  "txt",
  "doc",
  "png",
  "jpg",
  "jpeg",
  "tif",
  "tiff",
];

export function validateUploadFile(file: File): string | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!ALLOWED_UPLOAD_EXTENSIONS.includes(extension)) {
    return "Bu dosya türü desteklenmiyor.";
  }
  if (file.size > MAX_UPLOAD_SIZE) {
    return "Dosya boyutu 50 MB sınırını aşıyor.";
  }
  return null;
}
