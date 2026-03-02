import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cms.settings')
django.setup()

from files.models import Media
n = Media.objects.filter(media_type='video', encoding_status='pending').update(encoding_status='success', listable=True)
print(f'已修复 {n} 个视频')
