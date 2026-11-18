from urllib.parse import urlparse
import unittest

from models import db, User, ReadingProgress, Activity, ComicPage, ComicTag
from tests.support import AppTestCase


class FunctionalTests(AppTestCase):
    def test_public_pages_render(self):
        for path in ("/", "/login", "/register", "/forgot-password", "/discover", "/search?q=Public", "/categories", "/category/action", "/trending", f"/comic/{self.public.id}", f"/read/{self.public.id}"):
            with self.subTest(path=path):
                self.assert_status(self.client.get(path), 200)

    def test_admin_pages_render(self):
        self.login_as(self.admin)
        for path in ("/admin", "/admin/analytics", "/admin/comics", "/admin/comics/new", f"/admin/comics/{self.public.id}/edit", f"/admin/comic/{self.public.id}/chapters", "/admin/users", f"/admin/users/{self.owner.id}/edit", "/admin/categories", "/admin/categories/new", "/admin/tags", "/admin/tags/new", "/admin/ads", "/admin/ads/new", "/admin/settings", "/admin/bulk_upload"):
            with self.subTest(path=path):
                self.assert_status(self.client.get(path), 200)

    def test_member_pages_render(self):
        self.login_as(self.owner)
        for path in ("/profile", "/library", "/upload", f"/reading-list/{self.reading_list.id}"):
            with self.subTest(path=path):
                self.assert_status(self.client.get(path), 200)

    def test_random_and_similar_api(self):
        db.session.add(ComicTag(comic_id=self.public.id, tag="hero"))
        db.session.commit()
        self.assert_status(self.client.get("/api/comics/random"), 200)
        self.assert_status(self.client.get(f"/api/comics/{self.public.id}/similar"), 200)

    def test_chapter_navigation(self):
        response = self.client.get(f"/api/comics/{self.public.id}/chapters")
        self.assert_status(response, 200)
        self.assertEqual([chapter["number"] for chapter in response.json["chapters"]], [1, 2])
        response = self.client.get(f"/api/chapters/{self.chapter.id}/next")
        self.assert_status(response, 200)
        self.assertEqual(response.json["chapter"]["id"], self.next_chapter.id)
        response = self.client.get(f"/api/chapters/{self.next_chapter.id}/prev")
        self.assert_status(response, 200)
        self.assertEqual(response.json["chapter"]["id"], self.chapter.id)

    def test_bookmark_workflow(self):
        self.login_as(self.owner)
        response = self.client.post("/api/bookmarks", json={"comic_id": self.public.id, "page_number": 2})
        self.assert_status(response, 200)
        bookmark_id = response.json["bookmark"]["id"]
        response = self.client.get(f"/api/bookmarks/{self.public.id}")
        self.assert_status(response, 200)
        self.assertEqual(response.json["bookmarks"][0]["id"], bookmark_id)
        self.assert_status(self.client.delete(f"/api/bookmarks/{bookmark_id}"), 200)

    def test_empty_delete_with_a_json_header_is_supported(self):
        self.login_as(self.owner)
        result = self.client.post('/api/bookmarks', json={'comic_id': self.public.id, 'page_number': 3})
        self.assert_status(result, 200)
        self.assert_status(self.client.delete('/api/bookmarks/' + str(result.json['bookmark']['id']), headers={'Content-Type': 'application/json'}), 200)

    def test_first_progress_save_computes_percentage(self):
        self.login_as(self.owner)
        response = self.client.post("/api/reading-progress", json={"comic_id": self.public.id, "page_number": 5, "total_pages": 10, "time_spent": 30})
        self.assert_status(response, 200)
        progress = ReadingProgress.query.filter_by(user_id=self.owner.id, comic_id=self.public.id).first()
        self.assertEqual(progress.percentage, 50)
        self.assertEqual(progress.total_time_spent, 30)
        self.assert_status(self.client.get(f"/api/reading-progress/{self.public.id}"), 200)

    def test_progress_without_total_pages_has_safe_default(self):
        self.login_as(self.owner)
        response = self.client.post("/api/reading-progress", json={"comic_id": self.public.id, "page_number": 1})
        self.assert_status(response, 200)

    def test_reading_list_rename_is_persisted(self):
        self.login_as(self.owner)
        response = self.client.put(f"/api/reading-lists/{self.reading_list.id}", json={"title": "Renamed list"})
        self.assert_status(response, 200)
        db.session.expire_all()
        self.assertEqual(response.json["reading_list"]["title"], "Renamed list")
        self.assertEqual(db.session.get(type(self.reading_list), self.reading_list.id).title, "Renamed list")

    def test_list_creation_activity_references_the_list(self):
        self.login_as(self.owner)
        response = self.client.post("/api/reading-lists", json={"title": "New list"})
        self.assert_status(response, 201)
        activity = Activity.query.filter_by(user_id=self.owner.id, activity_type="list_create").first()
        self.assertEqual(activity.reading_list_id, response.json["reading_list"]["id"])

    def test_activity_api(self):
        db.session.add(Activity(user_id=self.owner.id, comic_id=self.public.id, activity_type="comment"))
        db.session.commit()
        self.login_as(self.owner)
        self.assert_status(self.client.get("/api/activity/user"), 200)
        self.assert_status(self.client.get("/api/activity/global"), 200)

    def test_like_count_tracks_toggle(self):
        self.login_as(self.other)
        response = self.client.post(f"/api/comments/{self.comment.id}/like")
        self.assert_status(response, 200)
        self.assertEqual(response.json["likes_count"], 1)
        response = self.client.post(f"/api/comments/{self.comment.id}/like")
        self.assertEqual(response.json["likes_count"], 0)

    def test_comment_replies_are_available(self):
        self.login_as(self.owner)
        response = self.client.post(f"/api/comics/{self.public.id}/comments", json={"content": "A reply", "parent_id": self.comment.id})
        self.assert_status(response, 201)
        response = self.client.get(f"/api/comments/{self.comment.id}/replies")
        self.assert_status(response, 200)
        self.assertEqual(response.json["replies"][0]["content"], "A reply")


class SecurityTests(AppTestCase):
    def test_legacy_html_uploads_are_not_served_as_active_content(self):
        from pathlib import Path
        self.public.cover_image = 'legacy.html'
        db.session.commit()
        path = Path(self.app.config['COVER_UPLOAD_FOLDER']) / 'legacy.html'
        path.write_text('<script>alert(1)</script>', encoding='utf-8')
        self.assert_status(self.client.get('/static/uploads/covers/legacy.html'), 404)
        self.login_as(self.admin)
        self.assert_status(self.client.get('/static/uploads/covers/legacy.html'), 404)

    def test_private_tags_do_not_leak_into_public_suggestions(self):
        from models import Tag
        db.session.add_all([Tag(name='confidential-tag'), ComicTag(comic_id=self.private.id, tag='confidential-tag')])
        db.session.commit()
        self.assertFalse('confidential-tag' in self.client.get('/search').get_data(as_text=True))
        response = self.client.get('/api/tags/autocomplete?q=confidential')
        self.assert_status(response, 200)
        self.assertEqual(response.json['tags'], [])

    def test_no_known_admin_is_created_at_startup(self):
        self.assertIsNone(User.query.filter_by(username="admin").first())

    def test_login_rejects_external_next_urls(self):
        for next_url in ("//evil.example", "/\\evil.example", "///evil.example", "https://evil.example"):
            with self.subTest(next_url=next_url):
                self.client = self.app.test_client()
                response = self.client.post("/login", query_string={"next": next_url}, data={"email": self.owner.email, "password": "ReaderPass123"})
                self.assert_status(response, 302)
                self.assertEqual(response.location, "/")

    def test_missing_password_is_a_validation_error(self):
        response = self.client.post("/login", data={"email": self.owner.email})
        self.assert_status(response, 200)

    def test_private_comics_are_not_publicly_accessible(self):
        for comic in (self.private, self.draft, self.unpublished):
            for path in (f"/comic/{comic.id}", f"/read/{comic.id}", f"/api/comic/{comic.id}/pages", f"/api/comics/{comic.id}/similar", f"/api/comics/{comic.id}/chapters", f"/api/comics/{comic.id}/comments"):
                with self.subTest(path=path):
                    self.assert_status(self.client.get(path), 404)

    def test_private_page_assets_require_access(self):
        path = self.app.static_folder + f"/uploads/pages/{self.private.id}/page_001.jpg"
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"private image")
        response = self.client.get(f"/static/uploads/pages/{self.private.id}/page_001.jpg")
        self.assert_status(response, 404)
        self.login_as(self.owner)
        self.assert_status(self.client.get(f"/static/uploads/pages/{self.private.id}/page_001.jpg"), 200)

    def test_public_catalog_hides_unpublished_comics(self):
        response = self.client.get("/")
        self.assert_status(response, 200)
        self.assertNotIn(self.unpublished.title, response.get_data(as_text=True))

    def test_regular_user_cannot_modify_other_private_comics(self):
        self.login_as(self.other)
        for path, payload in (("/api/toggle_library", {"comic_id": self.private.id}), ("/api/rate_comic", {"comic_id": self.private.id, "score": 4}), ("/api/reading_progress", {"comic_id": self.private.id, "current_page": 1, "total_pages": 2}), ("/api/bookmarks", {"comic_id": self.private.id, "page_number": 1}), (f"/api/comics/{self.private.id}/comments", {"content": "Unauthorized comment"})):
            with self.subTest(path=path):
                self.assert_status(self.client.post(path, json=payload), 404)

    def test_bad_json_shapes_are_rejected(self):
        self.login_as(self.owner)
        paths = ("/api/toggle_library", "/api/rate_comic", "/api/reading_progress", "/api/reading-progress", "/api/bookmarks", "/api/reading-lists", f"/api/reading-lists/{self.reading_list.id}/items", f"/api/comics/{self.public.id}/comments")
        for path in paths:
            for payload in ([1], "bad data", 42):
                with self.subTest(path=path, payload=payload):
                    self.assert_status(self.client.post(path, json=payload), 400)

    def test_invalid_numeric_values_are_rejected(self):
        self.login_as(self.owner)
        for score in ("bad", {}, [], True, 1.5):
            with self.subTest(score=score):
                self.assert_status(self.client.post("/api/rate_comic", json={"comic_id": self.public.id, "score": score}), 400)
        for page in ("bad", -1, {}, True, 1.5):
            with self.subTest(page=page):
                self.assert_status(self.client.post("/api/reading_progress", json={"comic_id": self.public.id, "current_page": page, "total_pages": 10}), 400)

    def test_nonexistent_comic_cannot_be_added_to_library(self):
        self.login_as(self.owner)
        self.assert_status(self.client.post("/api/toggle_library", json={"comic_id": 999999}), 404)

    def test_cross_comic_chapter_and_reply_are_rejected(self):
        self.login_as(self.owner)
        self.assert_status(self.client.post("/api/reading-progress", json={"comic_id": self.public.id, "chapter_id": self.private_chapter.id, "page_number": 1, "total_pages": 10}), 400)
        self.assert_status(self.client.post(f"/api/comics/{self.public.id}/comments", json={"content": "Wrong parent", "parent_id": self.private_comment.id}), 400)

    def test_hidden_comments_are_not_returned(self):
        response = self.client.get(f"/api/comics/{self.public.id}/comments")
        self.assert_status(response, 200)
        self.assertNotIn(self.hidden_comment.id, [comment["id"] for comment in response.json["comments"]])

    def test_global_activity_does_not_expose_private_data(self):
        db.session.add_all([Activity(user_id=self.owner.id, comic_id=self.private.id, activity_type="comment"), Activity(user_id=self.owner.id, activity_type="read", is_public=False)])
        db.session.commit()
        response = self.client.get("/api/activity/global")
        self.assert_status(response, 200)
        self.assertEqual(response.json["activities"], [])

    def test_api_errors_use_json(self):
        response = self.client.get("/api/nonexistent")
        self.assert_status(response, 404)
        self.assertTrue(response.is_json)

    def test_api_responses_are_not_cacheable(self):
        self.login_as(self.owner)
        response = self.client.get("/api/reading-lists")
        self.assert_status(response, 200)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    def test_private_reading_list_is_denied_without_crashing(self):
        self.login_as(self.other)
        self.assert_status(self.client.get(f"/reading-list/{self.private_list.id}"), 404)


if __name__ == "__main__":
    unittest.main()
