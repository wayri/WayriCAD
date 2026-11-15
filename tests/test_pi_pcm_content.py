from pathlib import Path

from build_pcm import plugin_files


def test_two_port_offline_guides_and_reproducible_examples_ship():
    base=Path(__file__).resolve().parents[1]/'quick_pi_plugin'
    names={path.relative_to(base).as_posix() for path in plugin_files(base)}
    for name in ('AC_PORTS.html','PLANE_PORTS.html','help-planar-pdn.png',
                 'examples/planar_pdn/README.md','examples/planar_pdn/study-24x12.json',
                 'examples/planar_pdn/result-24x12.json','examples/planar_pdn/provenance.json'):
        assert name in names
    assert not any(name.startswith('tests/') or name.endswith('.pyc') for name in names)
