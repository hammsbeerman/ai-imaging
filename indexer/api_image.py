from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from indexer.models import Image
from indexer.services.image_service import build_image_detail
from indexer.services.permission_service import filter_images_for_user


def api_image_detail(request, image_id):
    qs = filter_images_for_user(Image.objects.all(), request.user)
    img = get_object_or_404(qs, id=image_id)
    return JsonResponse(build_image_detail(request.user, img))