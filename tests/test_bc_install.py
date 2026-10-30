"""Only packs built with the fallback may bypass the legacy native-BC requirement."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from porter import install
from porter.upstream import BuildError


class BCInstall(unittest.TestCase):
    def install_pack(self, fallback):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            apk = data / 'game.apk'; apk.write_bytes(b'apk')
            man = {'name': 'test', 'package': 'org.test.game', 'requires': ['bcn'], 'bytes': 0}
            if fallback:
                man['bc_texture_fallback'] = 'cpu'
            device = MagicMock()
            device.bc_textures.return_value = False
            device.free_bytes.return_value = 10**9
            device.remote_sizes.return_value = {}
            device.prepare_app_files.return_value = False
            with patch.object(install.datapack, 'read_manifest', return_value=man), \
                    patch.object(install, 'Adb', return_value=device), \
                    patch.object(install, 'PROG'), patch.object(install, 'say'):
                install.install(apk, data, 'adb')
            return device

    def test_new_pack_installs_without_native_bc(self):
        device = self.install_pack(True)
        device.install.assert_called_once()
        device.push_tree.assert_called_once()

    def test_old_pack_still_checks_native_bc(self):
        with self.assertRaisesRegex(BuildError, 'needs BC-compressed textures'):
            self.install_pack(False)
