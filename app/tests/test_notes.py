"""Note images and portable backups, using the suite's isolated database."""
import base64
import copy
import io
import unittest
from PIL import Image
from fastapi.testclient import TestClient
from test_app import server


class NoteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        with server.db() as connection:
            for table in ['study_activity', 'daily_items', 'daily_batches', 'memberships', 'states',
                          'folders', 'settings', 'note_images']:
                connection.execute('DELETE FROM ' + table)
        self.pid = next(iter(server.PAPERS))
        self.path = f'/api/questions/{self.pid}/1'
        buffer = io.BytesIO()
        Image.new('RGB', (48, 32), '#a291ce').save(buffer, format='PNG')
        self.image = buffer.getvalue()

    def upload(self):
        response = self.client.post(self.path + '/images', content=self.image,
                                    headers={'content-type': 'image/png'})
        self.assertEqual(response.status_code, 200)
        return response.json()['url']

    def test_image_and_markdown_survive_fresh_database_restore(self):
        url = self.upload()
        self.assertEqual(self.upload(), url)  # Deduplicate by content.
        note = f'## 错因\n\n**漏看条件**\n\n![草稿]({url})\n\n- [ ] 再做一次'
        self.assertEqual(self.client.patch(self.path, json={'note': note, 'revision': 0}).status_code, 200)
        backup = self.client.get('/api/backup').json()
        self.assertEqual(backup['version'], 9)
        self.assertEqual(len(backup['images']), 1)
        self.assertEqual(base64.b64decode(backup['images'][0]['data']), self.image)
        self.assertEqual(self.client.post('/api/backup/preview', json=backup).json()['images'], 1)
        with server.db() as connection:
            connection.execute('DELETE FROM states')
            connection.execute('DELETE FROM note_images')
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post('/api/backup/restore', json=backup).status_code, 200)
        self.assertEqual(self.client.get(self.path).json()['note'], note)
        image = self.client.get(url)
        self.assertEqual(image.content, self.image)
        self.assertEqual(image.headers['content-type'], 'image/png')
        self.assertEqual(image.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(self.client.patch(self.path, json={'note': '旧草稿', 'revision': 0}).status_code, 409)

    def test_bad_files_and_cross_site_uploads_are_rejected(self):
        for content in [b'<svg onload="alert(1)"></svg>', b'not an image', self.image[:24]]:
            response = self.client.post(self.path + '/images', content=content,
                                        headers={'content-type': 'image/png'})
            self.assertEqual(response.status_code, 400)
        for content in [b'', b'x' * (server.note_images.MAX_IMAGE_BYTES + 1)]:
            self.assertEqual(self.client.post(self.path + '/images', content=content).status_code, 413)
        self.assertEqual(self.client.post(self.path + '/images', content=self.image,
                          headers={'origin': 'https://example.com'}).status_code, 403)
        self.assertEqual(self.client.post('/api/questions/missing/1/images', content=self.image).status_code, 404)

    def test_invalid_backup_does_not_overwrite_notes_or_images(self):
        url = self.upload()
        self.client.patch(self.path, json={'note': f'![图片]({url})', 'revision': 0})
        backup = self.client.get('/api/backup').json()
        for mutation in ['missing', 'hash', 'encoding', 'duplicate', 'legacy']:
            bad = copy.deepcopy(backup)
            if mutation == 'missing': bad['images'] = []
            if mutation == 'hash': bad['images'][0]['id'] = '0' * 64
            if mutation == 'encoding': bad['images'][0]['data'] = 'bad!'
            if mutation == 'duplicate': bad['images'] *= 2
            if mutation == 'legacy': bad['version'] = 3
            self.assertEqual(self.client.post('/api/backup/restore', json=bad).status_code, 400, mutation)
            self.assertEqual(self.client.get(self.path).json()['note'], backup['states'][0]['note'])
            self.assertEqual(self.client.get(url).content, self.image)

    def test_unused_uploads_are_not_exported_and_old_backups_still_restore(self):
        self.upload()
        backup = self.client.get('/api/backup').json()
        self.assertEqual(backup['images'], [])
        backup['version'] = 3
        backup.pop('knowledge')
        del backup['images']
        self.assertEqual(self.client.post('/api/backup/restore', json=backup).status_code, 200)


if __name__ == '__main__':
    unittest.main()
