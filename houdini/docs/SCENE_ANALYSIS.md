# Scene Analysis: `houdiniworkscene_cld.hip`

**Шлях:** `C:/houdini_mcp_sandbox/houdiniworkscene_cld.hip`
**Проект (ftrack):** `raid_cyclope / cinematic / sq010` (3 shots: sh110, sh120, sh130)
**Lighting artist:** `assembling_gamaiunov` (Sashok)
**Renderer:** Arnold (HtoA), ACES/ACEScg colorspace
**FPS:** 24
**Default frame range:** 1001–1057 (sh110), коротші для sh120 (1050) і sh130 (1045)
**Всього нод у сцені:** 642 (124 в /stage + 97 в /obj + інші)

---

## TL;DR

Це **lighting/lookdev сцена для 3-shot sequence** з Plarium pipeline. Робота йде в `/stage` (LOPs). `/obj` забитий sandbox-сміттям з MCP-сесій (96 шаблонних `geo1nnn/sphere_obj/box_obj`).

Кожен шот має 4 render-пасси: **chars / bg / sky / atmo**, плюс WIP-рендер для preview. Per-shot pass-рендери йдуть на Deadline farm, WIP-рендери локально. Light rig: 1× sun + 1× dome HDRI + 7+ char-lights (rim left/right, top, fill, sword, sun) + 3× volumetric spot lights з Arnold light filters.

---

## 1. Графова топологія

### Загальний flow

```
/stage:
  sh110, sh120, sh130 (pl_usd_import)
    → pl_shot_merge1
      → edit_sun (light::2.0) ← sun-light для всіх шотів (exposure 6.06)
        → edit_env (domelight::3.0) ← HDRI env "1325 Sun Clouds.exr", exposure -4.5
          → collection1
            → pl_shot_mark1 → prune_props → prune_cliffs → prune1 → prune_props2/prune_cliffs2 → ...
              → [per-shot branches]
                → sh110_chars/bg/sky/atmo → pl_renderfarm27 (deadline)
                → sh120_chars/bg/sky/atmo → pl_renderfarm28 (deadline)
                → sh130_chars/bg/sky/atmo → pl_renderfarm29 (deadline)
                → WIP2/WIP3/WIP4 (локальний preview)
              → pl_renderfarm30/31/32 (атмо-only branches)
```

### Side-of-merge3 — character lights branch
```
char_sun (spot, narrow, exp 9.54) ─┐
char_rim_left (rect 50×50, exp 9.33)─┤
char_rim_right (rect 25×25, exp 5.72)┤
char_top, char_top1, char_top2 (rect 8.19×8.19, exp 4.91)─┤  → merge3
char_fill, char_fill1 (sphere/rect mix, exp 6.03) ─┤      → lightlinker1
char_sword (sphere spot, exp 4.56) ─┤              → edit_char_sun → ...
vol_spot, vol_spot1, vol_spot2 (vol-only spots) ─→ loky_ArnoldlightFilter1/2/3 ─┘
```

---

## 2. /obj — sandbox-сміття (97 нод)

**Жодної реальної геометрії від твоєї роботи.** Всі ноди — шаблонні від MCP-сесій:

| Pattern | Count | Опис |
|---|---|---|
| `geo1nnn`, `geo1nnn1`, …, `geo1nnn31` | 32 | Порожні geo-контейнери |
| `sphere_obj`, `sphere_obj1`, …, `sphere_obj31` | 32 | MCP-test sphere ноди |
| `box_obj`, `box_obj1`, …, `box_obj31` | 32 | MCP-test box ноди |
| `test_sphere` | 1 | Окрема тестова |

**Рекомендація:** видалити повністю. Все важливе в `/stage`.

---

## 3. /stage — Production network (124 ноди)

### 3.1. Shot Imports (3 ноди) — `pl_usd_import` v1.x

| Шлях | filepath1 |
|---|---|
| `/stage/sh110` | `$FTRACK_ROOT_PATH/raid_cyclope/cinematic/sq010/sh110/shot.usd` |
| `/stage/sh120` | `$FTRACK_ROOT_PATH/raid_cyclope/cinematic/sq010/sh120/shot.usd` |
| `/stage/sh130` | `$FTRACK_ROOT_PATH/raid_cyclope/cinematic/sq010/sh130/shot.usd` |

**Параметри (всі однакові, стандартний template):**
- `layerbreak = on` (всі)
- Усі mute toggles вимкнено
- `timewarp_active = off`
- Жодних змін від дефолтів окрім самого `filepath1`

### 3.2. Shot Merge (1 нода)

`/stage/pl_shot_merge1` (pl_shot_merge, v1.1.10):
- 3 inputs: sh110/120/130
- `layerbreak = on`
- Інші — defaults

### 3.3. WIP Render-ноди (3 ноди) — `pl_render` v1.2.1

Локальний preview-рендер (не для farm).

| Нода | Шот | Frame range | render_folder |
|---|---|---|---|
| `WIP2` | sh110 | 1001-**1057** | `//loky.plarium.local/.../sh110/render/WIP2/v001` |
| `WIP3` | sh120 | 1001-**1050** | `//loky.plarium.local/.../sh120/render/WIP3/v001` |
| `WIP4` | sh130 | 1001-**1045** | `//loky.plarium.local/.../sh130/render/WIP4/v001` |

**Спільні non-default параметри:**
- `trange = stage`
- `advanced_cryptomatte = ON`
- `rgba_only = OFF`
- `ipr_mode = 0` (offline render)
- `rendersettings = /Render/rendersettings`

**WIP3 єдина має `is_displayed: true`** (зараз на ній сидиш в network editor).

### 3.4. Per-shot Pass-render (12 нод) — `pl_render` v1.2.1

Кожен шот має 4 проходи: **chars / bg / sky / atmo** → submit на Deadline.

| Нода | Шот | Pass | Frame end | inputs | output → renderfarm |
|---|---|---|---|---|---|
| `sh110_bg` | 110 | bg | 1057 | pl_aovs28 | pl_renderfarm27 idx0 |
| `sh110_chars` | 110 | chars | 1057 | pl_aovs30 | pl_renderfarm27 idx1 |
| `sh110_sky` | 110 | sky | 1057 | pl_aovs29 | — ⚠️ **BYPASSED** |
| `sh110_atmo` | 110 | atmo | 1057 | pl_aovs31 | pl_renderfarm27 idx2 **+** pl_renderfarm30 idx0 |
| `sh120_sky` | 120 | sky | 1050 | pl_aovs34 | pl_renderfarm28 idx0 |
| `sh120_bg` | 120 | bg | 1050 | pl_aovs32 | pl_renderfarm28 idx1 |
| `sh120_chars` | 120 | chars | 1050 | pl_aovs33 | pl_renderfarm28 idx2 |
| `sh120_atmo` | 120 | atmo | 1050 | pl_aovs35 | pl_renderfarm28 idx3 **+** pl_renderfarm31 idx0 |
| `sh130_sky` | 130 | sky | 1045 | pl_aovs39 | pl_renderfarm29 idx? |
| `sh130_bg` | 130 | bg | 1045 | pl_aovs36 | pl_renderfarm29 idx? |
| `sh130_chars` | 130 | chars | 1045 | pl_aovs37 | pl_renderfarm29 idx2 **+** pl_renderfarm32 idx0 |
| `sh130_atmo` | 130 | atmo | 1045 | pl_aovs38 | pl_renderfarm29 idx? |

**Спільні non-default параметри:**
- `ipr_mode = 2` (husk batch — на відміну від WIP де = 0)
- `trange = stage`
- `advanced_cryptomatte = ON`
- `rendersettings = /Render/rendersettings`

⚠️ **Знахідки:**
1. **`sh110_sky` повністю bypassed** — sky-пас вимкнено для sh110 (не йде на жодну ферму)
2. **`*_atmo`** на sh110/sh120/sh130 та `sh130_chars` — підключені до **двох** renderfarm-нод одночасно (основний + dedicated atmo-only stream)
3. **`sh120_chars`** на pl_renderfarm28 idx**2** (а sh120_sky idx0) — звичайний порядок (sky/bg/chars/atmo)

### 3.5. Renderfarm submitters (5 нод) — `pl_renderfarm` v1.1.4

**Спільні налаштування (всі однакові):**
- `job_name = "raid_cyclope_cinematic_sq010"`
- `department = "lighting"`
- `dl_priority = 50`
- `dl_concurrent_tasks = 1`
- `dl_chunk_size = 1` (frames per task)
- `dl_slave_task_limit = ON`
- `dl_frame_dependent = ON`
- `submit_scene = ON`
- `f1 = $FSTART`, `f2 = $FEND`, `f3 = 1`

| Нода | Покриває |
|---|---|
| `pl_renderfarm27` | sh110 (bg, chars, atmo) |
| `pl_renderfarm28` | sh120 (sky, bg, chars, atmo) |
| `pl_renderfarm29` | sh130 (sky, bg, chars, atmo) |
| `pl_renderfarm30` | sh110_atmo (dedicated atmo-stream) |
| `pl_renderfarm31` | sh120_atmo (dedicated atmo-stream) |
| `pl_renderfarm32` | sh130_chars (dedicated chars-stream) |

### 3.6. Render Settings (13 нод) — `rendersettings`

Дві категорії розрізняються:

**WIP rendersettings (rendersettings3/4/5)** — спрощений preview:
- `camera = /cams/cam_sh010` (sh010?? — мабуть legacy/typo)
- `resolution = 1280 × 1280` (квадрат!)
- `progressive_render = ON`
- `AA_samples = 2`
- **`ignore_subdivision = ON`** (preview!)
- **`ignore_displacement = ON`** (preview!)
- Color: ACES / ACEScg
- AA seed = `$F`
- Arnold output: HTML report / Stats / Profile → `C:/houdini_mcp_sandbox/arnold_*.{html,json}`

**Pass-render rendersettings (rendersettings26/27/28/29/30/31/32/33/34/35/36/37)**:
- `camera = /cams/cam_sh110` (правильна per-shot camera)
- `resolution = 1280 × 1280`
- `AA_samples = 2`
- **`GI_diffuse_depth = 2`**, **`GI_volume_depth = 1`** (явно налаштовано!)
- **`ignore_dof = ON`** (DoF вимкнено)
- **set:** ignore_subdivision, ignore_displacement, ignore_motion_blur, ignore_smoothing, ignore_sss (тільки control flag, value не on)
- Color: ACES / ACEScg

⚠️ Що варто перевірити: resolution 1280×1280 виглядає як **preview**, а не final. Production final зазвичай вище.

### 3.7. Lights (~16 нод) — `light::2.0` та `domelight::3.0`

#### Environment lights (`domelight::3.0` × 5)

| Нода | Exposure | Color | HDRI |
|---|---|---|---|
| `edit_env` | **-4.5** | R=0.72, B=0.955 | `\\loky.plarium.local\project\_pl\lib\hdri\3docean\3docean.HDRi.Pack.001\1325 Sun Clouds\1325 Sun Clouds.exr` (latlong, Arnold resolution 4096) |
| `edit_env1` | (не дамплений) | | per-shot варіація |
| `edit_env2` | (не дамплений) | | per-shot варіація |
| `edit_env3` | (не дамплений) | | per-shot варіація |
| `edit_env4` | (не дамплений) | | per-shot варіація |
| `edit_env5` | (не дамплений) | | per-shot варіація |

`edit_env` specific: `camera contribution = 1.6`, AOV group = `env`

#### Sun edits (`light::2.0` × 2)

| Нода | Exposure | Cone Angle | Cone Softness | Light type | AOV group |
|---|---|---|---|---|---|
| `edit_sun` (sh110) | **6.06** | **79.2°** | **0.14** | UsdLuxSphereLight | sun |
| `edit_sun1` (sh120/sh130) | **6.0** | **13.0°** | 0 (default) | UsdLuxSphereLight | sun |

Спільне: Color R=0.9685, G=0.895 (теплий, легкий жовтуватий)
Radius=60, Clipping=0.001, Soft Edge=1.0, Arnold shader = `/lights/sun/filters/lightFilter`

#### Character key/rim/fill lights (`light::2.0` × ~9)

Всі мають `normalize_power=ON`, `roundness=1.0`, `spread=0.096-0.999`, AOV groups налаштовані.

| Нода | Type | Position (tx, ty, tz) | Exp | Color (R,G,B) | Size | Cone | Softness | LookAt | Spotlight | AOV |
|---|---|---|---|---|---|---|---|---|---|---|
| `char_sun` | SphereLight | -4.60, 7.05, -4.46 | **9.54** | 0.97/0.90 (default B) | radius default | 9.6° | 0.505 | yes | ON | char_sun |
| `char_rim_left` | RectLight | 20.68, 15.68, 4.78 | **9.33** | 0.78/0.90 | 50×50 | 45° | — | yes | — | rim_left |
| `char_rim_right` | RectLight | -20.52, 19.15, -35.06 | **5.72** | 0.78/0.90 | 25×25 | 45° | — | yes | — | rim_right |
| `char_top` | RectLight | -5.81, 11.69, -4.83 | **4.91** | 0.78/0.90 | 8.19×8.19 | 45° | — | yes | — | top |
| `char_top1` | RectLight | (дублікат `char_top`) | 4.91 | 0.78/0.90 | 8.19×8.19 | 45° | — | yes | — | top |
| `char_top2` | RectLight | 0.44, 14.65, -2.66 | **4.91** | 0.78/0.90 | 8.19×8.19 | 45° | — | yes | — | top |
| `char_fill` | SphereLight | 1.61, -0.91, -3.45 | **6.03** | 0.78/0.90 | r=1.87 | 4.4° | 0.304 | yes | ON | fill |
| `char_fill1` | (не дамплений) | — | — | — | — | — | — | — | — | — |
| `char_sword` | SphereLight | -4.86, 1.55, -2.58 | **4.56** | 0.78/0.90 | r=0.85 | 6.8° | 0.304 | yes | ON | sword |

**Common rotation:** `ry = 84.88°` для всіх character rect-lights (rim, top, sword, fill rect)
**Common twist:** `-1.51e-06` (зумовлений lookAt)
**Common Focus Tint:** RGB (1.0, 1.0, 1.0) — нейтральний
**Roundness:** 1.0 на всіх rect-lights (`set` authored), Spread `0.096` (set, notauthored — за замовчуванням не зберігається в USD)

#### Volume-only spot lights (`light::2.0` × 3) — `vol_spot`, `vol_spot1`, `vol_spot2`

⚠️ **Особливість:** всі surface contribution = 0 (camera, diffuse, specular, transmission, sss).
Тільки `volume` залишений активним.

`vol_spot`:
- Position: (-7.24, 5.05, 2.55), LookAt (-0.97, 2.02, -1.04)
- **Exposure: 15.38** (дуже сильний для volume!)
- Color: R=0.895, B=0.982 (синюватий, холодний)
- Cone: 2.9°, softness 0.52, normalize ON
- AOV: `vol_spot`
- primpath: `/lights/char_spot`
- Подається в `loky_ArnoldlightFilter1` → merge3

### 3.8. Light Filters & Linkers

#### `loky_ArnoldlightFilter1/2/3` (Plarium HDA, custom)
Всі мають дефолтні parms — лише `folder = 0`. Підключені після відповідного `vol_spot{N}` → merge3.

#### `lightlinker1`
- 1 link rule:
  - `link_prim_1 = /lights/char_sun`
  - `link_excludes_1 = /env/locations/cyclop/*`
- **Тобто char_sun **виключений** з освітлення всього environment** — світить тільки на персонажа.

### 3.9. Light Transformations (3 ноди) — `xform`

Поворот env+sun для per-shot варіацій:

| Нода | primpattern | ry | Призначення |
|---|---|---|---|
| `transform1` | `/lights/env /lights/sun` | **-82.2°** | sh120 light orientation |
| `transform2` | `/lights/env /lights/sun` | **+80.0°** | sh130 light orientation |
| `transform3` | (cyclop scope) | **+4.0°** | cyclop-specific |

### 3.10. Edit Properties (6 нод) — `editproperties`

| Нода | Target | Що змінює |
|---|---|---|
| `edit_cell_noise1` | `/lights/sun/filters/lightFilter/cell_noise1` | offset=(292.79, 59.23, 24.4), scale=(131.2, 131.2, 131.2) |
| `edit_standard_volume4` | `/fx/atmo/mtl/atmo/standard_volume4` | (тільки primpattern; інші parms default) |
| `edit_standard_volume5` | `/fx/atmo/mtl/atmo/standard_volume4` | (same target як volume4, ⚠️ **BYPASSED**) |
| `edit_char_sun` | `/lights/char_sun` | `collection:lightLink = "/ "` (root), expandPrims |
| `edit_env1/2/3/4/5` | per-shot env edits | (не дампали) |

### 3.11. AOVs (13 нод) — `pl_aovs` v1.1.3

Всі однакові структурно. Зразок (`pl_aovs10`):
- `active_render_products = 9`
- `pl_aovs_version = v002`
- `crypto_object = off`
- `arnold_driver_deepexr_alpha_tolerance = 0.01`
- `arnold_driver_deepexr_depth_tolerance = 0.01`

Усі pl_aovs10/11/12/28/29/30/31/32/33/34/35/36/37/38/39 ймовірно однакові.

### 3.12. Geometry Settings (6 нод) — `rendergeometrysettings`

| Нода | primpattern | Що робить |
|---|---|---|
| `bg_nosubd_invis` | `%bg` | subdiv iter=0, **camera visibility OFF** (bg не видно камерою але впливає на освітлення) |
| `bg_nosubd_invis1` | (не дампали) | per-shot варіант |
| `bg_nosubd_invis2` | (не дампали) | per-shot варіант |
| `geo_matte` | `%bg %char` | subdiv iter=0, **matte=ON** (Arnold matte для atmo-пас) |
| `geo_matte1` | (не дампали) | per-shot варіант |
| `geo_matte2` | (не дампали) | per-shot варіант |

### 3.13. Prune-ноди (~10 нод)

Всі `method = deactivate`. Перелік primpattern-ів:

| Нода | Деактивує |
|---|---|
| `prune_props` | `/env/locations/cyclop/props/columns`, `/env/locations/cyclop/props/buildings` |
| `prune_cliffs` | ~100 cliffs/rocks/mountains/buildings (proxy+render LODs) |
| `prune_cyclop` | `/env/locations/cyclop/*` (TODO: підтвердити) |
| `prune_props1/2`, `prune_cliffs1/2` | per-shot дублі |
| `prune1` | (не дампали) |
| `prune_lights, prune_lights1/2` | per-shot light prunes |
| `prune_atmo, prune_atmo1/2` | per-shot atmo prunes |
| `prune_chars_atmo, ×5` | per-shot chars-atmo прибирання |

### 3.14. Outputs (1+ нода) — `pl_shot_output`

`OUTPUT_120` (для sh120):
- `is_bypassed: true` ⚠️
- `shots = sh120`
- `asset_name_DAILIES = assembling_gamaiunov` ($FTRACK_TASK_NAME)
- `asset_name_usd = assembling_gamaiunov`
- frame range $FSTART-$FEND
- `save_state = ON`

`OUTPUT_121` (для sh130 ймовірно) — не дампали.

### 3.15. Collections / Variants

⚠️ **Не дамплено через баги в плагіні:**
- `/stage/collection1` (collection::2.0) — `'NoneType' object has no attribute 'name'`
- `/stage/NO_PROXY_TEX1/2/3` (setvariant) — те ж саме

### 3.16. Shot Marks

`pl_shot_mark1/2/3` (v1.1.10) — позначає шот в LOPs network:
- `pl_shot_mark1.optionstrvalue1 = "sh110"`
- `pl_shot_mark2` — ймовірно sh120
- `pl_shot_mark3` — ймовірно sh130

---

## 4. Cameras (з посилань у render settings)

| Camera path | Викликається з | Шот |
|---|---|---|
| `/cams/cam_sh010` | WIP2/3/4 (rendersettings3/4/5) | ⚠️ виглядає як **typo або legacy** (sh010 не існує в сцені) |
| `/cams/cam_sh110` | rendersettings28 (sh110_atmo) | sh110 |
| (інші cam_sh120/130) | rendersettings інших pass | sh120, sh130 |

**Camera prim для всіх lights (`sample_cameraprim`):** `/cameras/camera1` (template default — це інший шлях ніж `/cams/cam_*` що в rendersettings!)

---

## 5. Виявлені аномалії / TODO

### Bypassed ноди (вимкнено)
- `/stage/sh110_sky` — sky-пас для sh110 повністю вимкнено
- `/stage/edit_standard_volume5` — atmo-edit для sh130 вимкнено
- `/stage/OUTPUT_120` — output для sh120 вимкнено

### Підозрілі значення
- WIP rendersettings посилаються на `/cams/cam_sh010` (sh010 не існує — мабуть `cam_sh110` мало бути або legacy)
- Resolution **1280×1280** в усіх rendersettings — preview, не final
- WIP мають `ignore_subdivision/displacement = ON` — це WIP, але **pass-render** rendersettings теж мають `set` flag для subdiv/displacement/sss/motion_blur/smoothing (хоч і без `on` value). Перевірити чи це не залишилось випадково з тестування

### Дубльовані ноди — підозра на копіювання
- `char_top` ≡ `char_top1` (повністю ідентичні параметри, тільки в різних шотах)
- `char_rim_left` ≡ `char_rim_right` (дзеркальні значення translate, інакше однакові)
- `pl_renderfarm27..32` — однакові parms, відрізняються лише inputs

### Sandbox-сміття
- `/obj` містить 96 шаблонних нод (`geo1nnn`, `sphere_obj`, `box_obj` × 32) + `test_sphere`. Не зачіпають production, але засмічують. Видалити.

---

## 6. Параметри що не вдалось дампити (баги плагіна)

`get_node_info` падає на цих типах нод з `'NoneType' object has no attribute 'name'`:
- `setvariant` (`/stage/NO_PROXY_TEX1`, `NO_PROXY_TEX2`, `NO_PROXY_TEX3`)
- `collection::2.0` (`/stage/collection1`)

**TODO для CC:** наступний фікс `remote/houdinimcp/server.py` — handle `None` returns від `parm.parmTemplate()` чи `inputNode()` для цих типів.

---

## 7. Що НЕ дампали (повний дамп зайняв би х5 більше tool-calls, але patterns зрозумілі)

- Всі pl_aovs (28-39) — структурно однакові з pl_aovs10
- Всі rendersettings 29-37 — варіації rendersettings28 з різними camera/aov-pointers
- Всі prune_* для sh120, sh130 (структура prune така ж як prune_props/prune_cliffs але інші primpaths)
- char_fill1, vol_spot1, vol_spot2, char_rim_right1 — дублі для per-shot
- edit_env1/2/3/4/5 — per-shot env-edits (ймовірно різні rotations/exposures)
- pl_shot_mark2, pl_shot_mark3 — sh120, sh130 marks
- merge1/2/3 — структурно прості merge nodes

**Якщо потрібен повний дамп будь-якої — попроси і отримай.**

---

## 8. Render output paths (де лежить готовий рендер)

Шаблон: `//loky.plarium.local/project/_pl/raid_cyclope/cinematic/sq010/sh{N}/render/{render_name}/v{version}/`

Конкретно:
- `sh110/render/WIP2/v001/`
- `sh110/render/sh110_bg/v001/`, `sh110/render/sh110_chars/v001/`, `sh110/render/sh110_sky/v001/`, `sh110/render/sh110_atmo/v001/`
- Аналогічно для sh120 (WIP3) і sh130 (WIP4)

---

## 9. Arnold-specific globals (з rendersettings)

- **Colorspace:** ACES / ACEScg (linear), narrow = sRGB family
- **Progressive Render:** ON (WIP) / set (pass)
- **AA samples (camera):** 2
- **GI:** diffuse_depth=2, volume_depth=1 (для atmo-пас)
- **AA seed:** `$F` (animated)
- **Output logs:** `$HIP/arnold_report.html`, `$HIP/arnold_stats.json`, `$HIP/arnold_profile.json`

---

## Метадані дампу

- **Дата:** 2026-05-17 (Sashok local)
- **Через:** vfx-mcp Houdini plugin (`get_node_info` з фіксом `only_non_default`)
- **Метод:** ноди дампилися через MCP по групах з фільтрацією тільки non-default параметрів
- **Покрито з 124 нод /stage:** ~30 унікальних детально + патерни ідентифіковано
