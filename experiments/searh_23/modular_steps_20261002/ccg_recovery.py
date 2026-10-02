"""Recover DATA-only EasyCCG model archive from one public OCI image layer.

No Docker engine, image execution, foreign Java binaries or root extraction.
Community mirror provenance is explicit, not authenticated author model gold.
"""
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request
from modular_common import RESULTS, write

REPO = 'turx/ccg2lambda'
MANIFEST = 'sha256:cf3943d062bd4a8e0a69a6f19156d02d9607f714e4848887b9e538a8a8b09dba'


def run():
    out = RESULTS / 'model_setup'
    record = {'original_author_model_download': 'BLOCKED original Drive folder',
              'mirror': 'public OCI data layer, never run image', 'repository': REPO, 'manifest': MANIFEST}
    try:
        with urllib.request.urlopen('https://auth.docker.io/token?service=registry.docker.io&scope=repository:turx/ccg2lambda:pull', timeout=30) as r:
            token = json.load(r)['token']
        def fetch(endpoint):
            request = urllib.request.Request('https://registry-1.docker.io/v2/' + REPO + '/' + endpoint,
                headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'})
            return urllib.request.urlopen(request, timeout=90)
        with fetch('manifests/' + MANIFEST) as r:
            manifest = json.load(r)
        with fetch('blobs/' + manifest['config']['digest']) as r:
            config = json.load(r)
        index = 0
        selected = None
        for entry in config['history']:
            if entry.get('empty_layer'):
                continue
            layer = manifest['layers'][index]
            index += 1
            command = entry.get('created_by', '')
            if 'COPY' in command and '/app/parsers/easyccg/model.tar.gz' in command:
                selected = layer
                record['layer_command'] = command
                break
        if selected is None or selected['size'] > 160_000_000:
            raise ValueError('model_data_layer_not_found_or_size_cap')
        record['layer'] = selected
        out.mkdir(parents=True, exist_ok=True)
        blob = out / 'easyccg_data_layer.tar.gz'
        with fetch('blobs/' + selected['digest']) as response, blob.open('wb') as dest:
            while True:
                block = response.read(1 << 20)
                if not block:
                    break
                dest.write(block)
                if dest.tell() > 160_000_000:
                    raise ValueError('download_size_cap')
        actual = 'sha256:' + hashlib.sha256(blob.read_bytes()).hexdigest()
        if actual != selected['digest']:
            raise ValueError('registry_layer_hash_mismatch')
        target = Path('/workspace/guardian/third_party_modular_20261002/easyccg/model.tar.gz')
        with tarfile.open(blob, 'r:*') as archive:
            members = [m for m in archive.getmembers() if m.name.endswith('app/parsers/easyccg/model.tar.gz') and m.isfile()]
            if len(members) != 1:
                raise ValueError('exact_model_archive_not_found')
            with archive.extractfile(members[0]) as stream, target.open('wb') as dest:
                dest.write(stream.read())
        record.update(status='RECOVERED_COMMUNITY_MIRROR_NOT_AUTHOR_AUTHENTICATED', archive=str(target),
                      archive_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        # Unpack only regular files INSIDE own easyccg/model; never links/devices.
        model_root = target.parent / 'recovered_model'
        model_root.mkdir(exist_ok=True)
        with tarfile.open(target, 'r:*') as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                relative = Path(member.name)
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('unsafe_model_member')
                dest = model_root / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, dest.open('wb') as sink:
                    sink.write(source.read())
        record['unpacked_model_root'] = str(model_root)
    except Exception as exc:
        record.update(status='BLOCKED', reason=type(exc).__name__)
    write(out / 'ccg_recovery.json', record)
    print(json.dumps({k: v for k, v in record.items() if k in ('status', 'reason', 'archive', 'unpacked_model_root')}))


if __name__ == '__main__':
    run()
