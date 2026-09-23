"""Executed through Guardian Gateway to verify the new ModelScope runtime."""

import socket
import torch

print("HOSTNAME:", socket.gethostname())
print("CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
print("GUARDIAN_GATEWAY_TEST_OK")
