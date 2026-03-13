import os


def _rel_from_scan(scan_path: str, full_path: str) -> str:
    rel = os.path.relpath(full_path, scan_path)
    rel = rel.replace("\\", "/")
    return rel


def folder_rel(scan_path: str, full_path: str) -> str:
    rel = _rel_from_scan(scan_path, full_path)
    return os.path.dirname(rel).replace("\\", "/")


def build_unc_folder(base_unc: str, folder_rel_path: str) -> str:
    base = (base_unc or "").rstrip("\\/")
    rel = (folder_rel_path or "").strip("/").replace("/", "\\")
    return base + (("\\" + rel) if rel else "")


def build_smb_folder(base_smb: str, folder_rel_path: str) -> str:
    base = (base_smb or "").rstrip("/")
    rel = (folder_rel_path or "").strip("/")
    return base + (("/" + rel) if rel else "")