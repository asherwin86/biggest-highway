import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game import coords, save
from game.config import CITY_Y, EARTH_LOOP_M, MAX_ALT


def test_good_save_round_trips():
    d = {'car': 'volt', 's': 1234.5, 'x': coords.lane_center_x(42), 'alt': -60.0, 'flying': True, 'laps': 3,
         'odometer': 99.0, 'traffic_auto': False, 'traffic_manual': 0.7, 'hour': 21.0, 'cruise': 40.0,
         'camera': 'Top'}
    assert save.sanitize(d) == d


def test_broken_saves_fall_back_to_defaults():
    for bad in (None, [], 'hello', 5, {'car': 'spaceship', 's': 'far', 'x': None, 'alt': 1e9, 'laps': 'many',
                                       'hour': float('nan'), 'cruise': -5, 'camera': 'drone', 'flying': 'yes',
                                       'traffic_manual': 7, 'extra': {'evil': 1}}):
        out = save.sanitize(bad)
        assert isinstance(out, dict)
        assert 'extra' not in out and out.get('car') is None and 'camera' not in out
    out = save.sanitize({'alt': 1e9, 'x': -5e9, 's': -10, 'traffic_manual': 7})
    assert out['alt'] == MAX_ALT
    assert out['x'] == coords.clamp_x(-5e9)
    assert 0 <= out['s'] < EARTH_LOOP_M
    assert out['traffic_manual'] == 1.0


def test_unreadable_file_is_ignored(tmp_path, monkeypatch):
    f = tmp_path / 'save.json'
    monkeypatch.setattr(save, 'SAVE_PATH', f)
    assert save.load() == {}                      # missing
    f.write_bytes(b'\xff\xfe not json')
    assert save.load() == {}                      # garbage
    f.write_text(json.dumps({'car': 'bolt', 'alt': CITY_Y}), encoding='utf-8')
    assert save.load()['car'] == 'bolt'
