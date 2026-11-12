"""사진 올리기 한도: Streamlit 설정(maxUploadSize, MB)과 앱 검사 한도가 같아야 한다."""
import tomllib
from pathlib import Path

from exhibition_app import photos


def test_upload_limit_matches_streamlit_config():
    cfg = tomllib.loads((Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml").read_text("utf-8"))
    assert cfg["server"]["maxUploadSize"] * 1024 * 1024 == photos.MAX_UPLOAD_BYTES
