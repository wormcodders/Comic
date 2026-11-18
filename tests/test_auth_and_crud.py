import hashlib
import re
from pathlib import Path

from models import db, User, ComicTag, UserLibrary, ReadingListItem, Rating, Bookmark, ReadingProgress, CommentLike, Activity, Follow
from tests.support import AppTestCase


class AuthAndCrudTests(AppTestCase):
    def test_api_timestamps_include_the_utc_offset(self):
        from datetime import datetime, timedelta
        self.login_as(self.owner)
        result = self.client.post(f'/api/comics/{self.public.id}/comments', json={'content': 'Time check'})
        self.assert_status(result, 201)
        timestamp = datetime.fromisoformat(result.json['comment']['created_at'])
        self.assertIsNotNone(timestamp.tzinfo)
        self.assertEqual(timestamp.utcoffset(), timedelta(0))

    def test_tag_suggestions_do_not_interpolate_tags_into_javascript(self):
        db.session.add(ComicTag(comic_id=self.public.id, tag="');alert(1);//"))
        db.session.commit()
        html = self.client.get('/search').get_data(as_text=True)
        handlers = re.findall(r'onclick="([^"]+)"', html)
        self.assertFalse(any('alert(1)' in handler for handler in handlers))
        self.assertIn('onclick="addTag(this.dataset.tag)"', html)

    def test_csrf_is_required_and_valid_ajax_tokens_work(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.login_as(self.owner)
        self.assert_status(self.client.post('/api/toggle_library', json={'comic_id': self.public.id}), 400)
        html = self.client.get('/profile').get_data(as_text=True)
        token = re.search(r'<meta name="csrf-token" content="([^"]+)"', html).group(1)
        self.assert_status(self.client.post('/api/toggle_library', json={'comic_id': self.public.id}, headers={'X-CSRFToken': token}), 200)
        self.assert_status(self.client.get('/logout'), 405)
        self.assert_status(self.client.post('/logout'), 400)
        self.assert_status(self.client.post('/logout', data={'csrf_token': token}), 302)
        self.assert_status(self.client.get('/api/reading-lists'), 401)

    def test_password_reset_invalidates_existing_sessions_and_reset_links(self):
        self.assert_status(self.client.post('/login', data={'email': self.owner.email, 'password': 'ReaderPass123', 'remember': 'on'}), 302)
        recovery = self.app.test_client()
        result = recovery.post('/forgot-password', data={'email': self.owner.email, 'security_answer': 'My favorite show'})
        self.assert_status(result, 302)
        link = result.location
        self.assert_status(recovery.post(link, data={'password': 'ChangedPass123', 'confirm_password': 'ChangedPass123'}), 302)
        self.assert_status(self.client.get('/api/reading-lists'), 401)
        self.assertEqual(recovery.get(link).location, '/forgot-password')

    def test_legacy_admin_credentials_and_security_answers_cannot_log_in_or_reset(self):
        self.admin.set_password('admin123')
        self.admin.set_security_answer('Batman')
        db.session.commit()
        self.assert_status(self.client.post('/login', data={'email': self.admin.email, 'password': 'admin123'}), 200)
        self.assert_status(self.client.get('/admin/settings'), 302)
        self.assert_status(self.client.post('/forgot-password', data={'email': self.admin.email, 'security_answer': 'Batman'}), 200)

    def test_malformed_session_identifiers_are_not_server_errors(self):
        for identifier in ('bad', '1:bad', '999999999999999999999999:bad'):
            with self.subTest(identifier=identifier):
                with self.client.session_transaction() as session:
                    session['_user_id'] = identifier
                self.assert_status(self.client.get('/api/reading-lists'), 401)

    def test_local_admin_command_creates_and_recovers_accounts(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=['create-admin', '--username', 'newadmin', '--email', 'newadmin@example.com'], input='NewAdminPass123\nNewAdminPass123\n')
        self.assertEqual(result.exit_code, 0, result.output)
        user = User.query.filter_by(username='newadmin').one()
        self.assertTrue(user.is_admin)
        self.assertIsNone(user.security_answer_hash)
        result = runner.invoke(args=['create-admin', '--username', 'newadmin', '--email', 'newadmin@example.com', '--reset-password'], input='RecoveredPass123\nRecoveredPass123\n')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(user.check_password('RecoveredPass123'))

    def test_regular_users_cannot_access_any_admin_endpoint(self):
        self.login_as(self.owner)
        for path in ('/admin/settings', '/admin/users', '/admin/comics', '/admin/analytics'):
            with self.subTest(path=path):
                self.assert_status(self.client.get(path), 403)
        self.assert_status(self.client.post('/admin/unified_upload'), 403)
        self.assertEqual(User.query.count(), 3)

    def test_public_lists_and_libraries_do_not_leak_private_comics(self):
        db.session.add_all([ReadingListItem(reading_list_id=self.reading_list.id, comic_id=self.private.id), ReadingListItem(reading_list_id=self.reading_list.id, comic_id=self.public.id), UserLibrary(user_id=self.other.id, comic_id=self.private.id)])
        db.session.commit()
        result = self.client.get(f'/api/reading-lists/{self.reading_list.id}')
        self.assert_status(result, 200)
        self.assertEqual(result.json['reading_list']['items_count'], 1)
        self.assertNotIn(self.private.title, result.get_data(as_text=True))
        self.login_as(self.other)
        self.assertFalse(self.private.title in self.client.get('/library').get_data(as_text=True), 'Private comics appeared in another user’s library')

    def test_reading_list_boolean_privacy_values_are_validated(self):
        self.login_as(self.owner)
        self.assert_status(self.client.post('/api/reading-lists', json={'title': 'Private?', 'is_public': 'false'}), 400)

    def test_publishing_a_draft_sets_publication_flag_and_clears_tags(self):
        db.session.add(ComicTag(comic_id=self.draft.id, tag='old'))
        db.session.commit()
        self.login_as(self.admin)
        self.assert_status(self.client.post(f'/admin/comics/{self.draft.id}/edit', data={'title': self.draft.title, 'visibility': 'public', 'tags': ''}), 302)
        db.session.refresh(self.draft)
        self.assertTrue(self.draft.is_published)
        self.assertEqual(self.draft.tags.count(), 0)

    def test_admin_account_edits_validate_duplicates_and_last_admin(self):
        self.login_as(self.admin)
        self.assert_status(self.client.post(f'/admin/users/{self.other.id}/edit', data={'username': self.owner.username, 'email': self.other.email}), 400)
        self.assert_status(self.client.post(f'/admin/users/{self.admin.id}/edit', data={'username': self.admin.username, 'email': self.admin.email}), 400)

    def test_deleting_a_user_cleans_dependent_rows(self):
        owner_id = self.owner.id
        db.session.add_all([UserLibrary(user_id=owner_id, comic_id=self.public.id), Rating(user_id=owner_id, comic_id=self.public.id, score=5), Bookmark(user_id=owner_id, comic_id=self.public.id, page_number=1), ReadingProgress(user_id=owner_id, comic_id=self.public.id, total_pages=10), CommentLike(user_id=owner_id, comment_id=self.comment.id), Activity(user_id=owner_id, comic_id=self.public.id, activity_type='read'), Follow(follower_id=owner_id, following_id=self.other.id)])
        db.session.commit()
        self.login_as(self.admin)
        self.assert_status(self.client.post(f'/admin/users/{owner_id}/delete'), 302)
        self.assertIsNone(db.session.get(User, owner_id))
        self.assertEqual(Rating.query.filter_by(user_id=owner_id).count(), 0)
        self.assertEqual(Bookmark.query.filter_by(user_id=owner_id).count(), 0)
        self.assertEqual(UserLibrary.query.filter_by(user_id=owner_id).count(), 0)

    def test_json_structured_data_safely_preserves_untrusted_text(self):
        self.public.title = 'Comic "quote" </script><script>alert(1)</script>'
        db.session.commit()
        result = self.client.get(f'/comic/{self.public.id}')
        self.assert_status(result, 200)
        html = result.get_data(as_text=True)
        import json
        content = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
        book = [json.loads(block) for block in blocks if 'Book' in block][0]
        self.assertEqual(book['name'], self.public.title)
        self.assertNotIn('</script><script>alert(1)</script>', html)
