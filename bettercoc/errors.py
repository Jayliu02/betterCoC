class BetterCoCError(Exception):
    pass


class ConfigError(BetterCoCError):
    pass


class CaptureError(BetterCoCError):
    pass


class DeviceError(BetterCoCError):
    pass


class MissingAssetError(BetterCoCError):
    pass


class RecognitionTimeout(BetterCoCError):
    pass


class OcrUnavailable(BetterCoCError):
    pass


class TaskError(BetterCoCError):
    pass


class StopRequested(BetterCoCError):
    pass
