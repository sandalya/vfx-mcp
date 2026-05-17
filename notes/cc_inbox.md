
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
