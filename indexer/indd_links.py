import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict


def _norm(p: str) -> str:
    return os.path.normpath(os.path.abspath(p))


def find_sibling_pdf(indd_path: str) -> str | None:
    p = Path(indd_path)
    candidate = p.with_suffix(".pdf")
    return str(candidate) if candidate.exists() else None


def find_sibling_idml(indd_path: str) -> str | None:
    p = Path(indd_path)
    candidate = p.with_suffix(".idml")
    return str(candidate) if candidate.exists() else None


def discover_package_links_folder(indd_path: str) -> list[str]:
    p = Path(indd_path)
    folder = p.parent / "Links"
    if not folder.exists() or not folder.is_dir():
        return []

    found = []
    for root, _, files in os.walk(folder):
        for name in files:
            found.append(_norm(os.path.join(root, name)))
    return found


def parse_idml_links(idml_path: str) -> List[Dict]:
    """
    Very practical parser:
    - walks the zip
    - looks for XML files
    - extracts attributes commonly used for linked resources
    """
    links = []
    seen = set()

    attr_names = {
        "LinkResourceURI",
        "FilePath",
        "AssetURL",
        "URI",
    }

    with zipfile.ZipFile(idml_path, "r") as zf:
        xml_files = [n for n in zf.namelist() if n.lower().endswith(".xml")]

        for name in xml_files:
            try:
                data = zf.read(name)
                root = ET.fromstring(data)
            except Exception:
                continue

            for elem in root.iter():
                for key, value in elem.attrib.items():
                    if key.split("}")[-1] in attr_names and value:
                        val = value.replace("file:", "").replace("///", "/")
                        val = val.strip()
                        if val and val not in seen:
                            seen.add(val)
                            links.append({
                                "raw_path": val,
                                "source": "idml",
                                "xml_file": name,
                            })

    return links


def resolve_link_paths(indd_path: str, raw_links: List[Dict]) -> List[Dict]:
    """
    Try to resolve relative or weird IDML paths against:
    - the indd folder
    - the Links folder
    """
    base_dir = Path(indd_path).parent
    links_dir = base_dir / "Links"

    resolved = []
    seen = set()

    for item in raw_links:
        raw = item["raw_path"]
        candidates = []

        raw_path = Path(raw)
        if raw_path.is_absolute():
            candidates.append(raw_path)

        candidates.append(base_dir / raw)
        candidates.append(links_dir / Path(raw).name)
        candidates.append(base_dir / Path(raw).name)

        chosen = None
        for c in candidates:
            try:
                c2 = c.resolve()
            except Exception:
                c2 = c
            if c2.exists():
                chosen = str(c2)
                break

        payload = {
            "raw_path": raw,
            "resolved_path": chosen,
            "exists": bool(chosen and os.path.exists(chosen)),
            "source": item.get("source", "idml"),
            "xml_file": item.get("xml_file"),
        }

        key = (payload["raw_path"], payload["resolved_path"])
        if key not in seen:
            seen.add(key)
            resolved.append(payload)

    return resolved


def collect_indd_relationships(indd_path: str) -> dict:
    sibling_pdf = find_sibling_pdf(indd_path)
    sibling_idml = find_sibling_idml(indd_path)
    package_links = discover_package_links_folder(indd_path)

    idml_links = []
    if sibling_idml:
        raw_links = parse_idml_links(sibling_idml)
        idml_links = resolve_link_paths(indd_path, raw_links)

    package_payload = [
        {
            "raw_path": p,
            "resolved_path": p,
            "exists": True,
            "source": "package_links",
            "xml_file": None,
        }
        for p in package_links
    ]

    return {
        "sibling_pdf": sibling_pdf,
        "sibling_idml": sibling_idml,
        "links": idml_links + package_payload,
    }