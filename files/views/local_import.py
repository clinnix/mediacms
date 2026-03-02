import os

from django.conf import settings
from django.core.files import File
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Media
from ..permissions import IsMediacmsEditor

IMPORT_DIR = os.path.join(settings.BASE_DIR, "media_import")

SUPPORTED_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v", ".flv",
    ".wmv", ".mpeg", ".mpg", ".3gp", ".ts",
    ".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a",
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".pdf",
}


class LocalImportFileList(APIView):
    """List files available in the import directory"""

    permission_classes = (IsMediacmsEditor,)

    def get(self, request):
        if not os.path.isdir(IMPORT_DIR):
            return Response({"files": []})

        files = []
        for name in sorted(os.listdir(IMPORT_DIR)):
            if name.startswith("."):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            full_path = os.path.join(IMPORT_DIR, name)
            if not os.path.isfile(full_path):
                continue
            files.append({"name": name, "size": os.path.getsize(full_path)})

        return Response({"files": files})


class LocalImportFile(APIView):
    """Import a single file from the import directory into MediaCMS"""

    permission_classes = (IsMediacmsEditor,)

    def post(self, request):
        filename = request.data.get("filename", "")
        # Prevent path traversal
        filename = os.path.basename(filename)
        if not filename:
            return Response({"success": False, "error": "filename is required"}, status=400)

        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return Response({"success": False, "error": "Unsupported file type"}, status=400)

        filepath = os.path.join(IMPORT_DIR, filename)
        if not os.path.isfile(filepath):
            return Response({"success": False, "error": "File not found"}, status=404)

        title = os.path.splitext(filename)[0]

        try:
            with open(filepath, "rb") as f:
                media = Media.objects.create(
                    user=request.user,
                    title=title,
                    media_file=File(f, name=filename),
                )
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=500)

        # Remove file from import directory after successful import
        try:
            os.remove(filepath)
        except OSError:
            pass

        return Response({
            "success": True,
            "friendly_token": media.friendly_token,
            "media_url": f"/view?m={media.friendly_token}",
        })
