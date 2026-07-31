import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import tifffile
    from psdtags import (
        PsdChannel,
        PsdChannelId,
        PsdCompressionType,
        PsdFormat,
        PsdKey,
        PsdLayer,
        PsdLayerFlag,
        PsdLayerMask,
        PsdLayers,
        PsdRectangle,
        PsdUserMask,
        TiffImageSourceData,
    )
except ImportError:
    tifffile = None


@unittest.skipIf(tifffile is None, "layered TIFF dependencies are not installed")
class LayeredTiffRoundTripTests(unittest.TestCase):
    def test_photoshop_layer_tag_survives_roundtrip(self):
        red = np.zeros((12, 10, 4), dtype=np.uint8)
        red[:, :, 0] = 220
        red[:, :, 3] = 255
        layer = PsdLayer(
            name="Red Motif",
            rectangle=PsdRectangle(0, 0, 12, 10),
            channels=[
                PsdChannel(
                    PsdChannelId.TRANSPARENCY_MASK,
                    PsdCompressionType.ZIP,
                    red[:, :, 3],
                ),
                PsdChannel(
                    PsdChannelId.CHANNEL0,
                    PsdCompressionType.ZIP,
                    red[:, :, 0],
                ),
                PsdChannel(
                    PsdChannelId.CHANNEL1,
                    PsdCompressionType.ZIP,
                    red[:, :, 1],
                ),
                PsdChannel(
                    PsdChannelId.CHANNEL2,
                    PsdCompressionType.ZIP,
                    red[:, :, 2],
                ),
            ],
            mask=PsdLayerMask(),
            flags=PsdLayerFlag.PHOTOSHOP5,
        )
        source_data = TiffImageSourceData(
            name="roundtrip.tif",
            psdformat=PsdFormat.LE32BIT,
            layers=PsdLayers(PsdKey.LAYER, [layer], True),
            usermask=PsdUserMask(),
        )
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "roundtrip.tif"
            tifffile.imwrite(
                destination,
                red[:, :, :3],
                photometric="rgb",
                metadata=None,
                extratags=[source_data.tifftag()],
            )
            reopened = TiffImageSourceData.fromtiff(destination)

        self.assertEqual(len(reopened.layers), 1)
        self.assertEqual(reopened.layers[0].name, "Red Motif")
        self.assertEqual(reopened.layers[0].asarray().shape, (12, 10, 4))


if __name__ == "__main__":
    unittest.main()
