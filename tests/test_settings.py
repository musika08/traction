import json
import os

from traction.settings import CONTROLLER_MODES, Settings, migrate_from_overdrive


def test_defaults_when_missing(tmp_path):
    s = Settings.load(str(tmp_path / "settings.json"))
    assert (s.controller_mode, s.grip_vibration, s.user_set) == ("gamepad", True, False)
    assert s.warning == ""
    assert not (tmp_path / "settings.json").exists()      # loading never writes


def test_each_field_checked_on_its_own(tmp_path):
    p = tmp_path / "settings.json"
    for mode in CONTROLLER_MODES:
        p.write_text(json.dumps({"controller_mode": mode}), encoding="utf-8")
        assert Settings.load(str(p)).controller_mode == mode
    for bad in ("Desktop", "mouse", 1, None, ["auto"]):
        p.write_text(json.dumps({"controller_mode": bad, "grip_vibration": False}), encoding="utf-8")
        s = Settings.load(str(p))
        assert s.controller_mode == "gamepad" and s.grip_vibration is False   # the other field is kept
    for bad in ("no", 0, 1, None):
        p.write_text(json.dumps({"grip_vibration": bad}), encoding="utf-8")
        assert Settings.load(str(p)).grip_vibration is True
    for bad in ("yes", 1, None):
        p.write_text(json.dumps({"user_set": bad}), encoding="utf-8")
        assert Settings.load(str(p)).user_set is False


def test_round_trip_and_bak(tmp_path):
    p = tmp_path / "sub" / "settings.json"
    s = Settings.load(str(p))
    s.controller_mode, s.grip_vibration, s.user_set = "auto", False, True
    s.save()
    again = Settings.load(str(p))
    assert (again.controller_mode, again.grip_vibration, again.user_set) == ("auto", False, True)
    assert json.loads(p.read_text(encoding="utf-8")) == {"controller_mode": "auto", "grip_vibration": False,
                                                         "user_set": True}
    assert os.path.exists(str(p) + ".bak")


def test_bom_is_accepted(tmp_path):
    p = tmp_path / "settings.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"controller_mode": "desktop"}).encode("utf-8"))
    assert Settings.load(str(p)).controller_mode == "desktop"


def test_unreadable_file_is_kept_before_it_is_overwritten(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{", encoding="utf-8")
    s = Settings.load(str(p))
    assert s.controller_mode == "gamepad"
    assert s.warning.startswith("Traction settings could not be read and were reset")
    copies = [n for n in os.listdir(tmp_path) if n.startswith("settings.json.unreadable-")]
    assert len(copies) == 1 and (tmp_path / copies[0]).read_text(encoding="utf-8") == "{"
    s.save()
    assert Settings.load(str(p)).controller_mode == "gamepad"


# ---------- moving the controller settings over from Overdrive (spec 3.3) ----------

def overdrive_file(tmp_path, content) -> str:
    folder = tmp_path / "overdrive"
    folder.mkdir(exist_ok=True)
    p = folder / "overdrive.json"
    if isinstance(content, str):
        p.write_text(content, encoding="utf-8")
    else:
        p.write_text(json.dumps(content), encoding="utf-8")
    return str(p)


def traction_settings(tmp_path) -> Settings:
    return Settings.load(str(tmp_path / "traction" / "settings.json"))


def test_migrate_takes_overdrive_values(tmp_path):
    od = overdrive_file(tmp_path, {"mode": "turbo", "controller_mode": "auto", "grip_vibration": False,
                                   "user_set": False})
    s = traction_settings(tmp_path)
    assert migrate_from_overdrive(od, s) is True
    # final review T3: the values are taken, but user_set only follows Overdrive's own user_set
    assert (s.controller_mode, s.grip_vibration, s.user_set) == ("auto", False, False)
    # Overdrive's file is only read, never changed.
    assert json.loads(open(od, encoding="utf-8").read())["controller_mode"] == "auto"
    assert sorted(os.listdir(tmp_path / "overdrive")) == ["overdrive.json"]
    # Only one value present: that one is taken, the other keeps its default.
    s2 = traction_settings(tmp_path)
    assert migrate_from_overdrive(overdrive_file(tmp_path, {"grip_vibration": False}), s2) is True
    assert (s2.controller_mode, s2.grip_vibration, s2.user_set) == ("gamepad", False, False)


def test_migrate_user_set_follows_overdrive(tmp_path):
    for user_set, want in ((True, True), (False, False), (None, False), ("yes", False), (1, False)):
        data = {"controller_mode": "desktop", "grip_vibration": False}
        if user_set is not None:
            data["user_set"] = user_set
        s = traction_settings(tmp_path)
        assert migrate_from_overdrive(overdrive_file(tmp_path, data), s) is True, user_set
        assert (s.controller_mode, s.grip_vibration, s.user_set) == ("desktop", False, want), user_set


def test_migrate_missing_unreadable_or_bad_values_keep_defaults(tmp_path):
    cases = {"missing": None, "unreadable": "{", "bad value": {"controller_mode": 5},
             "not an object": "[1, 2]", "bad vibration": {"grip_vibration": "off"}, "no keys": {"mode": "turbo"}}
    for what, content in cases.items():
        if content is None:
            od = str(tmp_path / "nowhere" / "overdrive.json")
        else:
            od = overdrive_file(tmp_path, content)
        s = traction_settings(tmp_path)
        assert migrate_from_overdrive(od, s) is False, what
        assert (s.controller_mode, s.grip_vibration, s.user_set) == ("gamepad", True, False), what
    # An unreadable Overdrive file is left exactly as it is (no copy is made in Overdrive's folder).
    od = overdrive_file(tmp_path, "{")
    migrate_from_overdrive(od, traction_settings(tmp_path))
    assert sorted(os.listdir(tmp_path / "overdrive")) == ["overdrive.json"]


def test_migrate_not_run_when_traction_file_exists(tmp_path):
    od = overdrive_file(tmp_path, {"controller_mode": "auto", "grip_vibration": False})
    s = traction_settings(tmp_path)
    s.save()                                   # Traction's own file exists (defaults)
    s = traction_settings(tmp_path)
    assert migrate_from_overdrive(od, s) is False
    assert (s.controller_mode, s.grip_vibration, s.user_set) == ("gamepad", True, False)
    # An unreadable Traction file counts as existing too: Overdrive's values never replace it.
    p = tmp_path / "traction" / "settings.json"
    p.write_text("{", encoding="utf-8")
    s = traction_settings(tmp_path)
    assert migrate_from_overdrive(od, s) is False and s.controller_mode == "gamepad"


# ---------- button bindings ----------

FACTORY = {"gamepad": {}, "desktop": {}, "m1_secondary": True, "m2_secondary": True}


def test_bindings_default_to_factory_and_older_files_load(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"controller_mode": "desktop", "user_set": True}), encoding="utf-8")
    s = Settings.load(str(p))
    assert s.bindings == FACTORY
    assert s.controller_mode == "desktop"


def test_v1_file_loads_as_v2(tmp_path):
    """Review Focus 1: a v1 file keeps the owner's mapping (M1 as B, Shift+A = Screenshot) and touched zones."""
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"user_set": True, "touched_zones": [5, 8],
                             "bindings": {"back_left": "shift", "back_right": "b", "combos": {"a": "screenshot"}}}),
                 encoding="utf-8")
    s = Settings.load(str(p))
    assert s.bindings == {"gamepad": {"back_right": {"primary": "b"}, "a": {"secondary": "screenshot"}},
                          "desktop": {"back_right": {"primary": "b"}}, "m1_secondary": False, "m2_secondary": True}
    assert s.touched_zones == {5, 8}
    s.save()
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["bindings"] == {"gamepad": {"back_right": {"primary": "b"}, "a": {"secondary": "screenshot"}},
                                 "desktop": {"back_right": {"primary": "b"}}, "m1_secondary": False}
    assert Settings.load(str(p)).bindings == s.bindings


def test_bindings_round_trip_and_junk_dropped(tmp_path):
    p = tmp_path / "settings.json"
    s = Settings.load(str(p))
    s.bindings = {"gamepad": {"a": {"secondary": "screenshot"}}, "desktop": {}, "m1_secondary": True,
                  "m2_secondary": False}
    s.save()
    saved = json.loads(p.read_text(encoding="utf-8"))
    # only the owner's choices are stored (missing keys mean factory, a switch only when off)
    assert saved["bindings"] == {"gamepad": {"a": {"secondary": "screenshot"}}, "m2_secondary": False}
    assert Settings.load(str(p)).bindings == s.bindings
    s.bindings = FACTORY
    s.save()
    assert "bindings" not in json.loads(p.read_text(encoding="utf-8"))
    p.write_text(json.dumps({"grip_vibration": False, "bindings": {
        "gamepad": {"a": {"primary": "gone", "secondary": "esc"}, "zz": {"primary": "a"},
                    "back_left": {"secondary": "a"}}, "desktop": 3, "m1_secondary": "no"}}), encoding="utf-8")
    s = Settings.load(str(p))
    assert s.bindings == {"gamepad": {"a": {"secondary": "esc"}}, "desktop": {}, "m1_secondary": True,
                          "m2_secondary": True}
    assert s.grip_vibration is False                       # the other fields are kept
    for bad in ("x", 1, None, ["a"]):
        p.write_text(json.dumps({"bindings": bad}), encoding="utf-8")
        assert Settings.load(str(p)).bindings == FACTORY


def test_touched_zones_round_trip_and_junk_dropped(tmp_path):
    p = tmp_path / "settings.json"
    s = Settings.load(str(p))
    assert s.touched_zones == set()
    s.touched_zones = {8, 5}
    s.save()
    assert json.loads(p.read_text(encoding="utf-8"))["touched_zones"] == [5, 8]
    assert Settings.load(str(p)).touched_zones == {5, 8}
    p.write_text(json.dumps({"touched_zones": [0, 3, 10, "4", True, 9, 3.0]}), encoding="utf-8")
    assert Settings.load(str(p)).touched_zones == {3, 9}
    for bad in ("5", 5, None, {"5": 1}):
        p.write_text(json.dumps({"touched_zones": bad}), encoding="utf-8")
        assert Settings.load(str(p)).touched_zones == set()


def test_settings_library_roundtrip_and_junk(tmp_path):
    p = tmp_path / "settings.json"
    s = Settings.load(str(p))
    assert s.library == {"single": "armoury", "long": "armoury"} and s.library_written is False
    s.library = {"single": "asus_show_desktop", "long": "esc"}
    s.library_written = True
    s.save()
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["library"] == {"single": "asus_show_desktop", "long": "esc"} and raw["library_written"] is True
    again = Settings.load(str(p))
    assert again.library == {"single": "asus_show_desktop", "long": "esc"} and again.library_written is True
    # unknown ids become "armoury", the rest is kept; a stored armoury_button (first Part B) is dropped
    p.write_text(json.dumps({"library": {"single": "nothing", "long": "win"}, "library_written": "yes",
                             "armoury_button": "task_manager", "grip_vibration": False}), encoding="utf-8")
    s = Settings.load(str(p))
    assert s.library == {"single": "armoury", "long": "win"} and s.library_written is False
    assert s.grip_vibration is False and not hasattr(s, "armoury_button")
    s.save()
    assert "armoury_button" not in json.loads(p.read_text(encoding="utf-8"))
    for bad in ("esc", 5, None, ["esc"], {"single": 3}):
        p.write_text(json.dumps({"library": bad}), encoding="utf-8")
        assert Settings.load(str(p)).library == {"single": "armoury", "long": "armoury"}, bad
    # nothing chosen and nothing to restore: no library keys at all
    s = Settings.load(str(tmp_path / "other.json"))
    assert "library" not in s.to_dict() and "library_written" not in s.to_dict()
