from pathlib import Path


path = Path("studio/api/routers/pixelize.py")
text = path.read_text(encoding="utf-8")
start = text.index("    try:\n        result = pixelize_service.pixelize_asset(")
end = text.index("    return PixelizeResponse(\n", start)
replacement = '''    try:
        if body.strategy == "reference_pixel_master_128":
            if body.size != 128:
                raise ValueError("reference_pixel_master_128 requires size=128")
            result_payload = pixelize_service.c2_result_payload(pixelize_service.c2_pixelize_asset(
                info,
                body.asset,
                target_size=128,
                palette_size=None if body.palette == "auto" else int(body.palette),
                alpha_threshold=body.alpha_threshold,
            ))
        else:
            result_payload = pixelize_service.result_payload(pixelize_service.pixelize_asset(
                info,
                body.asset,
                target_size=body.size,
                palette_size=None if body.palette == "auto" else int(body.palette),
                dither=body.dither,
                background=body.background,
                outline=body.outline,
                subject_mode=body.subject_mode,
                subject_bbox=body.subject_bbox,
                detail=body.detail,
                alpha_threshold=body.alpha_threshold,
            ))
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = result_payload
    paths = payload["paths"]
'''
text = text[:start] + replacement + text[end:]
text = text.replace(
    "    return PixelizeResponse(\n        output_asset=",
    "    return PixelizeResponse(\n        strategy=body.strategy,\n        output_asset=",
    1,
)
text = text.replace(
    "        report=payload[\"report\"],\n    )",
    "        report=payload[\"report\"],\n        raw_asset=_asset_url(project_id, info.path, paths[\"raw\"]) if \"raw\" in paths else None,\n        intermediate_asset=_asset_url(project_id, info.path, paths[\"intermediate\"]) if \"intermediate\" in paths else None,\n        post_asset=_asset_url(project_id, info.path, paths[\"post\"]) if \"post\" in paths else None,\n    )",
    1,
)
path.write_text(text, encoding="utf-8")
