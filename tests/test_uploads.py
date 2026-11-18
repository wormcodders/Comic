import io
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import pymupdf

from catbox_service import CatboxService, cloud_file_name
from models import db, Comic, Setting
from tests.support import AppTestCase
from tests.test_security_utils import response
from unified_uploader import UnifiedUploader


def pdf_bytes(pages=2, width=72, height=72):
    with pymupdf.open() as document:
        for _ in range(pages):
            document.new_page(width=width, height=height)
        return document.tobytes()


PDF_BYTES = pdf_bytes()


def png_bytes():
    stream = io.BytesIO()
    Image.new('RGB', (5, 5), 'red').save(stream, format='PNG')
    return stream.getvalue()


class UploadTests(AppTestCase):
    def test_user_upload_form_submits_to_the_member_endpoint(self):
        self.login_as(self.owner)
        html = self.client.get('/upload').get_data(as_text=True)
        self.assertIn('enctype="multipart/form-data"', html)
        self.assertIn('name="file"', html)
        self.assertNotIn('/admin/unified_upload', html)

    def make_uploader(self, **kwargs):
        return UnifiedUploader(upload_folder=self.app.config['COMIC_UPLOAD_FOLDER'], covers_folder=self.app.config['COVER_UPLOAD_FOLDER'], **kwargs)

    def test_real_pdf_upload_and_page_extraction(self):
        uploader = self.make_uploader()
        result = uploader.upload_comic(PDF_BYTES, 'comic.pdf', extract_metadata=False, upload_to_upfiles=False)
        self.assertTrue(result['success'], result['errors'])
        self.assertTrue(Path(result['local_path']).is_file())
        urls = uploader.extract_pages(result['local_path'], str(self.public.id))
        self.assertEqual(len(urls), 2)
        self.assertTrue((Path(self.app.static_folder) / 'uploads' / 'pages' / str(self.public.id) / '.complete').is_file())

    def test_fake_pdf_and_oversized_bytes_are_not_saved(self):
        uploader = self.make_uploader()
        result = uploader.upload_comic(b'<html><script>alert(1)</script></html>', 'fake.pdf', upload_to_upfiles=False)
        self.assertFalse(result['success'])
        self.assertTrue(result['validation_error'])
        uploader.max_file_size = 10
        result = uploader.upload_comic(PDF_BYTES, 'large.pdf', upload_to_upfiles=False)
        self.assertFalse(result['success'])
        self.assertEqual(list(Path(uploader.upload_folder).iterdir()), [])

    def test_non_seekable_input_is_bounded_and_supported(self):
        class Input:
            def read(self, limit=-1):
                return PDF_BYTES[:limit] if limit >= 0 else PDF_BYTES
        result = self.make_uploader().upload_comic(Input(), 'comic.pdf', extract_metadata=False, upload_to_upfiles=False)
        self.assertTrue(result['success'], result['errors'])

    def test_page_directory_traversal_is_rejected(self):
        uploader = self.make_uploader()
        self.assertEqual(uploader.extract_pages(PDF_BYTES, '../../outside'), [])
        self.assertFalse((Path(self.temp_dir.name) / 'outside').exists())

    def test_pdf_page_count_and_dimensions_are_bounded(self):
        uploader = self.make_uploader()
        self.assertFalse(uploader._validate_file('many.pdf', pdf_bytes(pages=501)))
        urls = uploader.extract_pages(pdf_bytes(pages=1, width=100000, height=100000), str(self.public.id))
        self.assertEqual(len(urls), 1)
        path = Path(self.app.static_folder) / 'uploads' / 'pages' / str(self.public.id) / 'page_001.jpg'
        with Image.open(path) as image:
            self.assertLessEqual(image.width * image.height, 4_010_000)

    def test_invalid_user_upload_content_is_rejected(self):
        self.login_as(self.owner)
        for name in ('fake.png', 'fake.pdf'):
            with self.subTest(name=name):
                self.assert_status(self.client.post('/upload', data={'file': (io.BytesIO(b'<html>bad</html>'), name)}), 400)
        self.assertFalse((Path(self.app.config['UPLOAD_FOLDER']) / 'user_submissions').exists())

    def test_user_submission_is_not_publicly_accessible(self):
        self.login_as(self.owner)
        self.assert_status(self.client.post('/upload', data={'file': (io.BytesIO(PDF_BYTES), 'comic.pdf')}), 302)
        path = next((Path(self.app.config['UPLOAD_FOLDER']) / 'user_submissions').iterdir())
        self.client = self.app.test_client()
        self.assert_status(self.client.get('/static/uploads/user_submissions/' + path.name), 404)

    def test_admin_cover_rejects_html_and_pdf(self):
        self.login_as(self.admin)
        for name, content in (('evil.html', b'<script>alert(1)</script>'), ('cover.pdf', PDF_BYTES)):
            with self.subTest(name=name):
                self.assert_status(self.client.post('/admin/comics/new', data={'title': 'A comic', 'cover': (io.BytesIO(content), name)}), 400)
        self.assertEqual(Comic.query.count(), 4)

    def test_valid_cover_is_reencoded_and_saved(self):
        self.login_as(self.admin)
        self.assert_status(self.client.post('/admin/comics/new', data={'title': 'With cover', 'cover': (io.BytesIO(png_bytes()), 'cover.png')}), 302)
        comic = Comic.query.filter_by(title='With cover').one()
        with Image.open(Path(self.app.config['COVER_UPLOAD_FOLDER']) / comic.cover_image) as image:
            self.assertEqual(image.format, 'JPEG')

    def test_unified_upload_works_without_an_optional_host_token(self):
        self.login_as(self.admin)
        result = self.client.post('/admin/unified_upload', data={'file': (io.BytesIO(PDF_BYTES), 'comic.pdf')})
        self.assert_status(result, 200)
        self.assertTrue(result.json['success'])

    def test_invalid_admin_pdf_returns_a_client_error(self):
        self.login_as(self.admin)
        for endpoint in ('/admin/unified_upload', '/admin/bulk_upload_file'):
            with self.subTest(endpoint=endpoint):
                self.assert_status(self.client.post(endpoint, data={'file': (io.BytesIO(b'not a pdf'), 'bad.pdf')}), 400)

    def test_bulk_drafts_are_not_uploaded_to_public_hosts(self):
        Setting.set('cloud_storage_enabled', '1')
        Setting.set('upfiles_token', 'private-token')
        self.login_as(self.admin)
        with patch.object(CatboxService, 'upload_file') as cloud, patch.object(UnifiedUploader, '_upload_to_upfiles') as host:
            result = self.client.post('/admin/bulk_upload_file', data={'file': (io.BytesIO(PDF_BYTES), 'draft.pdf')})
        self.assert_status(result, 200)
        comic = db.session.get(Comic, result.json['comic_id'])
        self.assertEqual(comic.visibility, 'draft')
        self.assertFalse(comic.is_published)
        self.assertFalse(comic.pdf_file.startswith('http'))
        cloud.assert_not_called()
        host.assert_not_called()

    def test_private_reader_does_not_publish_extracted_pages(self):
        (Path(self.app.config['COMIC_UPLOAD_FOLDER']) / 'private.pdf').write_bytes(PDF_BYTES)
        Setting.set('cloud_storage_enabled', '1')
        self.login_as(self.owner)
        with patch.object(CatboxService, 'upload_file') as cloud:
            result = self.client.get(f'/api/comic/{self.private.id}/pages')
        self.assert_status(result, 200)
        self.assertEqual(result.json['total'], 2)
        cloud.assert_not_called()

    def test_failed_cloud_page_upload_does_not_return_a_partial_sequence(self):
        with patch.object(CatboxService, 'upload_file', side_effect=['https://files.catbox.moe/a.jpg', None]):
            self.assertEqual(self.make_uploader().extract_pages(PDF_BYTES, str(self.public.id), upload_to_catbox=True), [])

    def test_model_output_shapes_and_lengths_are_validated(self):
        uploader = self.make_uploader()
        self.assertIsNone(uploader._parse_llm_response('[1, 2, 3]'))
        metadata = uploader._parse_llm_response('```json\n{"title":"<b>A comic</b>","tags":["hero",null,3],"episode":true}\n```')
        self.assertEqual(metadata['title'], 'A comic')
        self.assertEqual(metadata['tags'], ['hero'])
        self.assertIsNone(metadata['episode'])

    def test_catbox_album_skips_empty_and_foreign_references(self):
        self.assertEqual(cloud_file_name('https://files.catbox.moe/abc123.jpg?download=1'), 'abc123.jpg')
        self.assertIsNone(cloud_file_name(None))
        self.assertIsNone(cloud_file_name('https://other.example/abc.jpg'))
        with patch('catbox_service.safe_request', return_value=response(body=b'https://catbox.moe/c/album')) as request:
            album = CatboxService('account-hash').create_album('A comic', [None, 'https://files.catbox.moe/abc123.jpg'])
        self.assertEqual(album, 'https://catbox.moe/c/album')
        self.assertEqual(request.call_args.kwargs['data']['files'], 'abc123.jpg')
