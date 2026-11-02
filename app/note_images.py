"""Validated local note attachments; content-addressed IDs make backups portable."""
import base64
import hashlib
import io
import re
import warnings

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_BACKUP_BYTES = 100 * 1024 * 1024
IMAGE_REF = re.compile(r'/api/note-images/([a-f0-9]{64})')
SCHEMA = '''CREATE TABLE IF NOT EXISTS note_images(
    id TEXT PRIMARY KEY, media_type TEXT NOT NULL, data BLOB NOT NULL);'''


def inspect_image(data):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, '每张图片不能为空且不能超过 10 MB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                media_type = {'PNG': 'image/png', 'JPEG': 'image/jpeg',
                              'GIF': 'image/gif', 'WEBP': 'image/webp'}.get(image.format)
                if not media_type:
                    raise HTTPException(400, '请选择 PNG、JPEG、GIF 或 WebP 图片')
                image.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(400, '图片损坏或尺寸过大，请换一张图片')
    return hashlib.sha256(data).hexdigest(), media_type


def referenced_ids(states):
    return {image_id for state in states for image_id in IMAGE_REF.findall(state['note'])}


def export_images(connection, states):
    result = []
    for image_id in sorted(referenced_ids(states)):
        row = connection.execute('SELECT data FROM note_images WHERE id=?', (image_id,)).fetchone()
        if not row:
            raise HTTPException(409, '笔记引用的本地图片缺失，请修复图片后再导出备份')
        result.append({'id': image_id, 'data': base64.b64encode(row[0]).decode('ascii')})
    return result


def validate_images(records, states, version):
    if records and version < 4:
        raise HTTPException(400, '图片备份需要版本 4')
    images = {}
    for record in records:
        try:
            data = base64.b64decode(record.data, validate=True)
        except ValueError:
            raise HTTPException(400, '备份图片编码无效')
        image_id, media_type = inspect_image(data)
        if image_id != record.id or image_id in images:
            raise HTTPException(400, '备份图片标识不匹配或重复')
        images[image_id] = (media_type, data)
    if version >= 4 and not referenced_ids(states).issubset(images):
        raise HTTPException(400, '备份缺少笔记引用的图片')
    return images
