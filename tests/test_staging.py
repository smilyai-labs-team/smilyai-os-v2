import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
class StagingTests(unittest.TestCase):
    def test_staged_runtime_and_services(self):
        spec=importlib.util.spec_from_file_location("stage",ROOT/"scripts/stage-runtime.py")
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            mod.stage(d);p=Path(d)
            self.assertTrue((p/"opt/smilyai-os/shell/assets/smilyai-logo.png").is_file())
            self.assertFalse((p/"opt/smilyai-os/tests").exists())
            self.assertFalse((p/"opt/smilyai-os/.git").exists())
            self.assertFalse((p/"opt/smilyai-os/config.json").exists())
            self.assertTrue((p/"usr/local/bin/smilyai-session").stat().st_mode & 0o111)
            for name in ("smilyai-shell", "smilyai-session-environment", "smilyai-recover"):
                self.assertTrue((p/"usr/local/bin"/name).stat().st_mode & 0o111)
            self.assertTrue((p/"opt/smilyai-os/smilyai/shell_launcher.py").is_file())
            self.assertTrue((p/"opt/smilyai-os/smilyai/service_notify.py").is_file())
            for file in (p/"etc/xdg/smilyai/labwc").glob("*.xml"):ET.parse(file)
            unit=(p/"etc/systemd/user/smilyai-harness.service").read_text()
            self.assertIn("ReadWritePaths=%h %t",unit);self.assertNotIn("network-online.target",unit)
            lightdm=(p/"etc/lightdm/lightdm.conf.d/50-smilyai.conf").read_text()
            self.assertNotIn("autologin-user=",lightdm)
            manifest=json.loads((p/"opt/smilyai-os/runtime-manifest.json").read_text())
            self.assertIn("shell/boot.js",manifest)
    def test_chromium_sandbox_not_disabled(self):
        script=(ROOT/"packaging/rootfs/usr/local/bin/smilyai-shell").read_text()
        launcher=(ROOT/"smilyai/shell_launcher.py").read_text()
        self.assertNotIn("--no-sandbox",script);self.assertIn("47810",launcher)
        self.assertNotIn("--ozone-platform=auto",launcher)
        self.assertIn("shell_launcher.py",script)
    def test_manual_builds_no_password_artifact(self):
        workflow=(ROOT/".github/workflows/build-images.yml").read_text()
        self.assertNotIn("push:",workflow)
        self.assertNotIn("credentials.txt",workflow)
        self.assertIn("pi_gen_ref",workflow)
