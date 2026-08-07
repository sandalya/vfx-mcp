# Nuke Comp: збірка layer-branch з 4 Read-нод

**Проект (приклад):** `raid_echoes_of_oz / cinematic / sq010 / sh330`
**Layer у прикладі:** `bg`
**Захоплено:** 2026-08-06, через `nuke_mcp_plugin.py` (`get_nodes_in_view` / `execute_code`), живий скрипт на pc137

---

## TL;DR

Sashok будує комп із **layer-branches** (`fg`, `bg`, `floorVolume`, `atmo`, `clouds`, `dem_debris`, `dem_vol1` тощо). Кожен branch — рівно **4 Read-ноди**, по одній на render pass, які зводяться в один потік:

```
lights_product  ─┐
beauty_product  ─┼─→ (ShuffleCopy chain)  ─→  + tech_product (Copy)  ─→  + crypto_product (Copy, через Cryptomatte)
tech_product    ─┘
crypto_product  ──────────────────────────────────────────────────────────↗
```

- **beauty_product** = rgba + emission
- **tech_product** = Zg, Zc, P, mv (технічні/utility паси)
- **lights_product** = per-light AOV
- **crypto_product** = Cryptomatte-канали

Весь шот-комп — це N таких layer-branches, зведених разом.

---

## Конвенція шляхів

```
//loky.plarium.local/project/_pl/<project>/cinematic/<sequence>/<shot>/render/<layer>/v0XX/<pass>_product.%04d.exr
```

Приклад (layer `bg`):
```
.../raid_echoes_of_oz/cinematic/sq010/sh330/render/bg/v007/beauty_product.%04d.exr
.../raid_echoes_of_oz/cinematic/sq010/sh330/render/bg/v007/lights_product.%04d.exr
.../raid_echoes_of_oz/cinematic/sq010/sh330/render/bg/v006/tech_product.%04d.exr
.../raid_echoes_of_oz/cinematic/sq010/sh330/render/bg/v006/crypto_product.%04d.exr
```

**Важливо:** 4 паси одного "живого" layer-branch не обов'язково однієї версії (тут: beauty/lights=v007, tech/crypto=v006 — різні). Паси рендеряться/перерендеряться незалежно, тож version-swap тулза має керувати версією кожної з 4 Read-нод окремо, не припускаючи, що вони рухаються в лок-степі.

---

## Старі версії не видаляються

У референс-графі лежало 5 *зайвих*, відключених Read-нод (`beauty_product` / `lights_product` на v001, v002, v004, v006) — історія/порівняння, не живі. **Наслідок:** щоб зрозуміти, яка Read жива, треба дивитись що реально йде далі по ланцюгу (`inputs`), а не просто на список нод у графі. Пара таких сирітських Read-нод також живить `LayerContactSheet`-ноду збоку — для візуального порівняння версій поза основним потоком.

---

## Топологія збірки (референс-граф)

```
Read12(lights v007) ─┐
Read35(beauty v007) ─┼→ ShuffleCopy8 → ShuffleCopy1 ─┐
                      ┘                               ├→ Copy18 ─┐
Read2(tech v006)  ─────────────────────────────────────┘         ├→ Copy19  ← Cryptomatte3 ← Dot38 ← Read14(crypto v006)
                                                                   ┘
```

`Copy19` — точка, де всі 4 паси нарешті зведені в один вузол. Злиття всюди йде через **Copy**-ноди (не ChannelMerge — попередній прохід аналізу помилково прочитав ChannelMerge-ноду, яку користувач потім видалив як таку, що плутала аналіз; виправлено 2026-08-06).

## Crypto matte extraction (після Copy19)

Далі від `Copy19` йде ланцюжок `Copy17 → Copy23 → Copy10 → Copy11 → Copy6 → Copy7 → Copy8 → Copy9` — кожен доливає ще одну ізольовану crypto-матовку. Джерело — прямий Dot-спайн від того самого crypto Read:

```
Read14(crypto) → Dot38 → Dot62 → Dot63 → Dot15 → Dot18 → Dot23 → Dot30 → Dot17 → Dot32
                   ↓        ↓       ↓       ↓       ↓        ↓       ↓       ↓       ↓
              Cryptomatte3 6      7       2      11        10       9      5       8
```

9 окремих Cryptomatte-нод, кожна ізолює свій об'єкт/матеріал. `Roto4` вшита в той самий Copy-ланцюг для матовки, яку crypto не бере чисто.

Окремо є два бічні відгалуження (`Copy1`, `Copy12`) — ізольовані прев'ю конкретної crypto-вибірки, не частина основного накопичувального ланцюга.

---

## Knob-level деталі + офіційний init-шаблон (`sh320/bg v014`)

**Захоплено:** 2026-08-07, через `get_node_knobs` (plugin-команда, дампить `knob.toScript()` — той самий формат, що пишеться у `.nk`-файл — для всіх non-default knob'ів + список `inputs` кожної ноди). Перший приклад вище (`sh330/bg`) давав лише топологію одного реального branch; тут — Sashok навмисно перебудував той самий branch у **чистий, повторюваний шаблон** (порожня Cryptomatte, generic назви каналів) саме для того, щоб це стало основою init-скрипта. Знайдено через `get_nodes_in_view` (без виділення), бо саме ці 13 нод були у в'юпорті:

```
Read75(lights v014) ┐
Read74(beauty v014) ┴→ ShuffleCopy4 "RGBA IN" → ShuffleCopy9 "DIR EMISSION" → ShuffleCopy11 "INDIR EMISSION" ─┐
              (Read74 ще двічі як 2-й вхід у ShuffleCopy9 і ShuffleCopy11)                                     │
Read73(tech v014) ─────────────────────────────────────────────────────────────────────────────→ Copy16 ──────┤
                                                                                                                │
                                            ShuffleCopy12 "POS IN" ←── Copy16 (as in0) + Read73 (as in1, знову)│
                                                    │
                                                    ▼
Read72(crypto v014) → Dot48 → Cryptomatte9 (порожня) ────────────────────────────────────────────────→ Copy24
                                                                (ShuffleCopy12 as in0, Cryptomatte9 as in1)

StickyNote10, label="BG" — маркує branch зверху
```

Реальний порядок по `inputs` (не по позиції на екрані — вона оманлива, `xpos`/`ypos` в дампі не відповідають порядку з'єднань):
**ShuffleCopy4 → ShuffleCopy9 → ShuffleCopy11 → Copy16 → ShuffleCopy12 → Copy24**

### Крок 1 — ShuffleCopy4, label "RGBA IN"
- `input0` = lights Read, `input1` = beauty Read
- knobs: `red=red`, `green=green`, `blue=blue`
- Просте злиття rgba з обох Read (нічого екзотичного)

### Крок 2 — ShuffleCopy9, label "DIR EMISSION"
- `input0` = ShuffleCopy4 (попередній крок), `input1` = beauty Read (вдруге)
- knobs: `in=direct_emission`, `alpha=alpha2`, `black=red`, `white=green`, `red2=blue`, `out2=direct_emission`

### Крок 3 — ShuffleCopy11, label "INDIR EMISSION"
- `input0` = ShuffleCopy9, `input1` = beauty Read (втретє)
- knobs: `in=indirect_emission`, `alpha=alpha2`, `black=red`, `white=green`, `red2=blue`, `out2=indirect_emission`
- Кроки 2 і 3 — **той самий рецепт knob-у-knob**, змінюється лише `in`/`out2` (яка AOV-layer з beauty витягується) і `label`. Це повторюваний патерн: щоб додати ще одну AOV-layer з beauty, копіюєш ShuffleCopy-ноду і міняєш два значення.
- Семантика `black`/`white`/`red2` як імен knob (не значень) — специфіка ShuffleCopy UI, записано як є з `toScript()`; не інтерпретувати далі без підтвердження Sashok.

### Крок 4 — Copy16 (без окремого label — "merge tech")
- `input0` = ShuffleCopy11, `input1` = tech Read
- knobs: `from0=Zc.X → to0=depth.Z`, `from1=Zg.X → to1=Zg.X`, `from2=mv.X → to2=mv.X`, `from3=mv.Y → to3=mv.Y`
- `mix=0.48` — блендинг з коефіцієнтом, не пряме 1:1 копіювання; конкретне число специфічне для цього branch, копіювати як є

### Крок 5 — ShuffleCopy12, label "POS IN"
- `input0` = Copy16 (попередній крок), `input1` = tech Read (**вдруге** — tech Read живить і Copy16, і цю ноду, кожен раз за інший набір каналів)
- knobs: `in=Pg`, `alpha=alpha2`, `black=red`, `white=green`, `red2=blue`, `out2=Pg`
- Той самий ShuffleCopy-рецепт, що й кроки 2-3, але джерело — tech Read, не beauty, і layer — `Pg` (position pass)

### Крок 6 — Cryptomatte9 (порожня) + Dot48 + Copy24
- `Read72(crypto) → Dot48 → Cryptomatte9` — Cryptomatte9 у шаблоні **порожня** (`matteList` відсутній, `pickerAdd` всі нулі) — це навмисно, готова точка для ручного пікінгу об'єктів
- `Copy24`: `input0` = ShuffleCopy12, `input1` = Cryptomatte9; knobs `from0=rgba.alpha → to0=mask.a` — `mask.a` тут **generic placeholder**-назва каналу (не `<об'єкт>.matte`, як у першому реальному прикладі вище) — після пікінгу в Cryptomatte9 художник перейменовує канал на щось конкретне вручну

### StickyNote10 — маркер гілки
- knobs: `label="BG"`, `tile_color=0x353535ff`, `gl_color=0x797979ff`, `note_font_size=222`
- Init-скрипт має створювати такий самий StickyNote над кожним новим branch, з `label` = назва layer (bg/fg/atmo/...), тим самим кольором і розміром шрифту — це візуальна конвенція Sashok для підпису гілок

### Scope для Function 1 (init) — підтверджено Sashok
Init-скрипт створює: **4 Read + ShuffleCopy4("RGBA IN") → ShuffleCopy9("DIR EMISSION") → ShuffleCopy11("INDIR EMISSION") → Copy16(tech merge) → ShuffleCopy12("POS IN") → Cryptomatte(порожня) → Copy24(mask.a placeholder) + StickyNote(label=layer name)** — і на цьому зупиняється. Ізоляцію конкретних matte (додавання нових Cryptomatte/Copy-нод по одній на об'єкт, як у першому прикладі sh330/bg) художник робить вручну — це рішення "які об'єкти ізолювати", яке не автоматизується.

---

## Навіщо це задокументовано — актуальний запит

Ручна заміна 4 Read-нод на layer-branch (нова версія, фікс рендеру тощо) зараз ручна, і з N branches × 4 Read кожен — це error-prone при масштабуванні на цілий шот. Потрібні:

1. **Ініціалізація нового layer-branch** — скрипт створює 4 Read-ноди + assembly chain (ShuffleCopy → Copy → Cryptomatte-merge) з імені layer.
2. **Version management на існуючих branches** — bump/pin версії, ведення кольору/розташування нод при додаванні нових branches поряд зі старими.

Ще не реалізовано — це референс для майбутньої розробки цих скриптів.
