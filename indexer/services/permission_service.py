from indexer.models import Image, UserAccessRoot


def get_allowed_root_ids(user) -> set[int]:
    if getattr(user, "is_superuser", False):
        return set(
            Image.objects.exclude(root__isnull=True).values_list("root_id", flat=True)
        )

    return set(
        UserAccessRoot.objects.filter(user=user).values_list("root_id", flat=True)
    )


def filter_images_for_user(qs, user):
    if getattr(user, "is_superuser", False):
        return qs

    allowed_root_ids = get_allowed_root_ids(user)
    if not allowed_root_ids:
        return qs.none()

    return qs.filter(root_id__in=allowed_root_ids)


def user_can_access_image(user, image) -> bool:
    if getattr(user, "is_superuser", False):
        return True

    if not getattr(image, "root_id", None):
        return False

    return image.root_id in get_allowed_root_ids(user)