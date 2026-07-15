"""
The downloadable recording agent is a self-contained zipapp the PC owner runs
with `python vantage_recorder.pyz`. These tests prove the bundle is coherent:
valid zip, the right members, every member is syntactically valid Python, the
flat import layout the zip relies on is what the modules actually use, and the
per-Vantage config (URL + pairing code) is baked into the bundled bridge agent.
"""

import io
import zipfile

from alibi.cameras import recorder, bridge_agent, record_agent
from alibi.alibi_api import _bake_agent_config


def _build_zip(base_url="https://example.test", code="ABC123"):
    with open(recorder.__file__) as f:
        recorder_src = f.read()
    with open(record_agent.__file__) as f:
        record_agent_src = f.read()
    with open(bridge_agent.__file__) as f:
        bridge_agent_src = _bake_agent_config(f.read(), base_url, code)
    main_src = "import sys\nimport record_agent\nsys.exit(record_agent.main())\n"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("recorder.py", recorder_src)
        z.writestr("bridge_agent.py", bridge_agent_src)
        z.writestr("record_agent.py", record_agent_src)
        z.writestr("__main__.py", main_src)
    buf.seek(0)
    return buf.read()


def test_zip_has_expected_members():
    z = zipfile.ZipFile(io.BytesIO(_build_zip()))
    assert set(z.namelist()) == {
        "recorder.py", "bridge_agent.py", "record_agent.py", "__main__.py"
    }
    assert z.testzip() is None       # not corrupt


def test_every_member_compiles():
    z = zipfile.ZipFile(io.BytesIO(_build_zip()))
    for name in z.namelist():
        src = z.read(name).decode()
        compile(src, name, "exec")   # raises SyntaxError if malformed


def test_main_invokes_record_agent():
    z = zipfile.ZipFile(io.BytesIO(_build_zip()))
    main = z.read("__main__.py").decode()
    assert "record_agent.main()" in main


def test_config_is_baked_into_bridge_agent():
    z = zipfile.ZipFile(io.BytesIO(_build_zip(base_url="https://vx.example", code="Z9Z9")))
    ba = z.read("bridge_agent.py").decode()
    assert 'os.environ.get("VANTAGE_URL", "https://vx.example")' in ba
    assert 'os.environ.get("VANTAGE_PAIRING_CODE", "Z9Z9")' in ba


def test_modules_use_flat_import_fallback():
    """The zip layout is flat (no `alibi/` package), so record_agent must be able
    to import `recorder` / `bridge_agent` by bare name."""
    src = record_agent.__file__ and open(record_agent.__file__).read()
    assert "from recorder import" in src          # fallback path exists
    assert "import bridge_agent as ba" in src
