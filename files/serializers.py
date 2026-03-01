from django.conf import settings
from rest_framework import serializers

from .methods import is_mediacms_editor
from .models import Category, Comment, EncodeProfile, Media, Playlist, Tag

# TODO: put them in a more DRY way


class MediaSerializer(serializers.ModelSerializer):
    # to be used in APIs as show related media
    user = serializers.ReadOnlyField(source="user.username")
    url = serializers.SerializerMethodField()
    api_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    author_profile = serializers.SerializerMethodField()
    author_thumbnail = serializers.SerializerMethodField()

    def get_url(self, obj):
        return self.context["request"].build_absolute_uri(obj.get_absolute_url())

    def get_api_url(self, obj):
        return self.context["request"].build_absolute_uri(obj.get_absolute_url(api=True))

    def get_thumbnail_url(self, obj):
        if obj.thumbnail_url:
            return self.context["request"].build_absolute_uri(obj.thumbnail_url)
        else:
            return None

    def get_author_profile(self, obj):
        return self.context["request"].build_absolute_uri(obj.author_profile())

    def get_author_thumbnail(self, obj):
        return self.context["request"].build_absolute_uri(obj.author_thumbnail())

    class Meta:
        model = Media
        read_only_fields = (
            "friendly_token",
            "user",
            "add_date",
            "media_type",
            "state",
            "duration",
            "encoding_status",
            "views",
            "likes",
            "dislikes",
            "reported_times",
            "size",
            "is_reviewed",
            "featured",
        )
        fields = (
            "friendly_token",
            "url",
            "api_url",
            "user",
            "title",
            "description",
            "add_date",
            "views",
            "media_type",
            "state",
            "duration",
            "thumbnail_url",
            "is_reviewed",
            "preview_url",
            "author_name",
            "author_profile",
            "author_thumbnail",
            "encoding_status",
            "views",
            "likes",
            "dislikes",
            "reported_times",
            "featured",
            "user_featured",
            "size",
            # "category",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')

        if False and request and 'category' in self.fields:
            # this is not working
            user = request.user
            if is_mediacms_editor(user):
                pass
            else:
                if getattr(settings, 'USE_RBAC', False):
                    # Filter category queryset based on user permissions
                    non_rbac_categories = Category.objects.filter(is_rbac_category=False)
                    rbac_categories = user.get_rbac_categories_as_contributor()
                    self.fields['category'].queryset = non_rbac_categories.union(rbac_categories)


class SingleMediaSerializer(serializers.ModelSerializer):
    user = serializers.ReadOnlyField(source="user.username")
    url = serializers.SerializerMethodField()
    is_shared = serializers.SerializerMethodField()
    video_token = serializers.SerializerMethodField()

    def get_url(self, obj):
        return self.context["request"].build_absolute_uri(obj.get_absolute_url())

    def get_is_shared(self, obj):
        """Check if media has custom permissions or RBAC categories"""
        custom_permissions = obj.permissions.exists()
        rbac_categories = obj.category.filter(is_rbac_category=True).exists()
        return custom_permissions or rbac_categories

    def get_video_token(self, obj):
        if not getattr(settings, 'USE_B2_STORAGE', False):
            return None
        from .helpers import make_video_jwt
        request = self.context.get('request')
        user = request.user if request else None
        return make_video_jwt(user, obj.friendly_token, settings.SECRET_KEY)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not getattr(settings, 'USE_B2_STORAGE', False):
            return data
        token = data.get('video_token')
        cf_base = getattr(settings, 'CF_WORKER_BASE_URL', '').rstrip('/')
        if not token or not cf_base:
            return data

        # Inject ?token= into all CF Worker URLs in hls_info
        hls_info = data.get('hls_info') or {}
        for key, url in hls_info.items():
            if isinstance(url, str) and url.startswith(cf_base):
                hls_info[key] = f"{url}?token={token}"

        # Inject ?token= into all CF Worker URLs in encodings_info
        encodings_info = data.get('encodings_info') or {}
        for _res, codecs in encodings_info.items():
            if not isinstance(codecs, dict):
                continue
            for _codec, enc in codecs.items():
                if isinstance(enc, dict) and isinstance(enc.get('url'), str):
                    if enc['url'].startswith(cf_base):
                        enc['url'] = f"{enc['url']}?token={token}"

        # Inject ?token= into original_media_url
        original_url = data.get('original_media_url')
        if isinstance(original_url, str) and original_url.startswith(cf_base):
            data['original_media_url'] = f"{original_url}?token={token}"

        return data

    class Meta:
        model = Media
        read_only_fields = (
            "friendly_token",
            "user",
            "add_date",
            "views",
            "media_type",
            "state",
            "duration",
            "encoding_status",
            "views",
            "likes",
            "dislikes",
            "reported_times",
            "size",
            "video_height",
            "is_reviewed",
        )
        fields = (
            "url",
            "user",
            "title",
            "description",
            "add_date",
            "edit_date",
            "media_type",
            "state",
            "is_shared",
            "duration",
            "thumbnail_url",
            "poster_url",
            "thumbnail_time",
            "url",
            "sprites_url",
            "preview_url",
            "author_name",
            "author_profile",
            "author_thumbnail",
            "encodings_info",
            "encoding_status",
            "views",
            "likes",
            "dislikes",
            "reported_times",
            "user_featured",
            "original_media_url",
            "size",
            "video_height",
            "enable_comments",
            "categories_info",
            "is_reviewed",
            "edit_url",
            "tags_info",
            "hls_info",
            "license",
            "subtitles_info",
            "chapter_data",
            "ratings_info",
            "add_subtitle_url",
            "allow_download",
            "slideshow_items",
            "video_token",
            "b2_status",
        )


class MediaSearchSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    api_url = serializers.SerializerMethodField()

    def get_url(self, obj):
        return self.context["request"].build_absolute_uri(obj.get_absolute_url())

    def get_api_url(self, obj):
        return self.context["request"].build_absolute_uri(obj.get_absolute_url(api=True))

    class Meta:
        model = Media
        fields = (
            "title",
            "author_name",
            "author_profile",
            "thumbnail_url",
            "add_date",
            "views",
            "description",
            "friendly_token",
            "duration",
            "url",
            "api_url",
            "media_type",
            "preview_url",
            "categories_info",
        )


class EncodeProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = EncodeProfile
        fields = ("name", "extension", "resolution", "codec", "description")


class CategorySerializer(serializers.ModelSerializer):
    user = serializers.ReadOnlyField(source="user.username")

    class Meta:
        model = Category
        fields = (
            "title",
            "uid",
            "description",
            "is_global",
            "media_count",
            "user",
            "thumbnail_url",
        )


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ("title", "media_count", "thumbnail_url")


class PlaylistSerializer(serializers.ModelSerializer):
    user = serializers.ReadOnlyField(source="user.username")

    class Meta:
        model = Playlist
        read_only_fields = ("add_date", "user")
        fields = ("id", "add_date", "title", "description", "user", "media_count", "url", "api_url", "thumbnail_url", "friendly_token")


class PlaylistDetailSerializer(serializers.ModelSerializer):
    user = serializers.ReadOnlyField(source="user.username")

    class Meta:
        model = Playlist
        read_only_fields = ("add_date", "user")
        fields = ("title", "add_date", "user_thumbnail_url", "description", "user", "media_count", "url", "thumbnail_url")


class CommentSerializer(serializers.ModelSerializer):
    author_profile = serializers.ReadOnlyField(source="user.get_absolute_url")
    author_name = serializers.ReadOnlyField(source="user.name")
    author_thumbnail_url = serializers.ReadOnlyField(source="user.thumbnail_url")

    class Meta:
        model = Comment
        read_only_fields = ("add_date", "uid")
        fields = (
            "add_date",
            "text",
            "parent",
            "author_thumbnail_url",
            "author_profile",
            "author_name",
            "media_url",
            "uid",
        )
