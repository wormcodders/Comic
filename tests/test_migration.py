from pathlib import Path
from unittest.mock import patch

from models import db
from tests.support import AppTestCase
from tests.test_uploads import PDF_BYTES, png_bytes


class MigrationTests(AppTestCase):
    def prepare_files(self):
        directory = Path(self.app.config['COMIC_UPLOAD_FOLDER'])
        (directory / 'public.pdf').write_bytes(PDF_BYTES)
        (directory / 'private.pdf').write_bytes(PDF_BYTES)
        self.login_as(self.admin)
        return directory

    def test_migration_only_uploads_public_published_comics(self):
        directory = self.prepare_files()
        with patch('catbox_service.CatboxService.test_connection', return_value=(True, 'ok')), patch('catbox_service.CatboxService.upload_file', return_value='https://files.catbox.moe/public.pdf') as upload:
            result = self.client.post('/admin/migrate_to_cloud')
        self.assert_status(result, 200)
        self.assertTrue(result.json['success'])
        self.assertEqual(upload.call_count, 1)
        self.assertEqual(upload.call_args.kwargs['filename'], 'public.pdf')
        self.assertTrue((directory / 'private.pdf').is_file())
        self.assertEqual(self.private.pdf_file, 'private.pdf')

    def test_commit_failure_retains_files_and_database_references(self):
        directory = self.prepare_files()
        with patch('catbox_service.CatboxService.test_connection', return_value=(True, 'ok')), patch('catbox_service.CatboxService.upload_file', return_value='https://files.catbox.moe/public.pdf'), patch.object(db.session, 'commit', side_effect=RuntimeError('commit failed')):
            result = self.client.post('/admin/migrate_to_cloud')
        self.assert_status(result, 200)
        self.assertFalse(result.json['success'])
        self.assertEqual(self.public.pdf_file, 'public.pdf')
        self.assertTrue((directory / 'public.pdf').is_file())

    def test_midway_upload_failure_retains_every_local_asset(self):
        directory = self.prepare_files()
        cover = Path(self.app.config['COVER_UPLOAD_FOLDER']) / 'cover.png'
        cover.write_bytes(png_bytes())
        self.public.cover_image = 'cover.png'
        db.session.commit()
        with patch('catbox_service.CatboxService.test_connection', return_value=(True, 'ok')), patch('catbox_service.CatboxService.upload_file', side_effect=['https://files.catbox.moe/cover.jpg', None]):
            result = self.client.post('/admin/migrate_to_cloud')
        self.assertFalse(result.json['success'])
        self.assertTrue(cover.is_file())
        self.assertTrue((directory / 'public.pdf').is_file())
        self.assertEqual(self.public.cover_image, 'cover.png')

    def test_shared_local_files_are_retained_for_private_comics(self):
        directory = self.prepare_files()
        self.private.pdf_file = 'public.pdf'
        db.session.commit()
        with patch('catbox_service.CatboxService.test_connection', return_value=(True, 'ok')), patch('catbox_service.CatboxService.upload_file', return_value='https://files.catbox.moe/public.pdf'):
            result = self.client.post('/admin/migrate_to_cloud')
        self.assertTrue(result.json['success'])
        self.assertTrue((directory / 'public.pdf').is_file())
        self.assertEqual(self.private.pdf_file, 'public.pdf')
