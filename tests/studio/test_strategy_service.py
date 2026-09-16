import json
from pathlib import Path

from PIL import Image

from studio.backend import sequential_service, strategy_service


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


def test_sequential_promotion_publishes_shared_frame_manifest(tmp_path: Path) -> None:
    state = "side_attack"
    request = {
        "states": {state: {"frames": 4, "fps": 8, "loop": False}},
        "cell": {"width": 32, "height": 32, "safe_margin": 2},
        "fit": {"align_y": "bottom"},
        "chroma_key": {"rgb": [255, 0, 255]},
    }
    (tmp_path / "sprite-request.json").write_text(json.dumps(request), encoding="utf-8")
    sequence_dir = tmp_path / "studio" / "sequential" / state
    sequence_dir.mkdir(parents=True)
    sources = []
    for index in range(4):
        path = sequence_dir / f"source-{index}.png"
        Image.new("RGBA", (16, 16), (20 + index, 40, 60, 255)).save(path)
        sources.append(path)
    plan = strategy_service.motion_plan(tmp_path, request, state, "KEYPOSE_SEQUENTIAL")
    manifest = {
        "state": state,
        "status": "sequential_frames_generated",
        "motion_plan": plan,
        "accepted_key_poses": [0, 1, 3],
        "key_poses": [
            {"index": 0, "phase": "start", "role": "key", "path": str(sources[0])},
            {"index": 1, "phase": "windup", "role": "key", "path": str(sources[1])},
            {"index": 3, "phase": "impact", "role": "key", "path": str(sources[3])},
        ],
        "inbetweens": [{"index": 2, "phase": "accel", "role": "between", "path": str(sources[2])}],
    }
    (sequence_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    promoted = sequential_service.promote_to_shared_frames(tmp_path, state)

    assert promoted["status"] == "promoted"
    assert all((tmp_path / "frames" / "side_attack" / f"frame-{index}.png").is_file() for index in range(4))
    for index in range(4):
        with Image.open(tmp_path / "frames" / "side_attack" / f"frame-{index}.png") as image:
            assert image.size == (32, 32)
    frames_manifest = json.loads((tmp_path / "frames" / "frames-manifest.json").read_text(encoding="utf-8"))
    assert frames_manifest["rows"][0]["method"] == "sequential-promoted"
    assert frames_manifest["rows"][0]["files"] == [f"frames/side_attack/frame-{index}.png" for index in range(4)]
