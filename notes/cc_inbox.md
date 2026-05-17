
## [observation] Houdini scene audit oak_assemble.hip — Part 1/2: топологія, USD, lights, variants
_2026-05-17T15:41:14_
> consumed 2026-05-17 — vocabulary absorbed; standalone scene-doc not promoted because this scene is single-look. Patterns (prune-all+unprune-one, edit_* lights, per-shot AOV groups) noted for future whitelist expansion.

# HOUDINI SCENE AUDIT — oak_assemble.hip (Part 1/2)

> diff проти дефолтів для /stage та /obj. Зібрано через MCP `get_node_info(only_non_default=true)`.
> Часткове покриття (~30 з 332 нод детально). Решту — через Python-скрипт у Part 2.

## 0. МЕТА
- **File**: `C:/houdini_mcp_sandbox/oak_assemble.hip`
- **Total nodes**: 2922 (332 на топ-рівні /stage, 4 на /obj)
- **FPS**: 24, **Frame range**: 1001-1077
- **Project**: `//loky.plarium.local/project/_pl/raid_grand_oak/cinematic/sq010`
- **Shots**: sh040, sh080, sh120 (sh040 найбільш повно деталізована)
- **Renderer**: Arnold (htoa), **Color**: ACES/ACEScg
- **Farm**: Deadline (Department=lighting, Priority=50, 1 frame/task)
- **Env vars**: `$FTRACK_ROOT_PATH`, `$FTRACK_STUDIO_PATH`, `$FTRACK_CACHE_PATH`

## PLUGIN BUGS (зафіксувати, можливо patch SAFE_PARMS)
1. `houdini:get_node_info` падає на `ObjNode` з помилкою `'ObjNode' object has no attribute 'isBypassed'`. /obj/* всі 4 ноди недоступні: `cam_sh040`, `cam_sh080`, `cam_sh120` (всі lopimportcam) + `null1`.
2. Деякі /stage ноди повертають `'NoneType' object has no attribute 'name'`: `/stage/moon`, `/stage/hdri`, `/stage/tree_decoy`, `/stage/NO_PROXY_TEX1`, `/stage/NO_PROXY_TEX2`. Ймовірно пошкоджені connections або internal sub-refs.

## 1. ТОПОЛОГІЯ ВИСОКОГО РІВНЯ

### Render stack pattern (для кожного pl_render)
```
pl_usd_import → pl_shot_merge1 → bloodmasks_variants → prune_blodmasks_maces → unprune_main_mace1
→ sublayer/reference → materiallibrary+attribwrangle+assignmaterial → setvariant/configureprimitive/configurelayer
→ prune_unseen/prune_atmo/prune_leaf_mehslight/hide_chars → rendergeometrysettings (subdiv/matte)
→ lights+lightlinker+light filters → pl_aovs → rendersettings → pl_render → pl_renderfarm (deadline)
```

### pl_render виходи (25+ total)
- **sh040**: `sh040_all`, `sh040_env`, `sh040_env_leafFrontLight`, `sh040_env_leafMeshlight`, `sh040_env_tech`, `sh040_env_no_water`, `sh040_chars`, `sh040_chars_tech`, `sh040_atmo`, `sh040_magicGlow`, `sh040_inside_flowFX`, `sh040_FlowFX_alpha`, `sh040_FlowFX`, `sh040_FlowFX_smoke`
- **sh080**: `sh080_env`, `sh080_chars`, `sh080_atmo`, `sh080_magicGlow`, `sh080_env_crop`
- **sh120**: `sh120_env`, `sh120_chars`, `sh120_atmo`, `sh120_magicGlow`, `sh120_env_tech`
- **Інші**: `WIP`, `WIP1..WIP3`, `test_light`, `pl_rendasfsafer1`, `pl_rendasfsafer2` (підозра на typo!)

### Sequence outputs
- `sequence_lighting`, `sequence_lighting1` (pl_usd_rop) — USD writers
- `ftrack_publish1`, `ftrack_publish2` — ftrack pipeline
- `loky_saveUsd1`, `loky_saveUsd2` — optimize USD cache writers
- `roots_optimize`, `roots_optimize1` (pl_usd_rop)

## 2. USD IMPORT (pl_usd_import × 3)

Кожний `/stage/sh{040|080|120}` має:
- `filepath1` (raw): `$FTRACK_ROOT_PATH/raid_grand_oak/cinematic/sq010/sh{NNN}/shot.usd`
- `layerbreak=on`
- `node_version=1.0.15`

**ВЕЛИКИЙ default_context** — query string з version-pin-ами всіх USD-ассетів. Приклад для sh040:
```
shot.usd?
  raid_grand_oak/cinematic/sq010/sh040/usd=v016
  &raid_assets/props/grand_oak_tree/usd-deform=v008
  &raid_grand_oak/cinematic/sq010/sh010/usd-leaf_fx=v003
  &raid_assets/locations/grand_oak/usd-assembling=v018
  &raid_grand_oak/cinematic/sq010/sh040/usd-magic_flow_fx=v001
  &raid_grand_oak/cinematic/sq010/sh040/usd-grand_oak_tree_fx=v001
  &raid_grand_oak/cinematic/sq010/sh040/usd-leaf_fx=v001
  &raid_grand_oak/cinematic/sq010/sh040/usd-bloodmask_cfx_voitovych=v002
  &raid_grand_oak/cinematic/sq010/sh040/usd-magic_flip_fx=v003
  &raid_grand_oak/cinematic/sq010/sh040/anim-bloodmask_{a..e,main}=v00{6..7}
  &raid_grand_oak/cinematic/sq010/sh040/anim-grand_oak_tree=v001
  &raid_assets/characters/bloodmask/usd-lookdev=v033
  &raid_assets/props/grand_oak_tree/usd-lookdev=v009
  &raid_grand_oak/cinematic/sq010/usd-rendering=v006
  &raid_grand_oak/cinematic/sq010/usd-lighting=v006
  &raid_grand_oak/cinematic/sq010/sh{010..240}/cam=vNNN  (камери всіх 20+ шотів)
  &raid_grand_oak/cinematic/sq010/usd-watter_fx=v005
  &raid_assets/props/grand_oak_tree/anim-grand_oak_tree=v002
  &tools/camera/camera_distortion/lens018-map=v001
```
sh080 додатково: `usd-dead_bladmasks=v004`, `lens027-map=v001`.

## 3. ВАРІАНТИ / SETVARIANT

### bloodmasks_variants (3 variants, color rose pink)
- num_variants=3
- [1] pattern=`/chars/bloodmask_*`, variantset=geo, name=`half_armor`
- [2] pattern=`/chars/bloodmask_main`, variantset=geo, name=`full_armor`
- [3] **DISABLED** (enable3=off)
- Логіка: всі bloodmasks → half_armor, main → full_armor

### setvariant1 (camera distortion)
- primpattern=`/cams/cam_sh040`, variantset=`distortion`

## 4. PRUNE PATTERNS (selective deactivation)

| Path | Bypassed | Pattern |
|---|---|---|
| `/stage/prune_unseen` | no | `/env/locations/grand_oak/bushes_bg/{bush_1, spiral_branches_1, bush_extended_tunels_1}` |
| `/stage/prune_atmo` | no | `/fx/atmo /fx/water/magic_glow_volume` |
| `/stage/prune_leaf_mehslight` | **YES** | `/lights/leaf_geo_light1` |
| `/stage/prune_blodmasks_maces` | no | `/chars/bloodmask_*/geo/mdl/bloodmask_mdl/zMace` |
| `/stage/unprune_main_mace1` | no | `/chars/bloodmask_main/geo/mdl/bloodmask_mdl/zMace`, `prune=0` (re-activate!) |
| `/stage/hide_chars2` | no | `/chars` (env-only render) |

**Pattern "prune all + unprune one"** — використовується двічі для selective enable.

## 5. LIGHTS (30+ light::2.0, 3 domelight::3.0)

### /stage/tree (UsdLuxSphereLight)
- primpath: `/lights/tree`, ty=8
- color=(1.0, 0.706, 0.926) теплий рожевий
- exposure=8, radius=1.7
- arnold: samples=3, **camera=0** (no direct camera ray!), volume=0.4
- AOV Light Group: `tree`

### /stage/far (UsdLuxDiskLight)
- primpath: `/lights/far`, ty=413.6654 (very high!)
- lookat=on
- intensity=5000, exposure=2
- color=(1.15, 1.286, 2.0) синій
- width=60, height=60, radius=1, normalize=on
- arnold: spread=0.1 (narrow), volume=0.01
- AOV Light Group: `far`

### /stage/edit_tree (BYPASSED) — pattern "edit existing light"
- primpattern=`/lights/tree`, createprims=off
- Якщо ввімкнути: exposure=5, color=(1.0, 0.537, 0.404), radius=1.7, clipping=0.001
- Підключає shader: `/lights/tree/filters/lightFilter`
- AOV Group: `tree`

### Light inventory (без детального diff, але імена груп)
- env: `moon`, `moon1..3`, `hdri`, `hdri2`, `water`, `water1`, `center`, `center1`, `tree`, `tree1`, `far`, `far1`
- tree-specific: `tree_water1..6`, `tree_leaves_backlight1..13`, `tree_leaves_frontlight`, `tree_leaves_frontlight1`
- characters (per-shot): `char_moon`, `char_moon1..2`, `char_red`, `char_red1..3`, `char_fill`, `char_fill1..2`, `char_soft_front`, `char_soft_front1`
- utility: `light_emptry`, `light_emptry1`, `light_edit1`, `light1`, `edit_center`, `edit_tree_1`, `edit_tree_2`

## 6. LIGHT FILTERS (loky_ArnoldlightFilter × 16)
- 16 instances: `loky_ArnoldlightFilter1..16`, `tree_decoy`, `water_decoy`, `tree_decoy1`, `water_decoy1`
- Перевірено `loky_ArnoldlightFilter2`: **BYPASSED**, дефолтні параметри
- Студійна нода (намісне custom OTL з Loky pipeline)

## 7. LIGHTLINKER
- `/stage/lightlinker{1,2,3,5}` — всі мають 3 параметри, всі дефолтні. Likely linkage rules задані у внутрішніх sub-network нодах (треба inspect).

## 8. ВИЯВЛЕНІ ПАТЕРНИ / АНТИ-ПАТЕРНИ

### Patterns (добре)
1. **"Prune all + unprune one"** — selective enabling
2. **Per-shot render variants** — окремі pl_render під кожен pass
3. **Per-light Arnold AOV groups** — `xn__primvarsarnoldaov_t3ag` для compositing
4. **"Edit" lights** — `edit_tree`, `edit_center` тощо для tweaks без зміни оригінала

### Anti-patterns
1. **`pl_rendasfsafer1/2`** — підозра на typo (`pl_render`?). ПЕРЕВІРИТИ!
2. **Дубльовані materiallibrary** — 8+ instances для різних cases
3. **bucket_size=16** (default Arnold=64) — debug residue?
4. **crypto_object=off** на pl_aovs8 — без cryptomatte у comp складно

## ПИТАННЯ ДЛЯ CC
1. `pl_rendasfsafer1/2` — typo чи валідний asset?
2. `bucket_size=16` — інтенційно чи residual?
3. `crypto_object=off` — потрібно?
4. `ignore_dof=on` на rendersettings18 — точно?
5. `reference1.enable=off` — навіщо ця нода тоді?
6. Bypassed sublayer1 (water fx), edit_tree, prune_leaf_mehslight — feature flags?
7. `cardtexture*=C:/houdini_mcp_sandbox/tex/*.png` — це plugin підмінив `$HIP`. Реальний `$HIP` у проді інший.

**Part 2 містить**: VEX-сніпети, rendersettings deep dive, render farm, Python скрипт для повного дампу.

---

## [observation] Houdini scene audit oak_assemble.hip — Part 2/2: materials, VEX, rendersettings, deadline + Python dump script
_2026-05-17T15:42:16_
> resolved 2026-05-17 (72f8490) — Python crawler saved as `scripts/dump_scene.py`. Materials/VEX/rendersettings vocabulary noted for whitelist expansion. anti-patterns (`pl_rendasfsafer`, `bucket_size=16`, `crypto_object=off`) recorded for Sashok to verify in scene — those are scene-config decisions, not infra TODOs.

# HOUDINI SCENE AUDIT — oak_assemble.hip (Part 2/2)

> Продовження. Деталі по materials, VEX, render settings, deadline + повний Python-скрипт.
> Початок див. в Part 1.

## 9. MATERIALS / ASSIGN / VEX

### materiallibrary4 → /stage/materiallibrary4
- genpreviewshaders=off, matflag1=on (тільки VOPs з material flag)
- matnode1=`*`, assign1=off
- input: NO_PROXY_TEX2 (setvariant)

### create_atmo_mat (materiallibrary)
- matpathprefix=`/atmo/mtl/`
- geopath1=`/atmo`

### assignmaterial1 (2 materials, 1 disabled)
- [1] /fx/water/water_surface/mesh_0 → /fx/water/mtl/water_surface (purpose=full)
- [2] **DISABLED** (/env/locations/grand_oak/blocking/blocking/geo → /fx/water/mtl/roots, strength=strong)

### VEX: attribwrangle3 — wet maps
```
primpattern: /chars/** + %type:Mesh
custom param: y = 0.3
VEX:
  if(v@points[1] < chf("y"))
      f@primvars:wet = 0.5;
```
**Логіка**: всі частини персонажів нижче Y=0.3 отримують primvars:wet = 0.5.

### VEX: scale_leaf — instance scaling
```
primpattern: /fx/leaf_fx/geo/SG_leaf/instancer
custom param: scale_mult = 0.86
VEX:
  float mult = chf("scale_mult");
  vector scales[] = usd_attrib(0, @primpath, "scales");
  for (int i = 0; i < len(scales); i++)
      scales[i] *= mult;
  usd_setattrib(0, @primpath, "scales", scales);
```
**Логіка**: 14% зменшення всіх leaf instances.

## 10. RENDERGEOMETRYSETTINGS (subdiv/matte/visibility)

### blood_masks_subdiv_0
- primpattern=`/chars/bloodmask_*/**`
- subdiv:type=catclark, **iterations=0** (вимикає subdiv для bloodmask!)

### all_matte
- primpattern=`/chars /crowd /env /props/** /fx/water/**  /fx/leaf_fx_idle /fx/leaf_scatter`
- arnold:matte=on
- Призначення: ВСЕ matte для magic glow pass — тримає видимим тільки magic glow

## 11. CONFIGUREPRIMITIVE / CONFIGURELAYER / SUBLAYER

### configureprimitive2 (атмосфера)
- primpattern=`/atmo`
- purpose=`render`, visibility=`invisible`(!) — render-purpose але невидиме
- drawmode=`bounds`
- cardtexture*=`$HIP/tex/{X|Y|Z}{Neg|Pos}.png` (plugin підмінив на `C:/houdini_mcp_sandbox/`)

### configurelayer4
- setsavepath=on, savepath=`atmo.usd`, starttime/endtime=$FSTART/$FEND

### sublayer1 (**BYPASSED**)
- filepath1=`$FTRACK_ROOT_PATH/raid_grand_oak/cinematic/sq010/usd-watter_fx/fx.usd`

### grand_oak (sublayer)
- filepath1=`$FTRACK_ROOT_PATH/raid_assets/locations/grand_oak/environment.usd`

## 12. LOKY_SAVEUSD (Loky pipeline cache)

### loky_saveUsd1
- name=`sh040_optimize`, version=5
- SavePlace=`$FTRACK_CACHE_PATH`
- Final path: `//loky.plarium.local/.../houdini_cache/usd/sh040_optimize/v005/sh040_optimize_v005.usd`
- inputs: prune_unseen(0), ground_branches_optimize(1)

## 13. EDIT PROPERTIES (overrides)

### emission_Off
- primpattern=`/fx/water/mtl/magic_scum_particles/standard_surface1 /props/grand_oak_tree/mtl/*/standard_surface*`
- inputs:emission = 0.0 (вимикає emission на цих shader-ах)

### edit_cam_sh040
- primpattern=`/cams/cam_sh040`
- primvars:arnold:uv_remap = "" (empty UV remap override)

## 14. CAMERAS (нативні USD)

### test_cam1
- primpath=`/cameras/test_cam1`
- tx=12.50, ty=3.25, tz=11.67, rx=-4.22, ry=57.23, rz≈0
- **focal=17mm** (wide-angle), aperture=setratio, horizontalAperture=0.20955

### vfx01_crop1 (студійна нода для crop renders)
- dataWindowNDC4 = 0.5750882625579834

## 15. PL_AOVS (приклад)

### pl_aovs8
- active_render_products=15 (всі категорії active)
- pl_aovs_version=1 (v002)
- **crypto_object=off** (cryptomatte вимкнено!)
- arnold_driver_deepexr_alpha_tolerance=0.01
- arnold_driver_deepexr_depth_tolerance=0.01
- node_version=1.1.3

## 16. RENDERSETTINGS — ARNOLD GLOBALS

### rendersettings18 (sh040_env, 609 parms total, ~80+ non-default)

**Frame range / pattern**:
- sample_f1=1001, sample_f2=1077 (from stage)
- primpattern=`/Render/rendersettings`, createprims=off
- camera=`/cams/cam_sh040`, resolution1=1920

**Arnold globals (xn__arnoldglobal*)**:
- enable_progressive_render=on
- **AA_samples=8** (camera samples)
- GI_diffuse_samples=1, GI_specular_samples=1
- GI_diffuse_depth=2, GI_volume_depth=1
- AA_seed=`$F` (per-frame)
- color_family_linear=ACES, color_space_linear=ACEScg
- **bucket_size=16** (default Arnold=64, малий — debug?)
- **ignore_dof=on** (!)
- reportfile=`$HIP/arnold_report.html`
- statsfile=`$HIP/arnold_stats.json`
- profilefile=`$HIP/arnold_profile.json`

**Karma section**: безліч `KarmaRenderSettingsAPI_*` параметрів — швидше за все unused.

## 17. PL_RENDERFARM (Deadline)

### pl_renderfarm18 (типовий)
- f1=$FSTART, f2=$FEND
- job_name=`raid_grand_oak_cinematic_sq010` (computed via `pl_scripts.pl_renderfarm.utils.get_job_name`)
- department=`lighting` (computed via `pl_utils.get_department_name`)
- dl_priority=50, dl_concurrent_tasks=1
- dl_slave_task_limit=on, dl_chunk_size=1
- submit_scene=on, dl_frame_dependent=on
- node_version=1.1.4

## 18. PL_RENDER (output wrapper)

### sh040_env (типовий)
- trange=3 (stage)
- f1=1001, f2=1077, ipr_mode=2
- rendersettings=`/Render/rendersettings`
- render_name=`sh040_env` (`$OS`)
- pl_version=14
- render_folder_info=`$FTRACK_STUDIO_PATH/raid_grand_oak/cinematic/sq010/sh040/render/sh040_env/v014`
- advanced_cryptomatte=on
- node_version=1.2.1

## 19. РЕКОМЕНДАЦІЯ: ПОВНИЙ ДАМП ЧЕРЕЗ PYTHON

Через ліміт MCP я зібрав ~30 з 332 нод. Для повного дампу запусти в Houdini Python Shell:

```python
import hou, json
from pathlib import Path

def parm_diff(node):
    out = {}
    for p in node.parms():
        try:
            tpl = p.parmTemplate()
            default = tpl.defaultValue()
            if isinstance(default, tuple) and len(default) == 1:
                default = default[0]
            v = p.eval()
            unexp = p.unexpandedString() if tpl.dataType() == hou.parmData.String else None
            is_diff = v != default
            if isinstance(v, float) and isinstance(default, (int, float)):
                is_diff = abs(v - default) > 1e-9
            if is_diff or (unexp and unexp != str(default)):
                entry = {"value": v, "default": default}
                if unexp and unexp != str(v):
                    entry["raw"] = unexp
                out[p.name()] = entry
        except Exception as e:
            out[p.name()] = {"error": str(e)}
    return out

def node_dump(node):
    return {
        "path": node.path(),
        "type": node.type().name(),
        "category": node.type().category().name(),
        "bypassed": node.isBypassed() if hasattr(node, 'isBypassed') else False,
        "color": list(node.color().rgb()) if hasattr(node, 'color') else None,
        "inputs": [{"index": i, "path": inp.path()} for i, inp in enumerate(node.inputs()) if inp],
        "outputs": [{"path": c.outputNode().path()} for c in node.outputConnections()] if hasattr(node, 'outputConnections') else [],
        "parms_non_default": parm_diff(node),
    }

def crawl(root_path, output_file):
    root = hou.node(root_path)
    if not root:
        print(f"!!! {root_path} not found")
        return
    data = {"root": root_path, "nodes": []}
    for n in root.children():
        try:
            data["nodes"].append(node_dump(n))
        except Exception as e:
            data["nodes"].append({"path": n.path(), "error": str(e)})
    Path(output_file).write_text(json.dumps(data, indent=2, default=str))
    print(f"Wrote {len(data['nodes'])} nodes to {output_file}")

crawl("/stage", "C:/houdini_mcp_sandbox/stage_dump.json")
crawl("/obj",   "C:/houdini_mcp_sandbox/obj_dump.json")
```

Файли `stage_dump.json` (~ кілька MB) і `obj_dump.json` дадуть повний контекст для CC аналізу.

## 20. ВЖЕ ЗІБРАНІ ДАНІ — REFERENCE TABLE

Перелік нод з детальним diff (30 шт):
- pl_usd_import: sh040, sh080 (sh120 не детально)
- pl_shot_merge: pl_shot_merge1
- reference: reference1
- setvariant: setvariant1, bloodmasks_variants
- prune: prune_unseen, prune_atmo, prune_leaf_mehslight, prune_blodmasks_maces, unprune_main_mace1, hide_chars2
- rendergeometrysettings: blood_masks_subdiv_0, all_matte
- light::2.0: tree, far, edit_tree
- lightlinker: lightlinker2 (empty)
- loky_ArnoldlightFilter: loky_ArnoldlightFilter2 (bypassed)
- materiallibrary: materiallibrary4, create_atmo_mat
- assignmaterial: assignmaterial1
- attribwrangle: attribwrangle3 (wet), scale_leaf
- configureprimitive: configureprimitive2 (atmo)
- configurelayer: configurelayer4
- sublayer: sublayer1 (bypassed), grand_oak
- loky_saveUsd: loky_saveUsd1
- xform: transform1
- editproperties: emission_Off, edit_cam_sh040
- vfx01_crop: vfx01_crop1
- camera: test_cam1
- sopcreate: leaf_geo_light, atmo
- pl_aovs: pl_aovs8
- rendersettings: rendersettings18 (sh040_env, deep dive)
- pl_renderfarm: pl_renderfarm18
- pl_render: sh040_env

## ПРОПОНОВАНИЙ NEXT STEP ДЛЯ CC

1. **Запустити Python скрипт §19** — дамп всіх 332+4 нод у JSON.
2. **Завантажити обидва JSON** + цей audit як контекст.
3. **Найперше** — diff `rendersettings*` між шотами (sh040 vs sh080 vs sh120) і пасами (env vs chars vs atmo).
4. **Друге** — інвентаризація light AOV groups: `for each light → xn__primvarsarnoldaov_t3ag`.
5. **Третє** — мапа prune patterns: `[path, primpattern1, bypassed]` for all 25+ prune-ів.
6. **Не активувати bypassed ноди** без узгодження з Сашею. Це навмисно вимкнені feature flags.
7. **/obj камери** — окрема перевірка вручну в Houdini UI (MCP плагін не вміє ObjNode).

## END OF AUDIT

---

## [bug] houdini-mcp плагін: ObjNode crash + NoneType errors + max_nodes/tokens обмеження
_2026-05-17T15:43:11_
> BUG 1 resolved 2026-05-17 (72f8490) — wrapped every top-level get_node_info field in `_safe()`, gated `isBypassed` behind `hasattr`. /obj/* нодами тепер мають інспектуватись.
> BUG 2 still open — defensive serialization didn't catch root cause. Plugin now returns `traceback` in error response (72f8490). Next time CD hits NoneType on /stage/moon etc., the traceback will pinpoint the line.
> Token observations: 4 feature ideas added to BACKLOG (`get_node_parm_names_only`, `include_raw=false`, `parm_prefix_filter`, `recursive=True`). Workaround: `scripts/dump_scene.py` for offline full-scene dumps.

# Bugs/limitations виявлені у houdini-mcp плагіні під час аудиту /stage та /obj

## BUG 1: get_node_info crashes on ObjNode
**Repro**: `houdini:get_node_info(path="/obj/cam_sh040")` або `/obj/null1`
**Error**: `'ObjNode' object has no attribute 'isBypassed'`
**Impact**: всі /obj ноди недоступні через MCP. Не вдалось проаналізувати:
- /obj/cam_sh040, /obj/cam_sh080, /obj/cam_sh120 (всі lopimportcam)
- /obj/null1

**Suspected fix**: ObjNode використовує `.isObjectDisplayed()` замість `.isBypassed()`. Треба `hasattr` гард у плагіні, або conditional branch для category=Object.

## BUG 2: get_node_info returns 'NoneType' error для деяких /stage нод
**Repro**: `houdini:get_node_info(path="/stage/moon")`, `/stage/hdri`, `/stage/tree_decoy`, `/stage/NO_PROXY_TEX1`, `/stage/NO_PROXY_TEX2`
**Error**: `'NoneType' object has no attribute 'name'`
**Hypothesis**: ймовірно ці ноди мають input/output connection що повертає None (notused channel), або internal sub-network reference куди плагін намагається залізти.

**Suspected fix**: захист на тому місці у плагіні де він ітерує по `node.inputs()` або `node.outputConnections()` без перевірки на None.

## OBSERVATION: ліміт max_nodes у get_scene_info
get_scene_info(max_nodes=5000) повернув 332 топ-level /stage ноди + 4 /obj. Працює, але total `node_count=2922` означає що ВСЕРЕДИНІ топ-level нод є ще ~2586 sub-нод (внутрішні subnetworks loky_*, pl_*). MCP не дає швидкого способу їх обійти — треба було б рекурсивний crawl.

**Suggestion**: додати параметр `recursive=True` або новий tool `houdini:get_node_tree(path, depth=N)` що повертає flatten список з підмережами.

## OBSERVATION: токени на nodes з великими параметрами
Деякі ноди (rendersettings: 609 параметрів, light::2.0: 280 параметрів) повертають великий JSON навіть з only_non_default=true (бо ~80 non-default з 609). На 332 нодах це 500K+ токенів — нереально для одного циклу аналізу.

**Suggestion**: 
- Можливість запросити тільки список non-default parm names (без values)
- Параметр `include_raw=false` щоб виключити raw_value/expressions для economy
- Можливість фільтрувати parms за prefix-pattern (наприклад тільки `xn__arnoldglobal*`)

## WORKAROUND для повного дампу
Python скрипт що працює напряму в hou.session, оминає всі MCP обмеження. Зафорвардив у Part 2/2 аудиту. Дає JSON для /stage і /obj за ~30 секунд.

---

## [observation] [avp_assemble] Scene audit — Part 1/3: META + topology
_2026-05-17T16:18:04_
> consumed 2026-05-17 — vocabulary absorbed (rolling-shutter cameras, ~150 light::2.0 count, fetch/timeshift/Light_Blocker types). Anti-patterns recorded; cleanup is Sashok's call, not infra TODO.

# Scene audit: avp_assemble.hip (1/3)

## META
- **File**: `C:/houdini_mcp_sandbox/avp_assemble.hip`
- **Project**: AvP (Alien vs Predator) — sequence sq010
- **Shots**: sh270, sh280, sh290, sh300, sh310 (+ sh291 secondary import)
- **Frame range**: 1001-1080 @ 24fps
- **Renderer**: Arnold (htoa)
- **Color**: ACEScg (linear family ACES)
- **Resolution baseline**: 1920×1920 (square — VR/dome? worth verifying)
- **Total nodes**: 28,156 (most inside subnetworks/HDAs)
- **Top-level /stage**: ~620 nodes
- **Top-level /obj**: 7 nodes (5 cams + 2 geo: paper, glass)
- **Storage paths**: `//loky.plarium.local/project/_pl/raid_ap/cinematic/sq010/`
- **Studio**: Plarium (ftrack pipeline — `$FTRACK_ROOT_PATH`, `$FTRACK_STUDIO_PATH`)

## High-level topology (per-shot pattern)
Each shot has parallel pipelines, fed from `pl_usd_import → pl_shot_merge1`:

```
pl_usd_import (sh270/280/290/300/310)
    → pl_shot_merge1 → pl_shot_mark (per-shot)
        → variants (setvariant: chars_normal_tex, chars_proxy_tex, env_texture_*, capsule_damaged, ...)
        → prune stacks (deactivate-based, primpattern-driven)
        → rendergeometrysettings (matte/AOV/subdiv per pass)
        → lights (light::2.0, ~150+ instances) + editproperties + lightlinker
        → pl_aovs → rendersettings → pl_render (Arnold pass)
        → pl_renderfarm (job submission HDA)
```

## Node-type inventory (top-level /stage, ~620 nodes)
Counted from get_scene_info:

| Type                          | Count | Role                                          |
|-------------------------------|-------|-----------------------------------------------|
| `light::2.0`                  | ~150+ | All lighting (incl. evac/screen/capsule sets) |
| `prune`                       | ~85   | Per-pass selective enabling                   |
| `pl_render`                   | ~30   | Render-pass HDAs (bg/fg/main/atmo/sparks/etc) |
| `rendersettings`              | ~35   | Per-pass Arnold settings                      |
| `rendergeometrysettings`      | ~20   | Matte/subdiv/AOV per geo                      |
| `pl_aovs`                     | ~30   | AOV setup per pass                            |
| `editproperties`              | ~40   | Feature flags (no_emision, walls_emission_off, etc.) |
| `pl_renderfarm`               | ~14   | Farm submission                               |
| `setvariant`                  | ~15   | Variant switching (proxy/normal/damaged)      |
| `pl_shot_mark` / `pl_shot_edit` | ~15 | Shot boundary markers                         |
| `sublayer`                    | ~10   | Lookdev/asset layer injection                 |
| `sopcreate` (`grid*`, `cube*`)| ~14   | Light blockers (manual geo)                   |
| `Light_Blocker::12`           | 8     | HDA-based blockers                            |
| `materiallibrary` / `assignmaterial` | ~20 | Material assignments                      |
| `pl_usd_import`               | 6     | Shot USD imports                              |
| `pl_shot_output` / `pl_usd_rop` | 3   | USD output / assembly                         |
| `instancer` (GLASS*)          | 4     | Glass shatter instancers per shot             |
| `loky_*` HDAs                 | ~12   | Studio HDAs (ImportGeo, saveComponent, ArnoldlightFilter, XeroxSolarisModify, saveUsd, ImportVolume) |
| `fetch`                       | 16    | Cross-network references                      |
| `timeshift`                   | 7     | Time-offsetting (evac lights animation)       |
| `reference::2.0`              | ~8    | USD references (matte payloads, glass, fog)   |
| `null`                        | ~15   | Network navigation markers (SH*_SHOT_OUT, OUT_FOR_GLASS_*, FAST_PREVIEW, IN, OUT) |

## /obj contents (working)
- `/obj/sh270_cam` ... `/obj/sh310_cam` — 5 shot cameras (resolution 1920×1920, focal 40mm, shutter 0.4, custom rolling shutter ramp)
- `/obj/paper` (geo)
- `/obj/glass` (geo)

Cameras have keyframed transforms (bezier()). Arnold rolling-shutter expressions: `ar_rolling_shutter_duration = 1/1080`, `ar_mb_shutter_length = ch("shutter")`, custom 4-point shutter ramp.

Continued in Part 2/3 (patterns + per-category diff).

---

## [observation] [avp_assemble] Scene audit — Part 2/3: patterns + diff samples
_2026-05-17T16:19:21_
> consumed 2026-05-17 — concrete USD-encoded parm names captured. 3 added to SAFE_PARMS (see resolution on bug entry below).

# Scene audit: avp_assemble.hip (2/3) — Patterns + Diff

## Key configured values (samples)

### rendersettings (Arnold) — beauty pass baseline
Verified from `/stage/rendersettings1` (516 parm slots, ~70 non-default):
- `AA_samples = 7` (override)
- `bucket_size = 32` (override; default 64 — **smaller buckets = faster final tile but more overhead**)
- `enable_progressive_render = on` (overridden)
- `auto_generate_tx = off` (overridden — assumes pre-generated .tx)
- `AA_seed = $F` (per-frame seed — denoise-friendly)
- Color: `ACEScg` (linear) / `ACES` family
- Resolution: 1920×N where N = `computeResolutionParameter(True, False)` (auto-aspect from camera)
- Data window NDC: `[-0.003, -0.003, 1.003, 1.003]` (slight overscan)
- Arnold report/stats/profile paths all set to `$HIP/arnold_*.{html,json}` — overwritten per-render, **not per-shot/pass**. Could collide across simultaneous farm jobs.

### light::2.0 (e.g. `char_key`) — typical setup
- `lighttype = UsdLuxDiskLight`
- `lookatenable = on` with explicit lookatpos (so transforms make sense)
- `exposure = 1.72` (positive, stop-based)
- `primvars:arnold:aov = "char_key"` — **AOV light group per-light is the pattern**. Light groups will be exposed in the comp as separate AOVs.
- `arnoldaov_control = set` (override flag pattern — every Arnold-specific override has a sister `*_control` parm; CC must replicate this whitelist when scripting)

### rendergeometrysettings (e.g. `all_matte`) — matte pass
- `primpattern = /chars/* /env/* /props/*`
- `primvars:arnold:matte = on` (override)
- Used to flip the whole scene to matte for holdouts.

### pl_render (HDA wrapper) — render submission
Per-shot frame ranges (verified from `bg_270`):
- sh270 bg: 1001-1021 (20 frames)
- All cameras explicitly overridden: `override_camera = /cams/cam_sh270` etc.
- Path template: `$FTRACK_STUDIO_PATH/raid_ap/cinematic/sq010/<shot>/render/<name>/v<NNN>`
- `pl_version = 13`, `node_version = 1.2.1`
- `advanced_cryptomatte = on` everywhere

### prune (selective-enabling stack)
Two variants found:
1. **`prune` (default behavior)** — `method=deactivate`, `primpattern` lists explicit USD prim paths. E.g. `prune_invis_lights` deactivates 32 light prims (`/lights/lght_evac_*`, `/lights/light_aqr_sign_*`, `/lights/sky_blck_*`).
2. **`UN-prune` pattern** — `arbiter_hair_UNprune`: `prune = 0` + `primpattern = /chars/arbiter_space_suit/geo/hair`. Re-activates a previously pruned prim. Used as compositional override.

### Camera (/obj/*_cam)
- Square 1920×1920, focal 40, near 0.02
- Shutter 0.4 s, rolling-shutter duration 1/1080 (per-line, 1080 lines @ shutter speed)
- Custom 4-point shutter curve ramp (trapezoidal: 0→1 over 10%, hold, 1→0 over last 10%) — non-default trapezoid for realistic motion blur

---

## Anti-patterns / red flags

### 1. Massive rendersettings duplication (~35 instances)
`rendersettings1` through `rendersettings31` + `WIP/WIP1..8`, `draft23/24`. Some have ad-hoc names like `WIP`, `WIP1..8`, `draft23`, `draft24`, `rendersettings_edit11`. **Heuristic:** these were forked per-pass instead of inherited from a single base. CC should consider consolidating to a master + override-style children if scaling further. NOT auto-touching — confirm with Sashok first.

### 2. AOV nodes hanging unattached
`pl_aovs8` is **bypassed** AND has no inputs/outputs (`inputs: []`, `outputs: []`). Likely orphaned from refactor. Several `pl_aovs*` nodes (8..41) — check if all wired. Sample candidates for cleanup.

### 3. Naming drift
Notable mid-stack names:
- `prune_scattqer1` — typo for `prune_scatter` (already present elsewhere)
- `prune_zheka_scatter_off` — personal name ("zheka") in node label → bad for handoff
- `glass_on_the_floor` (prune) — works but ad-hoc
- `TEMP_PRUNE` — leftover temp marker
- `arbiter_hair_UNprune` vs `arbiter_hair_prune` — sibling naming OK, but UPPERCASE inconsistent
- Multiple `empty_light*` (5 nodes) — purpose unclear without inspection
- `sparks_ffg_270` — likely typo for `sparks_fg_270`

### 4. WIP / draft nodes in production graph
9 `WIP*` and 2 `draft*` rendersettings nodes are wired in. Need to confirm with Sashok whether these are deliberate "feature flags" or stale forks. NOT bypassed → they may be active for some pl_render outputs.

### 5. Many `editproperties` stacked feature-flag style
~12 instances of `no_emision*`, `walls_emission_off*`, `sparks_geolight_increase*`, `edit_standard_surface*`. Pattern: localized material/property overrides per pass. These ARE the legitimate per-pass override pattern in Solaris — flag if any are bypassed and forgotten.

### 6. Light count is high
~150+ `light::2.0` nodes at /stage top level. Many follow `light_screen_*` (17 letters A..O), `light_capsule_*` (~15), `lght_evac_*` (~25), `light_up_table_p*` (~25), `light_GI_*` family, etc. Most likely necessary (full set lighting), but Light_Blocker stack (8 blockers + 5 grid/cube SOPs for blocker geo) is sizeable — verify all are referenced from at least one lightlinker.

### 7. `lightlinker` nodes (8 instances): lightlinker1..8
Each one defines which lights affect which prims. With 150+ lights and 8 linkers, hard to audit by eye — flag as a domain for a dedicated audit if any pass renders wrong.

### 8. Arnold report file collision risk
All 35 rendersettings nodes likely write to `$HIP/arnold_report.html`, `$HIP/arnold_stats.json`, `$HIP/arnold_profile.json`. Concurrent farm renders WILL overwrite each other's stats. Worth parameterizing per-pass.

---

## Bypassed inventory (sampled)
Only `pl_aovs8` confirmed bypassed in the sampling pass. **Full bypass scan requires the Python dump (Part 3).** Per Sashok's rule: bypassed nodes are NOT activated; documented only.

## Open questions (need Sashok input)
1. **WIP / draft / WIP1..8 rendersettings** — feature flags or stale forks? OK to consolidate?
2. **1920×1920** square camera resolution — VR? Crop? Intentional?
3. **`pl_aovs8`** and other orphan AOV nodes — confirmed dead?
4. **Arnold report path collision** — parameterize per-pass or acceptable?
5. **`prune_scattqer1` / `prune_zheka_scatter_off` / `TEMP_PRUNE`** — safe to rename for handoff?
6. **`empty_light` × 5** — placeholder lights or unused?

Continued in Part 3/3 (Python dump script + recommended next step + plugin bug report).

---

## [observation] [avp_assemble] Scene audit — Part 3/3: dump script + next steps
_2026-05-17T16:20:13_
> consumed 2026-05-17 — improved dump script noted; the earlier `scripts/dump_scene.py` covers the same shape, keeping single canonical version. If we hit cases where the v2 features (`comment`, `has_keyframes`, parm-tuple aware default detection) matter, will fork.

# Scene audit: avp_assemble.hip (3/3) — Dump script + recommendations

## Python dump script (run in Houdini Python Shell)

This produces the FULL diff (all top-level /stage + /obj nodes, only non-default parms, with raw expressions). Sashok runs this once in the live session — output is `C:/houdini_mcp_sandbox/avp_assemble_dump.json`.

```python
import hou, json, os

OUT = "C:/houdini_mcp_sandbox/avp_assemble_dump.json"
CONTEXTS = ["/stage", "/obj"]

def serialize_value(v):
    """Best-effort JSON-safe value."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (tuple, list)):
        return [serialize_value(x) for x in v]
    return repr(v)

def parm_diff(parm):
    """Return (value, raw, type) only if non-default; None otherwise."""
    try:
        tpl = parm.parmTemplate()
        default_vals = tpl.defaultValue() if hasattr(tpl, "defaultValue") else None
        cur = parm.eval()
        raw = parm.rawValue() if hasattr(parm, "rawValue") else parm.unexpandedString() if hasattr(parm, "unexpandedString") else str(cur)
        # Compare against default; if default is tuple, take element 0
        default = default_vals[0] if isinstance(default_vals, (tuple, list)) and default_vals else default_vals
        is_default = (cur == default) and (str(raw) == str(default))
        # Always include expressions even if they evaluate to default
        has_expr = parm.keyframes() or (raw and str(raw) != str(cur))
        if is_default and not has_expr:
            return None
        return {
            "value": serialize_value(cur),
            "raw": str(raw) if raw is not None else None,
            "type": tpl.type().name() if tpl else "Unknown",
            "has_keyframes": bool(parm.keyframes()),
        }
    except Exception as e:
        return {"error": str(e)}

def node_dump(node):
    parms = {}
    for p in node.parms():
        d = parm_diff(p)
        if d is not None:
            parms[p.name()] = d
    inputs = [(c.name(), c.path(), c.type().name()) for c in node.inputs() if c]
    outputs = [(c.name(), c.path(), c.type().name()) for c in node.outputs() if c]
    return {
        "path": node.path(),
        "type": node.type().name(),
        "is_bypassed": node.isBypassed() if hasattr(node, "isBypassed") else None,
        "is_displayed": node.isDisplayFlagSet() if hasattr(node, "isDisplayFlagSet") else None,
        "color": list(node.color().rgb()) if hasattr(node, "color") else None,
        "position": list(node.position()) if hasattr(node, "position") else None,
        "comment": node.comment() if hasattr(node, "comment") else "",
        "parms": parms,
        "inputs": inputs,
        "outputs": outputs,
    }

result = {"file": hou.hipFile.path(), "contexts": {}}
for ctx_path in CONTEXTS:
    ctx = hou.node(ctx_path)
    if not ctx:
        result["contexts"][ctx_path] = {"error": "not found"}
        continue
    nodes = ctx.children()  # top-level only; recurse manually if needed
    result["contexts"][ctx_path] = {n.name(): node_dump(n) for n in nodes}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print("Dumped {} nodes to {}".format(
    sum(len(v) for v in result["contexts"].values() if isinstance(v, dict) and "error" not in v),
    OUT
))
```

### Notes on the script
- Top-level only by default. To recurse into HDAs/subnetworks, replace `ctx.children()` with `ctx.allSubChildren()` — but this will balloon to ~28K nodes; do it only for targeted subtrees.
- "Default" detection is heuristic — Houdini parm templates don't always expose the per-Arnold-override `_control` pair cleanly. The `has_expr` fallback ensures we never lose expressions.
- For a deep dive of one subnetwork only, pass it as a CONTEXT (e.g. `/stage/pl_renderfarm2`).

## Recommended next step for CC

**Priority order:**
1. **Run the dump** (Sashok, manually in Houdini) → `avp_assemble_dump.json`
2. **Answer the 6 open questions in Part 2** so cleanup scope is bounded
3. **If consolidation is approved**: CC can read the JSON, group rendersettings by overrides, propose a merged hierarchy
4. **If just for handoff archive**: JSON + the 3-part Markdown audit is the deliverable
5. **Light audit**: separate sub-task — generate a CSV of (light, exposure, type, AOV group, lightlinker membership) for a sanity pass

## Plugin bug report (separate forward — see bug category)
- `execute_houdini_code` — disabled in dispatcher but hangs for 4 minutes before timing out instead of returning a quick "Unknown command type"
- `read_cc_inbox` — also hung 4 minutes during this session (intermittent; subsequent `get_node_info` calls worked fine, so plugin recovered)

---

## Files for CC to consume
- `cc_inbox.md` — these 3 parts
- (after dump) `C:/houdini_mcp_sandbox/avp_assemble_dump.json` — full structured diff

## What was NOT done (and why)
- ❌ Recursed into 28K internal nodes — too noisy; covered by dump script if needed
- ❌ Touched `/obj` write operations — only read (plugin appears stable on /obj reads anyway, contrary to earlier session notes)
- ❌ Activated bypassed nodes — per Sashok's rule (audit only)
- ❌ Light-linker membership graph — large enough to be its own task

---

## [bug] [mcp-plugin] Two tools hang 4 min on disabled/error path
_2026-05-17T16:21:19_
> BUG 1 (`execute_houdini_code` 4-min hang) resolved 2026-05-17 — bridge wrapper now short-circuits and returns immediately, no socket round-trip. The disabled-path message instructs CD to use narrow tools or forward_to_cc a request.
> BUG 2 (`read_cc_inbox` intermittent hang) open — hypothesis: it was tail-blocked by BUG 1. Now that BUG 1 returns fast, this should not recur. Will revisit if seen again. Tracked in BACKLOG.
> SAFE_PARMS suggestions: 3 added (light `xn__inputsexposure_vya`, Arnold globals `xn__arnoldglobalbucket_size_jebg`, `xn__arnoldglobalAA_samples_wcbg`). NOT added: `is_bypassed` (node flag, not parm — would need separate `set_node_flag` tool); `primpattern1` (dangerous per CD's own note). Tracked in BACKLOG to add more `xn__*` parms as real scenes surface them.

# Plugin bugs found during avp_assemble audit session

## Bug 1: `execute_houdini_code` hangs 4 min instead of fast-fail

**Tool**: `houdini:execute_houdini_code`
**Tool description claims**: "currently disabled in the plugin dispatcher for security; returns 'Unknown command type'"
**Actual behavior**: hangs for ~4 minutes, then MCP client returns "No result received from the Claude Desktop app after waiting 4 minutes"

**Repro**:
```python
houdini:execute_houdini_code(code="print('ping')")
```

**Expected**: immediate error response "Unknown command type" (or a clear "disabled" message)
**Actual**: 4-minute hang, then client-side timeout

**Suspected fix**:
- In the plugin dispatcher, check the command type FIRST and return early with the "Unknown command type" / "disabled" payload synchronously
- If the dispatcher is fine, then the issue is on the server-side handler — there's probably no handler registered for this command, so the request hits a wait-loop / unawaited future

**Impact**: medium — wastes 4 min of session time per invocation, also confuses Claude/CC into thinking the plugin is dead

---

## Bug 2: `read_cc_inbox` intermittent 4-min hang

**Tool**: `houdini:read_cc_inbox`
**Behavior**: in this session it timed out at exactly 4 minutes, identical signature to Bug 1
**Context**: it was called RIGHT AFTER `execute_houdini_code` had its 4-min hang. The next `get_node_info` (on /stage/sh270) worked fine.

**Hypothesis**: the previous `execute_houdini_code` hang left the dispatcher in a bad state for one more request. Could be:
- (a) lingering future / event-loop block carrying over
- (b) the inbox file lock held by something
- (c) plugin state machine got desynced after the disabled-command timeout

**Repro suggestion**: try to reproduce by calling `execute_houdini_code` first, then `read_cc_inbox` immediately. If it consistently reproduces, the link is real.

**Impact**: low-medium — non-deterministic; subsequent calls worked.

---

## Notes
- All other tools used in this session worked cleanly: `get_scene_info` (5000 max_nodes), `get_node_info` × 5 (rendersettings, prune, light::2.0, pl_render, rendergeometrysettings, pl_aovs, prune-UN), `forward_to_cc` × 3
- `/obj` read works fine (sh270_cam returned 124 parms, 25 non-default). Earlier session note about `/obj` being a plugin bug may have been incorrect OR may apply only to specific node types (not `cam`)

## Suggested SAFE_PARMS whitelist additions (from this session)
For `set_node_parameter`, currently rejected parms that would be useful for audit-driven tweaks:
- `is_bypassed` (read-only via flag, but write would help disabling stale forks)
- `xn__inputsexposure_vya` (light exposure — Arnold light)
- `xn__arnoldglobalbucket_size_jebg` (Arnold bucket size — non-trivial perf knob)
- `xn__arnoldglobalAA_samples_wcbg` (AA samples)
- `primpattern1` (prune pattern — but DANGEROUS, only with explicit per-call OK)

(Don't add these blindly — `primpattern1` in particular can break a render if mistyped. Whitelist with judgment.)

---

## [bug] viewport_snapshot повертає "unsupported image format" — bridge incorrectly encodes image response
_2026-05-17T16:43:16_
> resolved 2026-05-17 — CD's hypothesis #1 was correct in spirit but wrong-direction. Houdini saves `.jpg`, plugin set `format="jpg"`, my `_result_to_image` had `if fmt == "jpeg": fmt = "jpg"` — inverted mapping. FastMCP builds `image/{format}` literally, so we ended up with `image/jpg` which is not a valid MIME type (canonical is `image/jpeg`). Inverted the mapping (`jpg → jpeg`) and added a guard rejecting non-inline formats (gif/webp allowed; bmp/exr/etc explicitly rejected with a clear error mentioning the file path on pc137).

## Симптом
Виклик `houdini:viewport_snapshot()` без аргументів (дефолтний `render_path=C:/temp/`) призводить до помилки на стороні MCP-клієнта (Claude Desktop):

```
The tool returned an image in an unsupported format.
```

## Що працює
- Плагін на pc137 СВОЮ ЧАСТИНУ виконав: файл скріншоту реально лежить у `C:/temp/` (підтвердив Саша візуально).
- Це значить баг — НЕ у Houdini-side рендері. Баг у тому, як **bridge (`houdini_mcp_server.py`) повертає image у MCP response**.

## Гіпотези (від найімовірнішої)
1. **MIME-type mismatch**: bridge захардкодив `image/png` у `ImageContent.mimeType`, а Houdini зберіг файл як `.jpg` / `.bmp` / `.exr` / щось інше. MCP client відмовляється парсити.
2. **Не base64-енкодить**: bridge читає файл і пхає raw bytes без base64 у `data` field. MCP protocol очікує base64 рядок.
3. **Неправильний content block type**: повертається `text` block з шляхом замість `image` block з контентом.
4. **Розширення файлу не співпадає з реальним форматом**: плагін зберіг наприклад `.png`, але всередині JPEG (або навпаки) — клієнт детектить magic bytes і відмовляє.

## Запропонована діагностика (для CC)

### Крок 1: подивитись що реально лежить у C:/temp/
```bash
ssh pc137 "powershell -c 'Get-ChildItem C:/temp/ -File | Sort LastWriteTime -Desc | Select -First 5 | Format-List Name,Length,Extension,LastWriteTime'"
```
Окремо magic bytes першого файлу:
```bash
ssh pc137 "powershell -c '$f=Get-ChildItem C:/temp/ -File | Sort LastWriteTime -Desc | Select -First 1; Format-Hex -Path $f.FullName -Count 16'"
```

### Крок 2: грепнути bridge — як він повертає response для viewport_snapshot
```bash
grep -n -B2 -A 40 "viewport_snapshot\|render_single_view\|ImageContent\|image/" houdini_mcp_server.py
```
Особливо шукати:
- Чи там є `ImageContent(type="image", data=..., mimeType=...)`
- Чи `data` обгорнутий у `base64.b64encode(...).decode()`
- Чи `mimeType` детектиться з розширення файлу або захардкоджений

### Крок 3: грепнути плагін — як він обирає формат збереження
```bash
grep -n -B2 -A 30 "def.*viewport_snapshot\|def.*render_single_view\|saveFrame\|saveImage" plugin/server.py
```

## Очікувана причина
~70% імовірність — плагін зберігає `.jpg` (Houdini-дефолт для OpenGL preview через `hou.GeometryViewport.saveViewport()` або similar), а bridge каже клієнту `image/png`. MCP client (Claude Desktop) перевіряє magic bytes і відмовляє.

## Запропонований фікс
- Bridge має детектити mime з реального розширення файлу (`pathlib.Path(path).suffix` → mapping до `image/{png,jpeg,bmp,webp}`).
- АБО: фіксовано форсити PNG на стороні плагіна (у `saveFrame()` явно вказувати `.png`-розширення).

## Як я туди прийшов
1. CD: `get_project_context` → `viewport_snapshot()` без аргументів
2. Bridge повернув error: `The tool returned an image in an unsupported format.`
3. Саша підтвердив що файл реально згенерований у `C:/temp/` → плагін OK → баг у транспорті.
4. Зробив stop і запитав CC через інбокс замість дампу гіпотез у чат (CD-rule).

## Пов'язане
- Не блокує сесію — є `get_scene_info` / `get_node_info` як текстова альтернатива.
- Але всі vision-tools (`render_single_view`, `render_quad_views`, `render_specific_camera`) ймовірно мають той самий баг — рекомендую перевірити їх після фіксу viewport_snapshot.

---
