from .models import RequestLog

ALLOWED_PATHS = {
    "/",
    "/list2/",
    "/management/",
}

class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        path = request.path

        if path in ALLOWED_PATHS:
            RequestLog.objects.create(
                ip_address=self.get_client_ip(request),
                path=path,
                method=request.method,
            )

        return response

    def get_client_ip(self, request):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0]
        return request.META.get("REMOTE_ADDR")
