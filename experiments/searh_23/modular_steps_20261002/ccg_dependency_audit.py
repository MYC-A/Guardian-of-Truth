"""Read-only native prover dependency/disk plan. Installs nothing."""
import json
import re
import shutil
import subprocess
from pathlib import Path


def main():
    plan = subprocess.check_output(['apt-get', '-s', '--no-install-recommends', 'install', 'coq'], text=True)
    selected = re.findall(r'^Inst (\S+) \((\S+)', plan, flags=re.MULTILINE)
    packages = []
    for name, version in selected:
        metadata = subprocess.check_output(['apt-cache', 'show', name + '=' + version], text=True)
        def field(key):
            match = re.search(r'^' + key + r': (\d+)$', metadata, flags=re.MULTILINE)
            if not match:
                raise ValueError('dependency_metadata_missing/' + name + '/' + key)
            return int(match[1])
        packages.append({'name': name, 'version': version, 'installed_bytes': field('Installed-Size') * 1024,
                         'download_bytes': field('Size')})
    free = shutil.disk_usage('/workspace').free
    installed = sum(p['installed_bytes'] for p in packages)
    download = sum(p['download_bytes'] for p in packages)
    result = {'scope': 'Actual apt solver dry-run and exact package metadata; no install/delete',
        'free_bytes': free, 'planned_installed_bytes': installed, 'planned_download_bytes': download,
        'fits_installed_only': installed <= free, 'fits_install_plus_download': installed + download <= free,
        'native_prover_found': shutil.which('coqtop'), 'packages': packages,
        'quality_scope': 'Dependency blockage only; does not measure semantic faithfulness or theorem quality.'}
    path = Path('/workspace/guardian/results/modular_steps_20261002/model_setup/ccg_prover_dependency_plan.json')
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('free_bytes', 'planned_installed_bytes', 'planned_download_bytes', 'fits_installed_only', 'fits_install_plus_download')}))


if __name__ == '__main__':
    main()
