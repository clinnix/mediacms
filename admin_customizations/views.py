from django.shortcuts import render


def local_import_view(request):
    return render(request, 'admin/local_import.html', {'title': '本地上传'})
