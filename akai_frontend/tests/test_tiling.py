"""VRAM-aware tiling mathematics."""

from __future__ import annotations

from akai.engine import choose_tile, plan_tiles


def test_no_vram_means_whole_frame():
    assert choose_tile(3840, 2160, 0) == 0


def test_small_vram_shrinks_the_tile():
    small = choose_tile(3840, 2160, 2048)
    large = choose_tile(3840, 2160, 24576)
    assert 0 < small <= large


def test_tile_always_from_the_step_ladder():
    from akai.engine import TILE_STEPS

    for vram in (512, 2048, 4096, 8192, 24576):
        assert choose_tile(1920, 1080, vram) in TILE_STEPS


def test_plan_grid_covers_the_output():
    plan = plan_tiles(1920, 1080, 4, 4096)
    out_w, out_h = plan["out"]
    assert out_w == 7680 and out_h == 4320
    grid_x, grid_y = plan["grid"]
    assert grid_x * plan["tile"] >= out_w
    assert grid_y * plan["tile"] >= out_h


def test_cpu_path_uses_a_single_whole_frame_tile():
    plan = plan_tiles(1280, 720, 2, 0)
    assert plan["tile"] == 0
    assert plan["grid"] == (1, 1)


def test_overlap_is_reasonable_for_blending():
    plan = plan_tiles(1920, 1080, 4, 4096)
    if plan["tile"]:
        assert 8 <= plan["overlap"] <= plan["tile"] // 4


def test_tile_never_exceeds_memory_budget():
    for vram in (1024, 2048, 8192):
        tile = choose_tile(7680, 4320, vram)
        assert tile * tile * 14 <= vram * 1048576 // 2 or tile == 128
