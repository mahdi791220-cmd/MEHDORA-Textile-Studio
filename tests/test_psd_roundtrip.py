import tempfile
import unittest
from pathlib import Path

from PIL import Image
try:
    from psd_tools import PSDImage
except ImportError:
    PSDImage = None


@unittest.skipIf(PSDImage is None, "psd-tools is not installed")
class LayeredPsdRoundTripTests(unittest.TestCase):
    def test_pixel_layers_survive_save_and_reopen(self):
        psd = PSDImage.new(mode="RGB", size=(32, 24), depth=8)
        psd.create_pixel_layer(
            Image.new("RGBA", (32, 24), (220, 40, 40, 255)),
            name="Background",
        )
        accent = psd.create_pixel_layer(
            Image.new("RGBA", (12, 10), (30, 90, 230, 180)),
            name="Colorway Accent",
            left=7,
            top=5,
        )
        accent.visible = False

        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "roundtrip.psd"
            psd.save(destination)
            reopened = PSDImage.open(destination)

        self.assertEqual(
            [layer.name for layer in reopened],
            ["Background", "Colorway Accent"],
        )
        self.assertFalse(reopened[1].visible)
        self.assertEqual(reopened.size, (32, 24))


if __name__ == "__main__":
    unittest.main()
