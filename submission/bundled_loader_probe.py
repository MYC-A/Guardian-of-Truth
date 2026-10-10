"""Read-only compact bundled-loader diagnosis, no weights or predictions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import probe_supervisor as supervisor


DRIVER_CODE = r'''
import sys,json,os
print('BUNDLED_PYTHON_STARTED:'+sys.version.split()[0],flush=True)
print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,
 LD_LIBRARY_PATH=os.environ.get('LD_LIBRARY_PATH'),
 CUDA_VISIBLE_DEVICES=os.environ.get('CUDA_VISIBLE_DEVICES'))),flush=True)
import ctypes,ctypes.util
for name in ('cuda','nvidia-ml'):
 print(json.dumps(dict(library=name,find=ctypes.util.find_library(name))),flush=True)
 try:
  library=ctypes.CDLL('lib'+name+'.so.1')
  print(name+':DLOPEN_OK',flush=True)
  if name=='cuda':
   library.cuInit.argtypes=[ctypes.c_uint];library.cuInit.restype=ctypes.c_int
   status=library.cuInit(0);print('CU_INIT_STATUS:'+str(status),flush=True)
   if status==0:
    count=ctypes.c_int()
    library.cuDeviceGetCount.argtypes=[ctypes.POINTER(ctypes.c_int)]
    status=library.cuDeviceGetCount(ctypes.byref(count))
    print(json.dumps(dict(device_count_status=status,device_count=count.value)),flush=True)
    if status==0 and count.value:
     device=ctypes.c_int();status=library.cuDeviceGet(ctypes.byref(device),0)
     print('DEVICE_GET_STATUS:'+str(status),flush=True)
     if status==0:
      namebuf=ctypes.create_string_buffer(256);major=ctypes.c_int();minor=ctypes.c_int()
      name_status=library.cuDeviceGetName(namebuf,256,device)
      cc_status=library.cuDeviceComputeCapability(ctypes.byref(major),ctypes.byref(minor),device)
      memory=ctypes.c_size_t()
      library.cuDeviceTotalMem_v2.argtypes=[ctypes.POINTER(ctypes.c_size_t),ctypes.c_int]
      memory_status=library.cuDeviceTotalMem_v2(ctypes.byref(memory),device)
      print(json.dumps(dict(name_status=name_status,name=namebuf.value.decode(errors='replace'),
       capability_status=cc_status,capability=[major.value,minor.value],
       memory_status=memory_status,total_memory_bytes=memory.value)),flush=True)
 except Exception as error:
  print(name+':LOAD_OR_DRIVER_ERROR:'+type(error).__name__+':'+str(error),flush=True)
try:
 with open('/proc/self/maps',encoding='utf-8') as stream:
  libraries=sorted({line.split()[-1] for line in stream if '/' in line and any(
   word in line for word in ('libcuda','libnvidia','libc.so','libpython','ld-linux'))})
 print(json.dumps(dict(loaded_native_paths=libraries[:64])),flush=True)
except Exception as error:print('MAPS_ERROR:'+type(error).__name__,flush=True)
'''


def driver_directories(environment):
    """Contrast-only driver search paths, not every host library directory."""
    candidates = environment.get('LD_LIBRARY_PATH', '').split(os.pathsep)
    candidates += ['/usr/local/nvidia/lib', '/usr/local/nvidia/lib64']
    result = []
    for value in candidates:
        path = Path(value)
        if (not value or not path.is_absolute() or any(char in value for char in '\n\r')
                or not path.is_dir()):
            continue
        if not any((path / name).is_file() for name in ('libcuda.so.1','libnvidia-ml.so.1')):
            continue
        if value not in result:
            result.append(value)
    return result


def main(arguments=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True)
    parser.add_argument('--output',required=True)
    parser.parse_args(arguments)  # Never open input or create predictions.
    root=Path(__file__).resolve().parents[1]
    supervisor.emit('purpose','BUNDLED_LOADER_ONLY_NO_WEIGHTS_NO_INPUT_READ_NO_PREDICTIONS')
    manifest=json.loads((root/'MANIFEST.json').read_text(encoding='utf-8'))
    supervisor.emit('scope',dict(runtime_source_sha=manifest['runtime_source_sha'],
        full_runtime_sha256=manifest['full_runtime_sha256'],
        original_launcher_sha256=manifest['original_launcher_sha256'],
        omitted=['runtime/site-packages','model weights','B2 inference','Torch/vLLM kernels']))
    paths=driver_directories(os.environ)
    supervisor.emit('driver_contrast_directories',paths)
    wrappers=[('original_bundled_loader',root/'runtime/python/run_python.sh',{}),
              ('driver_path_contrast',root/'runtime/python/run_python_driver_probe.sh',
               {'GUARDIAN_PROBE_DRIVER_DIRS':os.pathsep.join(paths)})]
    for name,wrapper,environment in wrappers:
        expected=manifest['files'][wrapper.relative_to(root).as_posix()]['sha256']
        if hashlib.sha256(wrapper.read_bytes()).hexdigest()!=expected:
            raise ValueError('PROBE_LAUNCHER_CHANGED')
        supervisor.run_probe(name,DRIVER_CODE,timeout=30,python=wrapper,
                             environment_overrides=environment)
    supervisor.emit('done','BUNDLED_LOADER_DIAGNOSTIC_COMPLETE_EXPECTED_EXIT_2')
    return 2


if __name__=='__main__':
    raise SystemExit(main())
