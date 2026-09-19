from tools.open_kicad import editor_path, launch_environment
import pytest


def test_private_namespace_preserves_user_config_and_libraries(tmp_path):
    source = {'TEMP': 'old', 'TMP': 'old', 'KICAD_API_SOCKET': 'wrong', 'KICAD_API_TOKEN': 'secret',
              'KICAD_CONFIG_HOME': 'user-config', 'KICAD_DOCUMENTS_HOME': 'user-documents',
              'KICAD10_3DMODEL_DIR': 'models', 'PATH': 'tools'}
    result = launch_environment(source, tmp_path)
    assert result['TEMP'] == result['TMP'] == str(tmp_path)
    assert 'KICAD_API_SOCKET' not in result and 'KICAD_API_TOKEN' not in result
    assert all(result[k] == source[k] for k in ('KICAD_CONFIG_HOME', 'KICAD_DOCUMENTS_HOME', 'KICAD10_3DMODEL_DIR', 'PATH'))
    assert source['KICAD_API_TOKEN'] == 'secret'


def test_non_windows_environment_keeps_temporary_directory():
    assert launch_environment({'TMP': '/tmp', 'OTHER': 'value'}) == {'TMP': '/tmp', 'OTHER': 'value'}


def test_explicit_executable_and_missing_path(tmp_path):
    executable = tmp_path / 'pcbnew'
    executable.write_text('fixture')
    assert editor_path(executable) == executable.resolve()
    with pytest.raises(ValueError, match='does not exist'):
        editor_path(tmp_path / 'missing')
