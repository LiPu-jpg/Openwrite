"""Build an audited Intel macOS wheel without requiring compilers on authors' Macs."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

URL = 'https://files.pythonhosted.org/packages/bb/ad/5d6702db60b1e40b41ef513b6967ff5848f307d50f8449baf1634f5908f1/cryptography-50.0.1.tar.gz'
SHA = '5dd9bda1c12b4162f6ff568eeb5e0ff956c28d14406e875cfe8a63a2d414ff20'
assert sys.platform == 'darwin' and platform.machine() == 'x86_64'
root = Path('.tmp-intel-wheel').resolve()
out = root / 'output'
out.mkdir(parents=True, exist_ok=True)
archive = root / 'source.tar.gz'
urllib.request.urlretrieve(URL, archive)
assert hashlib.sha256(archive.read_bytes()).hexdigest() == SHA
with tarfile.open(archive) as source:
    source.extractall(root, filter='data')
openssl = subprocess.check_output(['brew', '--prefix', 'openssl@3'], text=True).strip()
env = {**os.environ, 'OPENSSL_DIR': openssl, 'OPENSSL_STATIC': '1', 'MACOSX_DEPLOYMENT_TARGET': '13.0'}
subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--wheel-dir', str(out), str(root / 'cryptography-50.0.1')], env=env, check=True)
wheel, = out.glob('*.whl')
subprocess.run([sys.executable, '-m', 'pip', 'install', str(wheel)], check=True)
subprocess.run([sys.executable, '-c', 'from cryptography.hazmat.backends.openssl.backend import backend; from cryptography.hazmat.primitives.asymmetric import rsa; k=rsa.generate_private_key(public_exponent=65537,key_size=2048); print(backend.openssl_version_text())'], check=True)
with zipfile.ZipFile(wheel) as packed:
    shared, = [name for name in packed.namelist() if name.endswith('_rust.abi3.so')]
    packed.extract(shared, root / 'inspect')
linked = subprocess.check_output(['otool', '-L', str(root / 'inspect' / shared)], text=True)
assert 'libssl' not in linked and 'libcrypto' not in linked, linked
licenses = out / 'licenses'
licenses.mkdir()
for item in (Path(openssl) / 'share/doc/openssl@3').glob('*'):
    if item.is_file() and ('LICENSE' in item.name or 'NOTICE' in item.name):
        (licenses / item.name).write_bytes(item.read_bytes())
# Homebrew also retains the source license at its keg root.
for name in ['LICENSE.txt', 'LICENSE', 'NOTICE']:
    item = Path(openssl) / name
    if item.is_file(): (licenses / name).write_bytes(item.read_bytes())
assert list(licenses.iterdir()), 'OpenSSL license must accompany the static library'
(out / 'provenance.json').write_text(json.dumps({
    'package': 'cryptography', 'version': '50.0.1', 'source_url': URL, 'source_sha256': SHA,
    'wheel': wheel.name, 'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
    'platform': platform.platform(), 'python': sys.version,
    'openssl': subprocess.check_output([openssl + '/bin/openssl', 'version'], text=True).strip(),
    'rust': subprocess.check_output(['rustc', '--version'], text=True).strip(),
    'linkage': linked, 'build_commit': os.environ.get('GITHUB_SHA'),
    'run_url': 'https://github.com/' + os.environ['GITHUB_REPOSITORY'] + '/actions/runs/' + os.environ['GITHUB_RUN_ID'],
}, indent=2) + '\n')
