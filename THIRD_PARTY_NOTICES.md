# Third-party components

OpenWrite is Apache-2.0. The separately maintained Studio panel retains its MIT
license. DoG is based on Fun10165/dsh-dog v1.2.0, BSD-3-Clause; its full license
and integration changes are in vendor/dsh-dog/LICENSE and UPSTREAM.md.

The editor ships Vditor and its auxiliary files with the upstream license in
packages/studio-panel/vendor/vditor/LICENSE. OpenWrite preset skills retain
their source licenses beside their SKILL.md files.

The release runtime manifest pins uv (MIT/Apache-2.0) and the Astral
python-build-standalone Python distribution (Python and bundled component
licenses). Archives are downloaded only on environment preparation and retain
their license files. URLs and SHA-256 values are in release/runtime-manifest.json.

Python dependency versions and distribution hashes are in release/requirements.lock.
JavaScript dependency versions, resolved origins and integrity values are in the
repository lockfiles. Host React, Cordis and dsh services are provided by dsh;
they are not inlined into the plugin's browser code.

The release includes an OpenWrite-built cryptography 50.0.1 wheel for macOS
x86_64 because upstream discontinued Intel Mac wheels. It is built from the
SHA-256 pinned upstream source with statically linked OpenSSL 3.6.3. The wheel
retains upstream licenses; OpenSSL's full license is in release/wheels/licenses.
Source hash, toolchain, linkage inspection and the native CI build URL are in
release/wheels/provenance.json. No cryptography source code was modified.

Intel Macs use the last official ONNX Runtime Intel wheel, 1.23.2; other
platforms use 1.29.0. Platform markers and distribution hashes are recorded in
release/requirements.lock and release/platform-overrides.in.

JavaScript runtime dependency license texts are retained in release/licenses,
with names, versions and upstream repositories in release/source.json.
