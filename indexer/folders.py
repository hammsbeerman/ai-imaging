from __future__ import annotations

from indexer.models import Folder, Image, PreviewStatus


def normalize_rel_dir(path: str) -> str:
    path = (path or "").replace("\\", "/").strip("/")
    if path in ("", "."):
        return ""
    return path


def split_parts(rel_dir: str) -> list[str]:
    rel_dir = normalize_rel_dir(rel_dir)
    if not rel_dir:
        return []
    return [p for p in rel_dir.split("/") if p]


def ensure_folder_chain(root_id: int | None, relative_dir: str) -> Folder | None:
    if not root_id:
        return None

    rel_dir = normalize_rel_dir(relative_dir)
    parts = split_parts(rel_dir)
    if not parts:
        return None

    parent = None
    built = []

    for depth, part in enumerate(parts, start=1):
        built.append(part)
        rel_path = "/".join(built)

        folder, _ = Folder.objects.get_or_create(
            root_id=root_id,
            path=rel_path,
            defaults={
                "rel_path": rel_path,
                "name": part,
                "depth": depth,
                "parent": parent,
                "has_children": False,
                "customer_name": "",
                "probable_job_number": "",
            },
        )

        dirty = False

        parent_id = parent.id if parent else None
        if folder.parent_id != parent_id:
            folder.parent = parent
            dirty = True

        if folder.depth != depth:
            folder.depth = depth
            dirty = True

        if folder.rel_path != rel_path:
            folder.rel_path = rel_path
            dirty = True

        if folder.name != part:
            folder.name = part
            dirty = True

        if dirty:
            folder.save(update_fields=["parent", "depth", "rel_path", "name"])

        if parent and not parent.has_children:
            parent.has_children = True
            parent.save(update_fields=["has_children"])

        parent = folder

    return parent


def attach_image_to_folder(image: Image) -> Folder | None:
    if not image.root_id:
        if image.folder_id is not None:
            image.folder = None
            image.save(update_fields=["folder"])
        return None

    leaf = ensure_folder_chain(image.root_id, image.relative_dir)
    if leaf is None:
        if image.folder_id is not None:
            image.folder = None
            image.save(update_fields=["folder"])
        return None

    if image.folder_id != leaf.id:
        image.folder = leaf
        image.save(update_fields=["folder"])

    folder_updates = []

    if not leaf.customer_name and image.customer_name:
        leaf.customer_name = image.customer_name
        folder_updates.append("customer_name")

    if not leaf.probable_job_number and image.probable_job_number:
        leaf.probable_job_number = image.probable_job_number
        folder_updates.append("probable_job_number")

    if leaf.preview_image_id is None and image.preview_status == PreviewStatus.OK:
        leaf.preview_image_id = image.id
        folder_updates.append("preview_image")

    if folder_updates:
        leaf.save(update_fields=folder_updates)

    return leaf


def refresh_folder_for_image(image_id):
    img = Image.objects.select_related("root", "folder").get(id=image_id)
    return attach_image_to_folder(img)