import pytest
from helixer.core.controller import HelixerController


def test_controller():
    with pytest.raises(TypeError) as e:
        _ = HelixerController()
    assert "__init__() missing 4 required positional arguments: 'db_path_in', 'db_path_out', 'meta_info_root_path', and 'meta_info_csv_path'" == str(e.value)
