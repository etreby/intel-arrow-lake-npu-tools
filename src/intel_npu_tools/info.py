import json
import openvino as ov


def status() -> dict:
    core = ov.Core()
    devices = {device: core.get_property(device, "FULL_DEVICE_NAME") for device in core.available_devices}
    return {"npu_available": "NPU" in devices, "devices": devices}


def main():
    print(json.dumps(status(), indent=2))
