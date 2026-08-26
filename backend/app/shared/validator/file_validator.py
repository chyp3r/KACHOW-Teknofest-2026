from typing import List

def validate_file_extension(filename: str, allowed_extensions: List[str]) -> bool:
    """Dosya uzantısının izin verilen liste içinde olup olmadığını kontrol eder.

    İzin veriliyorsa True, aksi halde False döner.
    """
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in [e.lower().lstrip(".") for e in allowed_extensions]
