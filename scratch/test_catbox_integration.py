"""
Automated Verification Test for Catbox.moe Cloud Storage Integration
"""

import io
import fitz
from catbox_service import CatboxService
from main import create_app
from models import db, Comic, ComicPage, Setting
from unified_uploader import UnifiedUploader

def run_tests():
    print("=== Step 1: Testing Catbox Service ===")
    catbox = CatboxService()
    ok, msg = catbox.test_connection()
    print(f"Catbox connection: {ok} -> {msg}")
    assert ok, f"Catbox test connection failed: {msg}"
    
    print("\n=== Step 2: Testing In-Memory PDF Generation & Extraction ===")
    # Generate a small 2-page sample PDF in memory
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((50, 50), "Comic Cover Page 1", fontsize=20)
    page2 = doc.new_page()
    page2.insert_text((50, 50), "Comic Story Page 2", fontsize=20)
    pdf_bytes = doc.tobytes()
    doc.close()
    assert len(pdf_bytes) > 0, "Failed to generate in-memory PDF"
    print(f"Generated {len(pdf_bytes)} bytes test PDF in memory.")

    print("\n=== Step 3: Testing Direct In-Memory Uploader with Cloud Mode ===")
    uploader = UnifiedUploader(
        cloud_storage_enabled=True,
        catbox_userhash=""
    )
    
    upload_res = uploader.upload_comic(
        file_stream=io.BytesIO(pdf_bytes),
        filename="test_cloud_comic.pdf",
        extract_metadata=False,
        upload_to_upfiles=False
    )
    print("Upload result success:", upload_res['success'])
    print("Cover URL:", upload_res['cover_url'])
    print("Cloud PDF URL:", upload_res['local_path'])
    assert upload_res['success'], f"Upload failed: {upload_res['errors']}"
    assert str(upload_res['cover_url']).startswith('https://files.catbox.moe/'), "Cover was not uploaded to Catbox"
    assert str(upload_res['local_path']).startswith('https://files.catbox.moe/'), "PDF was not uploaded to Catbox"

    print("\n=== Step 4: Testing Direct In-Memory Page Extraction to Catbox ===")
    page_urls = uploader.extract_pages(
        pdf_input=pdf_bytes,
        comic_id="test_comic_999",
        upload_to_catbox=True
    )
    print(f"Extracted {len(page_urls)} pages to Catbox:")
    for i, u in enumerate(page_urls):
        print(f"  Page {i+1}: {u}")
        assert u.startswith('https://files.catbox.moe/'), f"Page {i+1} URL not Catbox"
    assert len(page_urls) == 2, f"Expected 2 pages, got {len(page_urls)}"

    print("\n=== Step 5: Testing Database Integration and Reader API ===")
    app = create_app()
    with app.app_context():
        # Set cloud storage setting
        Setting.set('cloud_storage_enabled', '1')
        assert Setting.get('cloud_storage_enabled') == '1'

        # Create a test comic with cloud URLs
        test_comic = Comic(
            title="Test Cloud Comic",
            author="Test Author",
            pdf_file=upload_res['local_path'],
            cover_image=upload_res['cover_url'],
            category="Action",
            visibility="public"
        )
        db.session.add(test_comic)
        db.session.commit()

        # Add ComicPage records
        for idx, purl in enumerate(page_urls):
            db.session.add(ComicPage(
                comic_id=test_comic.id,
                page_number=idx + 1,
                image_url=purl
            ))
        db.session.commit()

        # Verify cover_url property
        print(f"Comic cover_url property: {test_comic.cover_url}")
        assert test_comic.cover_url == upload_res['cover_url']

        # Verify pages query
        db_pages = test_comic.pages.all()
        assert len(db_pages) == 2
        print(f"Database retrieved {len(db_pages)} pages for comic {test_comic.id}.")

        # Test Reader API route
        client = app.test_client()
        res = client.get(f'/api/comic/{test_comic.id}/pages')
        data = res.get_json()
        assert res.status_code == 200, f"Reader API status {res.status_code}"
        assert data['success'] is True, "Reader API returned error"
        assert len(data['pages']) == 2, f"Expected 2 pages, got {len(data['pages'])}"
        print("Reader API response successfully returned Catbox pages:")
        print(" ", data['pages'])

        # Clean up test comic
        db.session.delete(test_comic)
        db.session.commit()

    print("\n ALL TESTS PASSED SUCCESSFULLY! ")

if __name__ == '__main__':
    run_tests()
