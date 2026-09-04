from pathlib import Path

from studio.backend import strategy_service


def _request(state: str = "side_attack", frames: int = 6) -> dict:
    return {"states": {state: {"frames": frames, "fps": 8, "loop": False, "action": "attack"}}}


def test_auto_attack_resolves_to_keypose_sequential(tmp_path: Path) -> None:
    result = strategy_service.resolve(tmp_path, _request(), "side_attack")
    assert result["requested"] == "AUTO"
    assert result["resolved"] == "KEYPOSE_SEQUENTIAL"


def test_motion_plan_marks_key_poses_and_persists(tmp_path: Path) -> None:
    plan = strategy_service.motion_plan(tmp_path, _request(), "side_attack", "KEYPOSE_SEQUENTIAL")
    path = strategy_service.save_motion_plan(tmp_path, plan)
    loaded = strategy_service.load_motion_plan(tmp_path, "side_attack")
    assert path.is_file()
    assert loaded == plan
    assert plan["key_pose_indices"] == [0, 1, 3, 5]
    assert plan["phases"][2]["role"] == "between"


def test_strategy_override_is_scoped_to_one_run(tmp_path: Path) -> None:
    states = strategy_service.set_override(tmp_path, "side_idle", "ROW_FAST")
    result = strategy_service.resolve(tmp_path, _request("side_idle", 8), "side_idle")
    assert states == {"side_idle": "ROW_FAST"}
    assert result["requested"] == "ROW_FAST"
    assert result["resolved"] == "ROW_FAST"
