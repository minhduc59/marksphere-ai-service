"""Non-regression contract: existing photo pipeline state fields must be untouched.

These tests verify that the VideoClipperState TypedDict and the publish pipeline
state extensions are structurally correct and backwards-compatible.
"""

from app.agents.video_clipper.state import VideoClipperState
from app.agents.publish_post.state import PublishPostState


class TestPublishPostStateContract:
    """Ensure the extended PublishPostState contains all expected keys."""

    def test_photo_keys_present_in_typeddict(self):
        keys = PublishPostState.__annotations__
        # Original photo keys must still be present
        assert "content_post_id" in keys
        assert "user_id" in keys
        assert "publish_mode" in keys
        assert "image_public_url" in keys
        assert "golden_hour_result" in keys
        assert "provider_post_id" in keys
        assert "publish_status" in keys
        assert "error" in keys

    def test_video_extension_keys_present(self):
        keys = PublishPostState.__annotations__
        assert "content_type" in keys
        assert "video_url" in keys

    def test_photo_state_instance_accepts_video_fields(self):
        # TypedDict does not enforce at runtime, but we verify it works
        state: PublishPostState = {
            "content_post_id": "post-uuid",
            "user_id": "user-uuid",
            "publish_mode": "auto",
            "scheduled_time_override": "",
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "published_post_id": "",
            "image_public_url": "https://cdn.cloudinary.com/photo.jpg",
            "assembled_caption": "",
            "golden_hour_result": {},
            "scheduled_at": "",
            "provider_post_id": "",
            "content_type": "photo",
            "video_url": "",
            "publish_status": "",
            "error": "",
        }
        assert state["content_type"] == "photo"
        assert state["video_url"] == ""

    def test_video_state_instance(self):
        state: PublishPostState = {
            "content_post_id": "post-uuid",
            "user_id": "user-uuid",
            "publish_mode": "auto",
            "scheduled_time_override": "",
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "published_post_id": "",
            "image_public_url": "",
            "assembled_caption": "",
            "golden_hour_result": {},
            "scheduled_at": "",
            "provider_post_id": "",
            "content_type": "video",
            "video_url": "https://cdn.cloudinary.com/v.mp4",
            "publish_status": "",
            "error": "",
        }
        assert state["content_type"] == "video"
        assert state["video_url"] == "https://cdn.cloudinary.com/v.mp4"


class TestVideoClipperState:
    """Verify VideoClipperState contains all required fields."""

    def test_all_required_keys_present(self):
        keys = VideoClipperState.__annotations__
        for key in [
            "task_id", "user_id", "source_type", "source_ref",
            "font_id", "caption_template_id", "max_clips",
            "task_temp_dir", "local_video_path", "transcript_data",
            "selected_segments", "clip_local_paths",
            "clip_cloudinary_objects", "clip_ids", "errors",
        ]:
            assert key in keys, f"Missing key: {key}"

    def test_state_instance_can_be_created(self):
        state: VideoClipperState = {
            "task_id": "task-uuid",
            "user_id": "user-uuid",
            "source_type": "url",
            "source_ref": "https://youtube.com/watch?v=abc",
            "font_id": "",
            "caption_template_id": "",
            "max_clips": 5,
            "task_temp_dir": "/tmp/test",
            "local_video_path": "",
            "transcript_data": {},
            "selected_segments": [],
            "clip_local_paths": [],
            "clip_cloudinary_objects": [],
            "clip_ids": [],
            "errors": [],
        }
        assert state["task_id"] == "task-uuid"
        assert state["max_clips"] == 5
        assert isinstance(state["errors"], list)
