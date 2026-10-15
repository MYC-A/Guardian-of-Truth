"""The selected experiment mode reaches a verified ZIP without changing repository defaults."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.build_judge_submission import build, ENCODER_PIN, ENCODER_REQUIRED, REQUIRED
from scripts.build_platform_startup_probe import file_info


class BuildMode(unittest.TestCase):
    def test_dense_zip_and_legacy_default_are_distinct_verified_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.zip'
            records = {}
            with zipfile.ZipFile(source, 'w') as z:
                for name in REQUIRED:
                    data = b'fixture runtime'
                    z.writestr(file_info(name, 0o755), data)
                    records[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), mode=0o755)
                z.writestr(file_info('MANIFEST.json'), json.dumps(dict(files=records)).encode())
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            model, encoder = root / 'model', root / 'encoder'
            for directory, files in ((model, ('config.json', 'model.safetensors')), (encoder, ENCODER_REQUIRED)):
                directory.mkdir()
                for name in files:
                    (directory / name).write_bytes(b'{}')
            for mode in (None, 'u2_dense'):
                output = root / ('default.zip' if mode is None else 'dense.zip')
                with contextlib.redirect_stdout(io.StringIO()):
                    receipt = build(source, digest, model, 'fixture', 'fixture', output,
                                    encoder_dir=encoder, encoder_id=ENCODER_PIN[0], encoder_revision=ENCODER_PIN[1],
                                    context_mode=mode)
                self.assertTrue(receipt['all_members_verified'])
                self.assertTrue(receipt['under_cap'])
                with zipfile.ZipFile(output) as z:
                    config = json.loads(z.read('JUDGE_CONFIG.json'))
                    manifest = json.loads(z.read('MANIFEST.json'))
                    self.assertEqual(config.get('context_mode', 'legacy'), mode or 'legacy')
                    self.assertEqual(manifest['judge_build']['context_mode'], mode or 'legacy')
                    self.assertIn('model/encoder/tokenizer.json', z.namelist())
                    self.assertEqual(config['questions'], ['overall'])
                    self.assertEqual(config['positive_rate'], .30)

    def test_dense_without_encoder_is_rejected_before_any_file_is_read(self):
        with self.assertRaisesRegex(ValueError, 'DENSE_BUILD_REQUIRES_ENCODER'):
            build('missing', 'x', 'missing', 'm', 'r', 'missing.zip', context_mode='u2_dense')

    def test_unknown_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'INVALID_BUILD_CONTEXT_MODE'):
            build('missing', 'x', 'missing', 'm', 'r', 'missing.zip', context_mode='dense_typo')


if __name__ == '__main__':
    unittest.main()
