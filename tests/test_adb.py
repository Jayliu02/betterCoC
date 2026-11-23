import unittest
from unittest.mock import patch

from bettercoc.adb import AdbDevice
from bettercoc.errors import DeviceError


class AdbResolveTest(unittest.TestCase):
    def test_tcp_serial_autoconnect(self):
        device = AdbDevice("adb", serial="127.0.0.1:16384")
        with patch.object(
            device,
            "_list_devices",
            side_effect=[[], ["127.0.0.1:16384"]],
        ), patch.object(device, "_run") as run:
            serial = device.resolve()
        self.assertEqual(serial, "127.0.0.1:16384")
        run.assert_called_once_with(["connect", "127.0.0.1:16384"], use_serial=False)

    def test_no_devices(self):
        device = AdbDevice("adb", serial="127.0.0.1:16384")
        with patch.object(device, "_list_devices", return_value=[]), patch.object(
            device, "_run"
        ):
            with self.assertRaises(DeviceError):
                device.resolve()


if __name__ == "__main__":
    unittest.main()
