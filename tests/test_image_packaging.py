from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ImagePackagingTests(unittest.TestCase):
    def test_x86_profile_is_hybrid_and_installable(self):
        config = (ROOT / "packaging/image/debian/auto/config").read_text()
        self.assertIn("--binary-image iso-hybrid", config)
        self.assertIn("--debian-installer live", config)
        packages = (ROOT / "packaging/image/debian/config/package-lists/smilyai.list.chroot").read_text().splitlines()
        for package in ("labwc", "chromium", "network-manager", "python3", "polkitd"):
            self.assertIn(package, packages)

    def test_pi_profile_exports_flashable_image_with_hardware_tools(self):
        profile = ROOT / "packaging/image/raspberrypi"
        self.assertTrue((profile / "stage-smily/EXPORT_IMAGE").is_file())
        config = (profile / "config").read_text()
        self.assertIn("DEPLOY_COMPRESSION='xz'", config)
        self.assertIn("stage-smily", config)
        packages = (profile / "stage-smily/00-install/00-packages").read_text().splitlines()
        self.assertIn("gpiod", packages)
        self.assertIn("rpicam-apps", packages)

    def test_image_services_keep_agent_unprivileged(self):
        services = [
            ROOT / "packaging/rootfs/etc/systemd/user/smilyai-harness.service",
        ]
        for path in services:
            unit = path.read_text()
            self.assertIn("NoNewPrivileges=true", unit)
            self.assertIn("ProtectSystem=strict", unit)
            self.assertNotIn("User=root", unit)


if __name__ == "__main__":
    unittest.main()
