from django.http import HttpResponseForbidden
import re
from django.shortcuts import render

class BlockEverythingExceptMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.allowed_exact_paths = {
            "", "list2/", "update/page/", "delete-media-folder/",
            "delete-calldata/", "update/page/secret/page",
            "management/", "updates/", "login/", "logout/","log-calendar-open/",
        }
        self.allowed_prefix_patterns = [
            r"^update/process/[^/]+/?$",
            r"^update/status/[^/]+/?$",
            r"^latest-schedule/[^/]+/?$",
            r"^record-audio/[^/]+/[^/]+$",
            r"^secure-photo/[^/]+/?$",
            r"^admin/.*$",
            r"^api/.*$",
        ]

    def __call__(self, request):
        path = request.path.lstrip("/")

        if path.startswith("media/backgrounds/") or path.startswith("media/documents/"):
            return self.get_response(request)

        if path in self.allowed_exact_paths:
            return self.get_response(request)

        for pattern in self.allowed_prefix_patterns:
            if re.match(pattern, path):
                return self.get_response(request)

        return render(request, '404.html', status=404)
